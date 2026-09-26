from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone, tzinfo
import logging
import time
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

from homeassistant.const import EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import CoreState, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr, entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store

from .const import DOMAIN
from .domain.runtime import RuntimeCollection
from .domain.rate_limit import RateLimitGate
from .domain.entity_contract import is_retired_unique_id
from .domain.interpretation import interpret_indoor, interpret_outdoor
from .domain.temporal.baseline import (
    BaselineSamples,
    CalibrationProgress,
    calibration_progress,
    cycle_baseline,
    daily_baseline,
    days_since_relearn,
    derive_band,
    describe_calibration,
    monthly_baseline,
    relearn_baseline,
    update_samples,
)
from .domain.temporal.daily import DailySummary, completed_days, light_report, update_ledger
from .domain.temporal.daylight import (
    DaylightState,
    DaylightWindow,
    parse_daily_windows,
    resolve_daylight,
)
from .domain.temporal.engine import EngineInputs, evaluate_plant
from .domain.temporal.history import ObservationHistory
from .domain.temporal.light import day_bounds, mean_daytime_radiation
from .domain.learning import LearningRuntime
from .domain.temporal.moisture import (
    PROFILE_BANDS,
    TemporalMoistureState,
    watering_rise_threshold,
)
from .domain.temporal.observation import PlantObservation
from .domain.temporal.store import (
    STORE_VERSION,
    restore_daily,
    restore_ephemeris,
    restore_store,
    serialize_store,
)
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
    SourceEnrichment,
    TrefleAdapter,
    select_exact_common_name_candidate,
)
from .domain.edit_plant import EditPlantError, async_edit_runtime_plant, setting_change
from .domain.issues import desired_issues
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

def _durable(state: TemporalMoistureState | None) -> tuple | None:
    """The parts of the moisture state a restart must not lose.

    Slope and the wet limit are recomputed on every evaluation, so they are
    deliberately excluded; comparing them would force a write on every tick.
    """
    if state is None:
        return None
    return (
        state.status,
        state.state_since,
        state.last_watering_event,
        state.elevated_since,
    )


# Edit errors from the care profile select and rain limit number, mapped to the
# exception messages in the translations.
_SETTING_ERRORS = {
    "plant_changed": "plant_changed",
    "custom_multiplier_range": "custom_needs_multiplier",
    "moisture_not_numeric": "moisture_not_ready",
    "moisture_out_of_range": "moisture_not_ready",
    "rain_limit_mm": "rain_limit_range",
}

# Statuses whose readings must not teach the learned baseline (roadmap Phase 6).
_UNLEARNABLE = frozenset({"too_wet", "too_dry", "sensor_problem", "waiting_for_data"})

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
    # Per-provider matching: adapters the flow searches (only configured
    # providers), the by-ID enrichment, and whether Perenual is on the free plan.
    provider_adapters: dict[str, Any] = field(default_factory=dict)
    source_enrichment: SourceEnrichment | None = None
    perenual_free: bool = True
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
    temporal_daily: dict[str, dict[str, DailySummary]] = field(default_factory=dict)
    ephemeris_windows: tuple[DaylightWindow, ...] = ()
    ephemeris_fetched_at: datetime | None = None
    ephemeris_stale: bool = False
    _astral_cache: tuple[date | None, tuple[DaylightWindow, ...]] = (None, ())
    temporal_store: Any = None
    temporal_unsub: Any = None
    image_proxy: Any = None
    image_gc_unsub: Any = None
    species_images: dict[str, Any] = field(default_factory=dict)
    learning: Any = None
    version: str | None = None
    _blocked: set[str] = field(default_factory=set)
    _trefle_gate: RateLimitGate = field(default_factory=RateLimitGate)

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
        self.plants.subscribe(self._plant_set_changed)
        if hass.state is CoreState.running:
            self.sync_issues()
        else:
            # Other integrations' sensors may still be loading until then.
            hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, self._on_started)

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
        self.temporal_daily = {
            uuid: ledger for uuid, ledger in restore_daily(data).items() if uuid in known
        }
        self.ephemeris_windows, self.ephemeris_fetched_at = restore_ephemeris(data, now)
        self.ephemeris_stale = True  # restored, not yet confirmed by a fresh fetch

    def _temporal_snapshot(self) -> dict[str, Any]:
        return serialize_store(
            self.temporal_history,
            self.temporal_state,
            self.temporal_daily,
            (self.ephemeris_windows, self.ephemeris_fetched_at),
        )

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
        from .image_proxy import async_set_image_proxy
        from .domain.image_proxy import system_resolve
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        session = async_get_clientsession(hass)
        cache_dir = Path(hass.config.path("plant_helper", "images"))
        downloader = ImageDownloader(session)
        self.image_proxy = await hass.async_add_executor_job(
            SpeciesImageProxy,
            cache_dir,
            downloader.fetch,
            system_resolve,
            hass.async_add_executor_job,
        )
        async_set_image_proxy(hass, self.image_proxy)
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

    def _learned_baseline(self, plant_uuid: str) -> dict[str, Any]:
        """The stored baseline for the plant's placement, without side effects."""
        learning = self.learning
        if learning is None or plant_uuid not in learning.placement:
            return {}
        try:
            return dict(learning.state(plant_uuid).baseline)
        except Exception:
            return {}

    async def _learning_step(
        self,
        plant_uuid: str,
        placement: str,
        profile: str,
        history: ObservationHistory,
        ledger: Mapping[str, DailySummary],
        now: datetime,
        record: bool,
    ) -> tuple[dict[str, Any], CalibrationProgress | None]:
        """Return (learned baseline, calibration progress), fully defensively.

        Learning continues after calibration (roadmap Phase 6): each watering
        cycle refines the typical rise, peak, drying slope and recovery time, and
        each new day refreshes the light, temperature and humidity norms and the
        monthly seasonal record. Readings taken in an abnormal state are not
        learned, and after a relearn only days from the relearn on count. Any
        failure returns ({}, None) so the engine falls back to the profile band
        and evaluation never breaks.
        """
        learning = self.learning
        if learning is None:
            return {}, None
        try:
            if plant_uuid not in learning.placement:
                learning.placement[plant_uuid] = placement
                learning.calibrating.add(plant_uuid)
            state = learning.state(plant_uuid)
            baseline = dict(state.baseline)
            profile_band = PROFILE_BANDS.get(profile, PROFILE_BANDS["balanced"])
            samples = BaselineSamples.from_dict(state.active_samples)
            tz = self._timezone()
            days = days_since_relearn(completed_days(ledger, now, tz), baseline)
            if record:
                prior = self.temporal_state.get(plant_uuid)
                learnable = prior is None or prior.status not in _UNLEARNABLE
                band_high = (
                    float(baseline["high"]) if baseline.get("complete") else profile_band[1]
                )
                updated = update_samples(
                    samples,
                    history,
                    now,
                    band_high=band_high,
                    learnable=learnable,
                    watering_rise=watering_rise_threshold(days),
                )
                learning.active_samples[plant_uuid] = updated.to_dict()
                cycle_closed = updated.last_watering != samples.last_watering
                day_key = now.astimezone(tz).date().isoformat()
                if cycle_closed:
                    await learning.set_active_samples(plant_uuid, updated.to_dict())
                if cycle_closed or baseline.get("updated") != day_key:
                    refreshed = dict(baseline)
                    refreshed.update(cycle_baseline(updated))
                    refreshed.update(daily_baseline(days))
                    refreshed["monthly"] = monthly_baseline(baseline.get("monthly"), days)
                    derived = derive_band(
                        updated, history.confidence(now), now, profile_band
                    )
                    if derived is not None:
                        refreshed.update(
                            {"complete": True, "low": derived[0], "high": derived[1]}
                        )
                    refreshed["updated"] = day_key
                    await learning.set_baseline(plant_uuid, state.placement, refreshed)
                    baseline = refreshed
                samples = updated
            progress = calibration_progress(
                samples,
                history.confidence(now),
                now,
                complete=bool(baseline.get("complete")),
                profile_band=profile_band,
            )
            return baseline, progress
        except Exception:
            _LOGGER.debug("Learning step failed for %s", plant_uuid, exc_info=True)
            return {}, None

    async def async_relearn(self, plant_uuid: str) -> None:
        """Forget what a plant learned for its current placement and start over.

        Clears the learned band, per-cycle values, and light, temperature and
        humidity norms for the current placement only; the other placement's
        baseline is kept. Recent readings and daily summaries stay, because the
        statuses need them, but learning only counts days from today on.
        """
        plant = self.plants.plants.get(plant_uuid)
        if plant is None:
            raise KeyError(plant_uuid)
        learning = self.learning
        if learning is None:
            raise RuntimeError("learning_unavailable")
        placement = str(plant.config.get("placement", "indoor"))
        learning.placement[plant_uuid] = placement
        today = datetime.now(timezone.utc).astimezone(self._timezone()).date()
        await learning.set_baseline(plant_uuid, placement, relearn_baseline(today))
        await learning.set_active_samples(plant_uuid, {})
        learning.calibrating.add(plant_uuid)
        await self.evaluate(plant_uuid)

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
        self.species_images[plant_uuid] = cached

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
            windows = parse_daily_windows(snapshot.data.get("daily"))
            if windows:
                self.ephemeris_windows = windows
                self.ephemeris_fetched_at = snapshot.fetched_at
                self.ephemeris_stale = snapshot.stale
        except Exception:
            self.ephemeris_stale = True
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
        self.sync_issues()

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
                self.evaluate(plant_uuid, tick=True),
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
        self,
        plant_uuid: str,
        environment: Any = None,
        *,
        record: bool = True,
        tick: bool = False,
    ) -> None:
        """Produce stable user-facing states from physical and weather context.

        Every call records an observation (history deduplication decides what is
        kept), so the background tick is a collection trigger as the roadmap
        requires: steady plants keep coverage, and sunrise and sunset are
        captured within a tick. A tick only notifies listeners when a published
        output actually changed; sensor events and CRUD always notify.
        """
        plant = self.plants.plants.get(plant_uuid)
        if plant is None or plant.removing or plant_uuid in self._blocked:
            return

        state = plant.state
        moisture = state.get("moisture")
        profile = str(plant.config.get("profile", "balanced"))
        placement = str(plant.config.get("placement", "indoor"))
        previous = self._published(state)

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
        tz = self._timezone()
        history = self.temporal_history.get(plant_uuid)
        if history is None:
            history = ObservationHistory()
            self.temporal_history[plant_uuid] = history
        daylight = self._daylight(now)
        soil_temperature = state.get("temperature")
        light = state.get("light")
        humidity = state.get("humidity")
        stored = False
        if record:
            stored = history.append(
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
                    is_daylight=daylight.is_daylight,
                    daylight_source=daylight.source,
                )
            )
        ledger = update_ledger(
            self.temporal_daily.get(plant_uuid, {}),
            history,
            now,
            tz,
            placement=placement,
            radiation_for_day=lambda day: self._radiation_for_day(day, tz),
            learned=self._learned_baseline(plant_uuid),
        )
        self.temporal_daily[plant_uuid] = ledger
        learned, calibration = await self._learning_step(
            plant_uuid, placement, profile, history, ledger, now, record
        )
        result = evaluate_plant(
            EngineInputs(
                history=history,
                prior=self.temporal_state.get(plant_uuid),
                ledger=ledger,
                now=now,
                tz=tz,
                profile=profile,
                placement=placement,
                learned=learned,
                rain_suppression=rain_suppression,
                growth_season=conditions.get("growth_season"),
                radiation_24h=self._forecast_derived("radiation_24h"),
            )
        )
        previous_state = self.temporal_state.get(plant_uuid)
        self.temporal_state[plant_uuid] = result.moisture_state
        watered = result.moisture_state.last_watering_event
        if (
            previous_state is not None
            and watered is not None
            and watered != previous_state.last_watering_event
        ):
            # A new watering, not the stored one restored after a restart.
            for entity in self.entities.get(plant_uuid, {}).get("event", []):
                if entity.hass is not None:
                    entity.watered(watered)
        # Persist only when something durable changed. Deduplication keeps at
        # most one observation per few minutes, and today's and yesterday's
        # summaries are rebuilt from history on load, so a steady plant writes
        # rarely instead of on every tick.
        if stored or _durable(previous_state) != _durable(result.moisture_state):
            self._schedule_temporal_save()

        care_attributes: dict[str, Any] = {
            "summary": result.summary,
            "reason": result.reason,
            "since": result.since.isoformat() if result.since else None,
            "confidence": result.confidence,
            "drying_context": result.drying_context,
            "light_context": result.light_context,
            "humidity_context": result.humidity_context,
            "temperature_context": result.temperature_context,
            "dormant": result.dormant,
            "placement": placement,
        }
        if placement == "outdoor":
            care_attributes["rain_suppression"] = rain_suppression
            care_attributes["frost_hours"] = conditions.get("frost")
            care_attributes["exposure"] = list(conditions.get("exposure", ())) or None
        else:
            care_attributes["external_daylight"] = conditions.get("external_daylight")

        state["care_status"] = result.status
        state["care_status_attributes"] = care_attributes
        state["health"] = result.health
        state["health_attributes"] = {"summary": result.health_summary}
        state["needs_attention"] = result.needs_attention
        state["needs_attention_attributes"] = {"reason": result.attention_reason}
        state["last_watered"] = watered
        state["daily_light"], state["daily_light_attributes"] = light_report(ledger, now, tz)
        if calibration is None:
            state["calibration"] = None
            state["calibration_attributes"] = {}
        else:
            state["calibration"], state["calibration_attributes"] = describe_calibration(
                calibration, learned, tz
            )

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

        if not tick:
            self._update_device(plant_uuid)
        if not tick or self._published(state) != previous:
            self.plants.notify_updated(plant_uuid)

    @staticmethod
    def _published(state: Mapping[str, Any]) -> tuple:
        """Everything the entities publish that the tick can change."""
        return (
            state.get("care_status"),
            repr(state.get("care_status_attributes")),
            state.get("health"),
            repr(state.get("health_attributes")),
            state.get("needs_attention"),
            repr(state.get("needs_attention_attributes")),
            state.get("calibration"),
            repr(state.get("calibration_attributes")),
            state.get("last_watered"),
            state.get("daily_light"),
            repr(state.get("daily_light_attributes")),
        )

    def _timezone(self) -> tzinfo:
        name = getattr(getattr(self.hass, "config", None), "time_zone", None)
        try:
            return ZoneInfo(name) if name else timezone.utc
        except Exception:
            return timezone.utc

    def _daylight(self, now: datetime) -> DaylightState:
        return resolve_daylight(
            now,
            forecast_windows=self.ephemeris_windows,
            forecast_fetched_at=self.ephemeris_fetched_at,
            forecast_stale=self.ephemeris_stale,
            astral=self._astral_windows,
        )

    def _astral_windows(self, now: datetime) -> tuple[DaylightWindow, ...]:
        """Home Assistant location plus Astral: yesterday, today and tomorrow."""
        if self.hass is None:
            return ()
        today = now.astimezone(self._timezone()).date()
        cached_day, cached = self._astral_cache
        if cached_day == today:
            return cached
        from homeassistant.const import SUN_EVENT_SUNRISE, SUN_EVENT_SUNSET
        from homeassistant.helpers.sun import get_astral_event_date

        windows = []
        for offset in (-1, 0, 1):
            day = today + timedelta(days=offset)
            sunrise = get_astral_event_date(self.hass, SUN_EVENT_SUNRISE, day)
            sunset = get_astral_event_date(self.hass, SUN_EVENT_SUNSET, day)
            if sunrise is not None and sunset is not None and sunset > sunrise:
                windows.append(DaylightWindow(sunrise, sunset))
        self._astral_cache = (today, tuple(windows))
        return self._astral_cache[1]

    def _forecast_derived(self, key: str) -> float | None:
        data = self.forecast_data if isinstance(self.forecast_data, dict) else {}
        derived = data.get("derived")
        value = derived.get(key) if isinstance(derived, Mapping) else None
        try:
            return float(value) if value is not None else None
        except (TypeError, ValueError):
            return None

    def _radiation_for_day(self, day: date, tz: tzinfo) -> float | None:
        data = self.forecast_data if isinstance(self.forecast_data, dict) else {}
        hourly = data.get("hourly")
        times = getattr(hourly, "times", None)
        values = getattr(hourly, "values", {}).get("radiation") if hourly is not None else None
        if not times or not values:
            return None
        start, end = day_bounds(day, tz)
        return mean_daytime_radiation(zip(times, values), start, end)

    async def async_configure_enrichment(
        self, hass: HomeAssistant, options: Mapping[str, Any]
    ) -> None:
        """Configure the chained iNaturalist, Trefle, and Perenual providers."""
        from homeassistant.helpers.aiohttp_client import async_get_clientsession

        session = async_get_clientsession(hass)
        perenual_key = str(options.get("perenual_api_key", "")).strip()
        trefle_key = str(options.get("trefle_api_key", "")).strip()
        gate = self._trefle_gate

        async def request_json(url: str, params: Mapping[str, Any]) -> Mapping[str, Any]:
            try:
                async with session.get(url, params=params, timeout=30) as response:
                    try:
                        body: Any = await response.json(content_type=None)
                    except Exception as err:
                        raise ProviderError("provider", response.status, "non-json response") from err
                    return {"http_status": response.status, "body": body, "headers": {str(key).lower(): value for key, value in response.headers.items()}}
            except ProviderError:
                raise
            except Exception as err:
                raise ProviderError("network", message=str(err)) from err

        def observe_trefle(raw: Mapping[str, Any]) -> Mapping[str, Any]:
            # Header names are normalized to lowercase in request_json because HTTP/2
            # (which Trefle serves) lowercases them; a cased lookup would never match.
            headers = raw.get("headers", {})
            gate.observe(
                int(raw.get("http_status", 200)),
                headers.get("ratelimit-remaining"),
                headers.get("ratelimit-reset"),
                time.time(),
            )
            return raw

        async def inaturalist_request(query: str) -> Mapping[str, Any]:
            return await request_json(
                "https://api.inaturalist.org/v1/taxa/autocomplete",
                {"q": query, "rank": "species", "per_page": 10},
            )

        async def trefle_request(query: str) -> Mapping[str, Any]:
            if not trefle_key or not gate.allow(time.time()):
                return {"data": []}
            return observe_trefle(
                await request_json(
                    "https://trefle.io/api/v1/species/search",
                    {"q": query, "limit": 10, "token": trefle_key},
                )
            )

        async def trefle_details(species_id: Any) -> Mapping[str, Any]:
            if not trefle_key or not gate.allow(time.time()):
                return {"data": None}
            return observe_trefle(
                await request_json(
                    f"https://trefle.io/api/v1/species/{species_id}",
                    {"token": trefle_key},
                )
            )

        async def perenual_request(query: str) -> Mapping[str, Any]:
            if not perenual_key:
                return {"data": []}
            return await request_json(
                "https://perenual.com/api/v2/species-list",
                {"q": query, "key": perenual_key},
            )

        async def perenual_details(species_id: Any) -> Mapping[str, Any]:
            return await request_json(
                f"https://perenual.com/api/v2/species/details/{species_id}",
                {"key": perenual_key},
            )

        inaturalist = INaturalistAdapter(inaturalist_request)
        trefle = TrefleAdapter(trefle_request, trefle_details, credential=trefle_key)
        perenual = PerenualAdapter(
            perenual_request, perenual_key, detail_request=perenual_details
        )
        self.species_enrichment = ChainedSpeciesEnrichment(inaturalist, trefle, perenual)
        self.provider_adapters = {"inaturalist": inaturalist}
        if trefle_key:
            self.provider_adapters["trefle"] = trefle
        if perenual_key:
            self.provider_adapters["perenual"] = perenual
        self.perenual_free = str(options.get("perenual_access_level", "free")) != "paid"
        self.source_enrichment = SourceEnrichment(
            trefle=trefle if trefle_key else None,
            perenual=perenual if perenual_key else None,
            storage=self.storage,
        )
        try:
            await self.source_enrichment.load()
        except Exception:
            _LOGGER.debug("Species record cache could not be loaded", exc_info=True)

    async def schedule_enrichment(self, plant_uuid: str, species: str) -> None:
        """Enrich a plant from its chosen provider records, or the legacy chain.

        A plant added or re-matched with per-provider matching carries
        ``species_sources``: each provider's chosen record is fetched by ID and
        nothing is re-matched. Plants from before that keep the name-matching
        chain until they are re-matched.
        """
        plant = self.plants.plants.get(plant_uuid)
        if plant is None or not species.strip():
            return
        sources = plant.config.get("species_sources")
        if sources and self.source_enrichment is not None:
            try:
                result = await self.source_enrichment.enrich(sources)
            except Exception:
                _LOGGER.exception("Species enrichment failed for %s", plant_uuid)
                return
            await self._publish_species(plant_uuid, species, result)
            return
        chain = self.species_enrichment
        if chain is None:
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
        await self._publish_species(plant_uuid, species, result)

    async def _publish_species(self, plant_uuid: str, species: str, result: Any) -> None:
        plant = self.plants.plants.get(plant_uuid)
        if plant is None:
            return
        attributes = {
            key: result.data[key]
            for key in (
                "common_name",
                "scientific_name",
                "family",
                "genus",
                "watering_category",
                "sunlight_requirements",
                "light_requirement",
                "humidity_requirement",
                "soil_moisture_requirement",
                "ph_minimum",
                "ph_maximum",
                "minimum_temperature_c",
                "maximum_temperature_c",
                "growth_habit",
                "growth_rate",
                "toxicity",
                "average_height_cm",
                "duration",
                "edible",
                "watering_interval",
                "care_level",
                "indoor",
                "drought_tolerant",
                "poisonous_to_pets",
                "poisonous_to_humans",
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
        self._update_device(plant_uuid)
        self.plants.notify_updated(plant_uuid)
        self.sync_issues()

    async def schedule_reconciliation(self, plant_uuid: str) -> None:
        plant = self.plants.plants.get(plant_uuid)
        if plant is not None:
            await self.register_listeners(plant_uuid, plant.config)
            await self.evaluate(plant_uuid)

    async def handle_placement_change(self, plant_uuid: str, *_args: Any) -> None:
        """Switch learning to the new placement, preserving the old baseline.

        Indoor and outdoor baselines are kept separately (roadmap Phase 6): the
        inactive placement's baseline stays stored and resumes if the plant moves
        back. The daily ledger restarts because its bands are placement-relative.
        """
        self.temporal_daily.pop(plant_uuid, None)
        plant = self.plants.plants.get(plant_uuid)
        learning = self.learning
        if plant is None or learning is None:
            return
        destination = str(plant.config.get("placement", "indoor"))
        try:
            if plant_uuid in learning.placement:
                await learning.transition(plant_uuid, destination)
            else:
                learning.placement[plant_uuid] = destination
        except Exception:
            _LOGGER.debug("Placement learning switch failed for %s", plant_uuid, exc_info=True)

    async def handle_species_change(
        self, plant_uuid: str, species_change: Any = None, *_args: Any
    ) -> None:
        self.species_context.pop(plant_uuid, None)
        if getattr(species_change, "kind", "different_taxon") != "alias":
            await self._reset_learning(plant_uuid)
        await self.evaluate(plant_uuid)

    async def async_edit(
        self, plant_uuid: str, expected_revision: int, raw: dict[str, Any], placement: str
    ) -> None:
        """Save an edited plant; raises EditPlantError with a translation key."""
        await async_edit_runtime_plant(
            self, plant_uuid, expected_revision, raw, placement, self._read_source
        )
        self.sync_issues()

    async def async_change_setting(self, plant_uuid: str, key: str, value: Any) -> None:
        """Change one plant setting from its select or number entity."""
        plant = self.plants.plants.get(plant_uuid)
        if plant is None:
            raise HomeAssistantError(translation_domain=DOMAIN, translation_key="not_a_plant")
        revision, raw, placement = setting_change(plant.config, key, value)
        try:
            await self.async_edit(plant_uuid, revision, raw, placement)
        except EditPlantError as err:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key=_SETTING_ERRORS.get(err.key, "cannot_save_plant"),
            ) from None
        except Exception as err:
            _LOGGER.exception("Failed to save plant %s", plant_uuid)
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="cannot_save_plant"
            ) from err

    def device_model(self, plant_uuid: str) -> str:
        """The plant device's model: its species, or "Plant" without one."""
        context = self.species_context.get(plant_uuid)
        if context is not None and context[0] not in {"ambiguous", "not_found"}:
            return context[0]
        plant = self.plants.plants.get(plant_uuid)
        species = plant.config.get("species") if plant is not None else None
        return str(species) if species else "Plant"

    def _update_device(self, plant_uuid: str) -> None:
        """Keep the device's name, model and version in step with the plant."""
        plant = self.plants.plants.get(plant_uuid)
        if self.hass is None or plant is None:
            return
        registry = dr.async_get(self.hass)
        device = registry.async_get_device(identifiers={(DOMAIN, plant_uuid)})
        if device is None:
            return
        name = str(plant.config.get("display_name", plant_uuid))
        model = self.device_model(plant_uuid)
        if (device.name, device.model, device.sw_version) != (name, model, self.version):
            registry.async_update_device(
                device.id, name=name, model=model, sw_version=self.version
            )

    @callback
    def _on_started(self, _event: Any) -> None:
        self.sync_issues()

    @callback
    def _plant_set_changed(self, change: Any) -> None:
        if change.added or change.removed:
            self.sync_issues()

    @callback
    def sync_issues(self) -> None:
        """Show the repair issues that apply now and clear the rest."""
        hass = self.hass
        if hass is None:
            return
        running = hass.state is CoreState.running
        wanted = desired_issues(
            {uuid: plant.config for uuid, plant in self.plants.plants.items()},
            sensor_exists=(
                (lambda entity_id: hass.states.get(entity_id) is not None)
                if running
                else None
            ),
            provider_problems=(
                self.source_enrichment.problems if self.source_enrichment else {}
            ),
            perenual_free=self.perenual_free,
        )
        registry = ir.async_get(hass)
        for domain, issue_id in list(registry.issues):
            # Before startup finishes sensors cannot be judged; keep those issues.
            judged = running or not issue_id.startswith("missing_moisture_sensor_")
            if domain == DOMAIN and issue_id not in wanted and judged:
                ir.async_delete_issue(hass, DOMAIN, issue_id)
        for issue_id, (key, placeholders) in wanted.items():
            ir.async_create_issue(
                hass,
                DOMAIN,
                issue_id,
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=key,
                translation_placeholders=placeholders,
            )

    def destination_baseline_complete(self, plant_uuid: str, destination: str) -> bool:
        learning = self.learning
        if learning is None:
            return False
        stored = learning.baselines.get(plant_uuid, {}).get(destination, {})
        return bool(stored.get("complete"))

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

    def prune_retired_entities(self) -> None:
        """Drop registry entries for entity keys this version no longer creates.

        Keys retired by earlier releases otherwise linger as restored
        "unavailable" entities, because no platform ever recreates them.
        """
        if self.hass is None or self.entry_id is None:
            return
        registry = er.async_get(self.hass)
        for entity in list(registry.entities.values()):
            if (
                entity.platform == DOMAIN
                and entity.config_entry_id == self.entry_id
                and is_retired_unique_id(self.entry_id, entity.unique_id)
            ):
                registry.async_remove(entity.entity_id)

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
        self.temporal_daily.pop(plant_uuid, None)
        self.species_images.pop(plant_uuid, None)
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
        if self.hass is not None and self.image_proxy is not None:
            from .image_proxy import async_set_image_proxy

            async_set_image_proxy(self.hass, None)
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
        self.temporal_daily.clear()
        self._blocked.clear()
        self.plants.unload()
        self.physical_subscriptions = None
        self.physical_processor = None
        self.hass = None
        self.entry_id = None
