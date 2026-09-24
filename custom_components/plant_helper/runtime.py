from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import logging
from pathlib import Path
from typing import Any, Mapping

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .domain.runtime import RuntimeCollection
from .domain.interpretation import interpret_indoor, interpret_outdoor
from .domain.temporal.history import ObservationHistory
from .domain.temporal.humidity import (
    HUMIDITY_MIN_SAMPLES,
    HUMIDITY_WINDOW_HOURS,
    humidity_context,
)
from .domain.temporal.light import (
    LIGHT_MIN_SAMPLES,
    LIGHT_WINDOW_HOURS,
    light_context,
)
from .domain.temporal.status import merge_health
from .domain.temporal.season import is_dormant
from .domain.temporal.baseline import BaselineSamples, derive_band, update_samples
from .domain.learning import LearningRuntime
from .domain.temporal.moisture import TemporalMoistureState, evaluate_moisture
from .domain.temporal.observation import PlantObservation
from .domain.temporal.store import STORE_VERSION, restore_store, serialize_store
from .domain.forecast import (
    ForecastCollector,
    request_for as forecast_request_for,
)
from .domain.air_quality import (
    AirQualityCollector,
    request_for as air_quality_request_for,
)
from .domain.enrichment import (
    ChainedSpeciesEnrichment,
    INaturalistAdapter,
    PerenualAdapter,
    ProviderError,
    TrefleAdapter,
    select_exact_common_name_candidate,
)
from .domain.storage import PlantHelperStorage, StorageBackend
from .physical import PhysicalSubscriptions
from .domain.physical import PlantPhysicalProcessor
from .domain.remove_plant import (
    RemoveHooks,
    RemoveResult,
    async_reconcile_pending_removals,
    async_remove_plant,
)
from .weather import OpenMeteoClient

_LOGGER = logging.getLogger(__name__)

# Debounce for temporal-store writes. Sensor pushes are frequent, so writes are
# coalesced over this window and flushed on a timer and on unload, rather than
# once per observation.
TEMPORAL_SAVE_DELAY = 30.0

# How often the background tick advances durations without a sensor push. This
# is what makes staying_wet and too_wet reachable while moisture is unchanged.
# It records no observation and makes no provider or weather request.
TEMPORAL_TICK_SECONDS = 60

_SOURCE_TO_STATE = {
    "soil_moisture": "moisture",
    "soil_temperature": "temperature",
    "lux": "light",
    "humidity_sensor": "humidity",
    "battery": "battery",
}


@dataclass(slots=True)
class PlantHelperRuntime:
    """Live Home Assistant runtime for Plant Helper."""

    plants: RuntimeCollection = field(default_factory=RuntimeCollection)
    platform_callbacks: dict[str, Any] = field(default_factory=dict)
    entities: dict[str, dict[str, Any]] = field(default_factory=dict)
    storage: PlantHelperStorage | None = None
    hass: HomeAssistant | None = None
    entry_id: str | None = None
    physical_processor: PlantPhysicalProcessor | None = None
    physical_subscriptions: PhysicalSubscriptions | None = None
    species_enrichment: ChainedSpeciesEnrichment | None = None
    species_context: dict[str, tuple[str, dict[str, Any]]] = field(default_factory=dict)
    weather_client: Any = None
    forecast_collector: ForecastCollector | None = None
    air_collector: AirQualityCollector | None = None
    weather_options: dict[str, Any] = field(default_factory=dict)
    forecast_data: dict[str, Any] | None = None
    air_snapshot: Any = None
    weather_unsub: Any = None
    temporal_history: dict[str, ObservationHistory] = field(default_factory=dict)
    temporal_state: dict[str, TemporalMoistureState] = field(default_factory=dict)
    temporal_store: Any = None
    temporal_unsub: Any = None
    image_proxy: Any = None
    image_gc_unsub: Any = None
    learning: Any = None
    _blocked: set[str] = field(default_factory=set)

    async def async_initialize(self, backend: StorageBackend) -> None:
        """Load persistent storage before platforms are forwarded."""
        storage = PlantHelperStorage(backend)
        snapshot = await storage.async_load()
        self.storage = storage
        self.plants.load(snapshot.data["plants"])

    async def async_start(self, hass: HomeAssistant, entry_id: str) -> None:
        """Connect stored plants to current Home Assistant source states."""
        self.hass = hass
        self.entry_id = entry_id
        self.physical_processor = PlantPhysicalProcessor(
            self.plants,
            self.evaluate,
            self.current_environment,
        )
        self.physical_subscriptions = PhysicalSubscriptions(
            hass, self.physical_processor
        )
        for plant_uuid, plant in self.plants.plants.items():
            await self.register_listeners(plant_uuid, plant.config)
            await self.evaluate(plant_uuid)
            species = plant.config.get("species")
            if species:
                hass.async_create_task(
                    self.schedule_enrichment(plant_uuid, str(species)),
                    f"Plant Helper species enrichment for {plant_uuid}",
                )
        await self._refresh_weather()
        interval = int(self.weather_options.get("update_interval", 300) or 300)
        self.weather_unsub = async_track_time_interval(
            hass, self._weather_tick, timedelta(seconds=interval)
        )
        self.temporal_unsub = async_track_time_interval(
            hass, self._temporal_tick, timedelta(seconds=TEMPORAL_TICK_SECONDS)
        )

    def require_storage(self) -> PlantHelperStorage:
        if self.storage is None:
            raise RuntimeError("plant_helper_storage_not_initialized")
        return self.storage

    async def async_configure_weather(
        self, hass: HomeAssistant, options: Mapping[str, Any]
    ) -> None:
        """Build the Open-Meteo forecast and air-quality collectors."""
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        session = async_get_clientsession(hass)
        self.weather_client = OpenMeteoClient(session)
        self.forecast_collector = ForecastCollector(
            self.weather_client.fetch_forecast
        )
        self.air_collector = AirQualityCollector(
            self.weather_client.fetch_air_quality
        )
        self.weather_options = dict(options)

    async def async_configure_temporal(
        self, hass: HomeAssistant, entry_id: str
    ) -> None:
        """Open the temporal store and restore rolling history and state.

        Runs before async_start so restored history is in place before the
        first evaluation. Restored data is pruned to plants that still exist,
        and timestamp validation lives in the pure store module.
        """
        self.temporal_store = Store(
            hass, STORE_VERSION, f"{DOMAIN}.temporal.{entry_id}"
        )
        data = await self.temporal_store.async_load()
        if not data:
            return
        now = datetime.now(timezone.utc)
        histories, states = restore_store(data, now)
        known = set(self.plants.plants)
        self.temporal_history = {
            uuid: history for uuid, history in histories.items() if uuid in known
        }
        self.temporal_state = {
            uuid: state for uuid, state in states.items() if uuid in known
        }

    def _temporal_snapshot(self) -> dict[str, Any]:
        return serialize_store(self.temporal_history, self.temporal_state)

    def _schedule_temporal_save(self) -> None:
        if self.temporal_store is not None:
            self.temporal_store.async_delay_save(
                self._temporal_snapshot, TEMPORAL_SAVE_DELAY
            )

    async def async_configure_images(self, hass: HomeAssistant) -> None:
        """Stand up the species image proxy and register its HTTP view.

        The proxy fetches, sanitizes, thumbnails, caches, and serves species
        photos from a local authenticated endpoint so the frontend never loads a
        raw provider URL. Construction touches the filesystem (cache dir), so it
        runs in the executor.
        """
        from .domain.image_proxy import SpeciesImageProxy
        from .image_client import ImageDownloader
        from .image_proxy import PlantHelperImageView
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        session = async_get_clientsession(hass)
        cache_dir = Path(hass.config.path("plant_helper", "images"))
        downloader = ImageDownloader(session)
        self.image_proxy = await hass.async_add_executor_job(
            SpeciesImageProxy, cache_dir, downloader.fetch
        )
        hass.http.register_view(PlantHelperImageView(self.image_proxy))
        self.image_gc_unsub = async_track_time_interval(
            hass, self._image_gc_tick, timedelta(hours=24)
        )

    @callback
    def _image_gc_tick(self, _now: datetime) -> None:
        if self.hass is not None and self.image_proxy is not None:
            self.hass.async_create_task(
                self._run_image_gc(), "Plant Helper image cache cleanup"
            )

    async def _run_image_gc(self) -> None:
        if self.hass is None or self.image_proxy is None:
            return
        await self.hass.async_add_executor_job(self.image_proxy.garbage_collect)

    async def async_configure_learning(self) -> None:
        """Instantiate the learned-baseline runtime over the existing store.

        Best-effort: if learning cannot load, the engine simply keeps using the
        static profile bands, which is the pre-learning behavior.
        """
        if self.storage is None:
            return
        learning = LearningRuntime(self.storage)
        try:
            await learning.load()
        except Exception:
            _LOGGER.debug("Learned-baseline load failed; using profile bands", exc_info=True)
            return
        self.learning = learning

    async def _learning_step(
        self,
        plant_uuid: str,
        placement: str,
        history: ObservationHistory,
        now: datetime,
        confidence: str,
        record: bool,
    ) -> tuple[tuple[float, float] | None, str]:
        """Return (learned band or None, calibration state), fully defensively.

        Any failure yields (None, "learning") so the moisture engine falls back
        to the profile band and the core evaluation never breaks. On the record
        path it also accumulates cycle samples and finalizes the baseline once
        the calibration gate passes.
        """
        learning = self.learning
        if learning is None:
            return None, "learning"
        try:
            if plant_uuid not in learning.placement:
                learning.placement[plant_uuid] = placement
                learning.calibrating.add(plant_uuid)
            state = learning.state(plant_uuid)
            if state.baseline.get("complete"):
                return (
                    float(state.baseline["low"]),
                    float(state.baseline["high"]),
                ), "calibrated"
            if not record:
                return None, "learning"
            samples = BaselineSamples.from_dict(state.active_samples)
            updated = update_samples(samples, history, now)
            learning.active_samples[plant_uuid] = updated.to_dict()
            if len(updated.troughs) > len(samples.troughs):
                await learning.set_active_samples(plant_uuid, updated.to_dict())
            derived = derive_band(updated, confidence, now)
            if derived is not None:
                low, high = derived
                await learning.set_baseline(
                    plant_uuid,
                    state.placement,
                    {"complete": True, "low": low, "high": high},
                )
                return (low, high), "calibrated"
            return None, "learning"
        except Exception:
            _LOGGER.debug("Learning step failed for %s", plant_uuid, exc_info=True)
            return None, "learning"

    async def _reset_learning(self, plant_uuid: str) -> None:
        """Drop a plant's learned baseline so it recalibrates. Best-effort."""
        learning = self.learning
        if learning is None:
            return
        try:
            learning.baselines.pop(plant_uuid, None)
            learning.active_samples[plant_uuid] = {}
            learning.calibrating.add(plant_uuid)
            await learning.set_active_samples(plant_uuid, {})
            await learning.set_baseline(plant_uuid, "indoor", {})
            await learning.set_baseline(plant_uuid, "outdoor", {})
        except Exception:
            _LOGGER.debug("Learning reset failed for %s", plant_uuid, exc_info=True)

    async def _attach_species_image(
        self,
        plant_uuid: str,
        species_key: str,
        data: Mapping[str, Any],
        attributes: dict[str, Any],
    ) -> None:
        """Fetch the provider image through the proxy and expose the local path.

        On any failure the raw provider URL is deliberately not surfaced; the
        plant simply shows no image until the next successful refresh.
        """
        source = data.get("image_url")
        if not source or self.image_proxy is None:
            return
        from .image_proxy import IMAGE_PATH

        try:
            cached = await self.image_proxy.refresh(species_key, str(source))
        except Exception as err:
            _LOGGER.warning("Species image could not be fetched for %s: %s", plant_uuid, err)
            return
        attributes["image_url"] = IMAGE_PATH.format(hash=cached.digest)

    def _coordinates(self) -> tuple[float | None, float | None]:
        latitude = self.weather_options.get("latitude")
        longitude = self.weather_options.get("longitude")
        if self.hass is not None:
            if latitude is None:
                latitude = self.hass.config.latitude
            if longitude is None:
                longitude = self.hass.config.longitude
        return latitude, longitude

    def _has_outdoor_plant(self) -> bool:
        return any(
            str(plant.config.get("placement")) == "outdoor"
            for plant in self.plants.plants.values()
        )

    def current_environment(
        self, _plant_uuid: str | None = None
    ) -> dict[str, Any]:
        """Return the latest cached Open-Meteo environment for evaluation."""
        return {"forecast": self.forecast_data, "air": self.air_snapshot}

    async def _refresh_weather(self) -> None:
        """Refresh cached weather when at least one plant needs it."""
        if self.forecast_collector is None or not self.plants.plants:
            return
        latitude, longitude = self._coordinates()
        if latitude is None or longitude is None:
            return
        now = datetime.now(timezone.utc)
        outdoor = self._has_outdoor_plant()
        try:
            snapshot = await self.forecast_collector.refresh(
                forecast_request_for(latitude, longitude, outdoor), now
            )
            self.forecast_data = snapshot.data
        except Exception:
            _LOGGER.debug(
                "Plant Helper forecast refresh failed", exc_info=True
            )
        if outdoor and self.air_collector is not None:
            request = air_quality_request_for(latitude, longitude, True)
            if request is not None:
                try:
                    self.air_snapshot = await self.air_collector.refresh(
                        request, now
                    )
                except Exception:
                    _LOGGER.debug(
                        "Plant Helper air quality refresh failed",
                        exc_info=True,
                    )
        for plant_uuid in list(self.plants.plants):
            await self.evaluate(plant_uuid)

    @callback
    def _weather_tick(self, _now: datetime) -> None:
        if self.hass is not None:
            self.hass.async_create_task(
                self._refresh_weather(), "Plant Helper weather refresh"
            )

    @callback
    def _temporal_tick(self, _now: datetime) -> None:
        if self.hass is None:
            return
        for plant_uuid, plant in self.plants.plants.items():
            if plant.removing or plant_uuid in self._blocked:
                continue
            self.hass.async_create_task(
                self.evaluate(plant_uuid, record=False),
                f"Plant Helper temporal tick for {plant_uuid}",
            )

    def _read_source(self, entity_id: str | None) -> Any:
        if self.hass is None or not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        return None if state is None else state.state

    async def register_listeners(
        self, plant_uuid: str, config: dict[str, Any]
    ) -> None:
        """Seed values and subscribe to every configured physical source."""
        if self.physical_subscriptions is None or self.physical_processor is None:
            raise RuntimeError("physical_runtime_not_started")
        self.physical_subscriptions.replace(plant_uuid, config)
        for source_key in _SOURCE_TO_STATE:
            entity_id = config.get(source_key)
            if entity_id:
                self.physical_processor.accept(
                    plant_uuid, source_key, self._read_source(entity_id)
                )

    async def replace_listeners(
        self, plant_uuid: str, config: dict[str, Any]
    ) -> None:
        await self.register_listeners(plant_uuid, config)

    async def evaluate(
        self, plant_uuid: str, environment: Any = None, *, record: bool = True
    ) -> None:
        """Produce stable user-facing states from physical and weather context.

        record=True (sensor push, CRUD, startup) stores a new observation.
        record=False (background tick) re-evaluates against the existing
        history so durations advance without recording a fresh sample, and only
        notifies listeners when the user-facing status actually changes.
        """
        plant = self.plants.plants.get(plant_uuid)
        if plant is None or plant.removing or plant_uuid in self._blocked:
            return

        state = plant.state
        moisture = state.get("moisture")
        profile = str(plant.config.get("profile", "balanced"))
        placement = str(plant.config.get("placement", "indoor"))
        previous = (
            state.get("care_status"),
            state.get("health"),
            state.get("needs_attention"),
        )

        env = environment if environment is not None else self.current_environment(plant_uuid)
        forecast = env.get("forecast") if env else None
        air = env.get("air") if env else None
        if placement == "outdoor":
            try:
                rain_limit = float(plant.config.get("rain_limit_mm") or 1.0)
            except (TypeError, ValueError):
                rain_limit = 1.0
            interpretation = interpret_outdoor(
                physical=state, forecast=forecast, air=air, rain_limit_mm=rain_limit
            )
        else:
            interpretation = interpret_indoor(
                physical=state, forecast=forecast, air=air
            )
        conditions = interpretation.conditions
        rain_suppression = (
            placement == "outdoor" and bool(conditions.get("rain_suppression"))
        )

        now = datetime.now(timezone.utc)
        history = self.temporal_history.get(plant_uuid)
        if history is None:
            history = ObservationHistory()
            self.temporal_history[plant_uuid] = history
        soil_temperature = state.get("temperature")
        light = state.get("light")
        humidity = state.get("humidity")
        if record:
            history.append(
                PlantObservation(
                    observed_at=now,
                    moisture=moisture,
                    soil_temperature=soil_temperature,
                    moisture_valid=moisture is not None,
                    soil_temperature_valid=soil_temperature is not None,
                    light=light,
                    humidity=humidity,
                    light_valid=light is not None,
                    humidity_valid=humidity is not None,
                )
            )
        temporal_env: dict[str, Any] = {
            "placement": placement,
            "rain_suppression": rain_suppression,
            "soil_temperature": soil_temperature,
            "humidity": state.get("humidity"),
            "growth_season": conditions.get("growth_season"),
            "season": conditions.get("season"),
            "day_length": conditions.get("day_length"),
        }
        if isinstance(forecast, dict) and forecast.get("et0_24h") is not None:
            temporal_env["et0_24h"] = forecast.get("et0_24h")
        confidence = history.confidence(now)
        band, calibration_state = await self._learning_step(
            plant_uuid, placement, history, now, confidence, record
        )
        decision, moisture_state = evaluate_moisture(
            history,
            self.temporal_state.get(plant_uuid),
            now,
            profile,
            temporal_env,
            band=band,
        )
        self.temporal_state[plant_uuid] = moisture_state
        self._schedule_temporal_save()

        light_ctx = light_context(
            history.rolling_mean(
                now,
                "light",
                "light_valid",
                window_hours=LIGHT_WINDOW_HOURS,
                min_samples=LIGHT_MIN_SAMPLES,
            )
        )
        humidity_ctx = humidity_context(
            history.rolling_mean(
                now,
                "humidity",
                "humidity_valid",
                window_hours=HUMIDITY_WINDOW_HOURS,
                min_samples=HUMIDITY_MIN_SAMPLES,
            )
        )
        health = merge_health(decision.health, light_ctx, humidity_ctx)

        care_attributes: dict[str, Any] = {
            "summary": decision.summary,
            "reason": decision.reason,
            "since": decision.since.isoformat() if decision.since else None,
            "confidence": decision.confidence,
            "drying_context": decision.drying_context,
            "light_context": light_ctx,
            "humidity_context": humidity_ctx,
            "dormant": is_dormant(temporal_env),
            "placement": placement,
        }
        if placement == "outdoor":
            care_attributes["rain_suppression"] = rain_suppression
            care_attributes["frost_hours"] = conditions.get("frost")
            care_attributes["exposure"] = list(conditions.get("exposure", ())) or None
        else:
            care_attributes["external_daylight"] = conditions.get("external_daylight")

        state["care_status"] = decision.status
        state["care_status_attributes"] = care_attributes
        state["health"] = health
        state["health_attributes"] = {"summary": decision.summary}
        state["needs_attention"] = decision.needs_attention
        state["needs_attention_attributes"] = {
            "reason": decision.reason if decision.needs_attention else None
        }
        state["calibration"] = calibration_state
        if calibration_state == "calibrated":
            calibration_summary = (
                "Judging against this plant's learned moisture range"
            )
        else:
            calibration_summary = (
                "Learning this plant's normal range; using the profile band meanwhile"
            )
        state["calibration_attributes"] = {"summary": calibration_summary}

        species = plant.config.get("species")
        if species:
            enriched = self.species_context.get(plant_uuid)
            if enriched is None:
                state["species_context"] = str(species)
                state["species_context_attributes"] = {
                    "scientific_name": str(species)
                }
            else:
                state["species_context"] = enriched[0]
                state["species_context_attributes"] = dict(enriched[1])
        else:
            self.species_context.pop(plant_uuid, None)
            state.pop("species_context", None)
            state.pop("species_context_attributes", None)

        current = (
            decision.status,
            health,
            decision.needs_attention,
        )
        if record or current != previous:
            self.plants.notify_updated(plant_uuid)

    async def async_configure_enrichment(
        self, hass: HomeAssistant, options: Mapping[str, Any]
    ) -> None:
        """Configure the chained iNaturalist, Trefle, and Perenual providers."""
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        session = async_get_clientsession(hass)
        perenual_key = str(options.get("perenual_api_key", "")).strip()
        trefle_key = str(options.get("trefle_api_key", "")).strip()

        async def request_json(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
            try:
                async with session.get(url, params=params, timeout=30) as response:
                    try:
                        body: Any = await response.json(content_type=None)
                    except Exception as err:
                        raise ProviderError("provider", response.status, "non-json response") from err
                    return {"http_status": response.status, "body": body}
            except ProviderError:
                raise
            except Exception as err:
                raise ProviderError("network", message=str(err)) from err

        async def inaturalist_request(query: str) -> Mapping[str, Any]:
            return await request_json(
                "https://api.inaturalist.org/v1/taxa/autocomplete",
                {"q": query, "rank": "species", "per_page": 10},
            )

        async def trefle_request(query: str) -> Mapping[str, Any]:
            if not trefle_key:
                return {"data": []}
            return await request_json(
                "https://trefle.io/api/v1/species/search",
                {"q": query, "limit": 10, "token": trefle_key},
            )

        async def perenual_request(query: str) -> Mapping[str, Any]:
            if not perenual_key:
                return {"data": []}
            return await request_json(
                "https://perenual.com/api/v2/species-list",
                {"q": query, "key": perenual_key},
            )

        self.species_enrichment = ChainedSpeciesEnrichment(
            INaturalistAdapter(inaturalist_request),
            TrefleAdapter(trefle_request, trefle_key),
            PerenualAdapter(perenual_request, perenual_key),
        )

    async def schedule_enrichment(self, plant_uuid: str, species: str) -> None:
        """Resolve a common name through the configured provider chain."""
        plant = self.plants.plants.get(plant_uuid)
        chain = self.species_enrichment
        if plant is None or chain is None or not species.strip():
            return
        try:
            candidates = await chain.discover(species)
            selected = select_exact_common_name_candidate(species, candidates)
            if selected is None:
                context_state = "ambiguous" if candidates else "not_found"
                context_attributes = {
                    "query": species,
                    "candidate_count": len(candidates),
                }
                self.species_context[plant_uuid] = (context_state, context_attributes)
                plant.state["species_context"] = context_state
                plant.state["species_context_attributes"] = dict(context_attributes)
                self.plants.notify_updated(plant_uuid)
                return
            result = await chain.enrich_selected(species, selected)
        except ProviderError as err:
            _LOGGER.warning("Species enrichment provider failure for %s: %s", plant_uuid, err.kind)
            return
        except Exception:
            _LOGGER.exception("Species enrichment failed for %s", plant_uuid)
            return
        plant.state["species_context"] = result.data.get("scientific_name", species)
        attributes = {
            key: result.data[key]
            for key in (
                "common_name",
                "scientific_name",
                "family",
                "genus",
                "watering_category",
                "sunlight_requirements",
                "provenance",
            )
            if result.data.get(key) not in (None, "", [], {})
        }
        attributes["providers"] = list(result.providers)
        context_state = str(result.data.get("scientific_name", species))
        await self._attach_species_image(plant_uuid, context_state, result.data, attributes)
        self.species_context[plant_uuid] = (context_state, dict(attributes))
        plant.state["species_context"] = context_state
        plant.state["species_context_attributes"] = dict(attributes)
        self.plants.notify_updated(plant_uuid)

    async def schedule_reconciliation(self, plant_uuid: str) -> None:
        plant = self.plants.plants.get(plant_uuid)
        if plant is not None:
            await self.register_listeners(plant_uuid, plant.config)
            await self.evaluate(plant_uuid)

    async def handle_placement_change(self, plant_uuid: str, *_args: Any) -> None:
        """A placement change relearns the baseline; providers stay optional."""
        await self._reset_learning(plant_uuid)

    async def handle_species_change(
        self, plant_uuid: str, species_change: Any = None, *_args: Any
    ) -> None:
        self.species_context.pop(plant_uuid, None)
        if getattr(species_change, "kind", "different_taxon") != "alias":
            await self._reset_learning(plant_uuid)
        await self.evaluate(plant_uuid)

    def destination_baseline_complete(self, *_args: Any) -> bool:
        return False

    async def cancel_tasks(self, plant_uuid: str) -> None:
        self.species_context.pop(plant_uuid, None)
        if self.physical_processor is not None:
            self.physical_processor.block(plant_uuid)

    async def unsubscribe_listeners(self, plant_uuid: str) -> None:
        if self.physical_subscriptions is not None:
            self.physical_subscriptions.unsubscribe(plant_uuid)

    async def block_evaluation(self, plant_uuid: str) -> None:
        self._blocked.add(plant_uuid)
        if self.physical_processor is not None:
            self.physical_processor.block(plant_uuid)

    def _owns_registry_entity(self, entity: Any, plant_uuid: str) -> bool:
        if entity.platform != DOMAIN:
            return False
        if self.entry_id is not None and entity.config_entry_id != self.entry_id:
            return False
        return entity.unique_id.startswith(f"{self.entry_id}_{plant_uuid}_")

    async def remove_loaded_entities(self, plant_uuid: str) -> None:
        """Remove attached platform entities and tolerate not-yet-added entities."""
        platform_entities = self.entities.pop(plant_uuid, {})
        for entities in platform_entities.values():
            for entity in tuple(entities):
                if entity.hass is not None:
                    await entity.async_remove()

    async def remove_entity_registry(self, plant_uuid: str) -> None:
        if self.hass is None:
            return
        registry = er.async_get(self.hass)
        for entity in list(registry.entities.values()):
            if self._owns_registry_entity(entity, plant_uuid):
                registry.async_remove(entity.entity_id)

    async def verify_entities_gone(self, plant_uuid: str) -> bool:
        if self.hass is None:
            return True
        registry = er.async_get(self.hass)
        return not any(
            self._owns_registry_entity(entity, plant_uuid)
            for entity in registry.entities.values()
        )

    async def remove_device_registry(self, plant_uuid: str) -> None:
        if self.hass is None:
            return
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, plant_uuid)})
        if device is None:
            return
        entity_registry = er.async_get(self.hass)
        if any(
            entity.device_id == device.id
            for entity in entity_registry.entities.values()
        ):
            # Keep the device while any entity, including a foreign template
            # entity, still references it. Deleting it would leave an invalid
            # device_id in that entity's registry record.
            return
        registry.async_remove_device(device.id)

    async def remove_owned_state(self, plant_uuid: str) -> None:
        self.entities.pop(plant_uuid, None)
        self.temporal_history.pop(plant_uuid, None)
        self.temporal_state.pop(plant_uuid, None)
        self._blocked.discard(plant_uuid)

    def removal_hooks(self) -> RemoveHooks:
        return RemoveHooks(
            self.cancel_tasks,
            self.unsubscribe_listeners,
            self.block_evaluation,
            self.remove_loaded_entities,
            self.remove_entity_registry,
            self.verify_entities_gone,
            self.remove_device_registry,
            self.remove_owned_state,
        )

    async def remove_plant(
        self, plant_uuid: str, expected_revision: int
    ) -> RemoveResult:
        return await async_remove_plant(
            plant_uuid=plant_uuid,
            expected_revision=expected_revision,
            storage=self.require_storage(),
            runtime=self.plants,
            hooks=self.removal_hooks(),
        )

    async def reconcile_pending_removals(self) -> list[RemoveResult]:
        return await async_reconcile_pending_removals(
            storage=self.require_storage(),
            runtime=self.plants,
            hooks_factory=lambda _plant_uuid: self.removal_hooks(),
        )

    async def async_unload(self) -> None:
        """Release subscriptions, debounce tasks, and runtime references."""
        if self.weather_unsub is not None:
            self.weather_unsub()
            self.weather_unsub = None
        if self.temporal_unsub is not None:
            self.temporal_unsub()
            self.temporal_unsub = None
        if self.image_gc_unsub is not None:
            self.image_gc_unsub()
            self.image_gc_unsub = None
        self.image_proxy = None
        self.forecast_collector = None
        self.air_collector = None
        self.weather_client = None
        self.forecast_data = None
        self.air_snapshot = None
        if self.physical_subscriptions is not None:
            self.physical_subscriptions.unload()
        if self.temporal_store is not None:
            await self.temporal_store.async_save(self._temporal_snapshot())
            self.temporal_store = None
        self.platform_callbacks.clear()
        self.entities.clear()
        self.temporal_history.clear()
        self.temporal_state.clear()
        self._blocked.clear()
        self.plants.unload()
        self.physical_subscriptions = None
        self.physical_processor = None
        self.hass = None
        self.entry_id = None
