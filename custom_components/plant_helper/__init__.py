"""Plant Helper — v4 setup.

Wires the tested decision engine into Home Assistant: loads the durable stores
(species/config enrichment, learned constants, runtime samples), builds the
`PlantHelperCoordinator` that runs one `engine.compute` cycle per interval, and
forwards the sensor/binary_sensor platforms that read its results.

The API enrichment layer (Perenual/Trefle/iNaturalist via PlantStorage) is
retained for context — common name, tips, facts, photos — but no longer drives
care decisions; those come from the learned per-plant baselines.
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DEFAULT_ENABLE_INATURALIST_ENRICHMENT,
    DEFAULT_ENABLE_TREFLE_FALLBACK,
    DEFAULT_PLACEMENT,
    DEFAULT_PROFILE,
    DEFAULT_RAIN_LIMIT_MM,
    DOMAIN,
    CONF_ENABLE_INATURALIST_ENRICHMENT,
    CONF_ENABLE_TREFLE_FALLBACK,
    CONF_FORECAST_ENTITY,
    CONF_RADIATION_SOURCE,
    DEFAULT_RADIATION_SOURCE,
    CONF_OZONE_ENTITY,
    CONF_PERENUAL_API_KEY,
    CONF_TREFLE_API_KEY,
    EVENT_DATABASE_RESET,
)
from .coordinator import PlantHelperCoordinator
from .enrichment import summarize_enrichment
from .learned_store import LearnedStore, clear_all_plants
from .learned_store import remove_plant as learned_remove_plant
from .plant_data_api import PlantDataAPI
from .sample_store import SampleStore, clear_key_prefix
from .storage import PlantStorage

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["sensor", "binary_sensor"]


def _coordinator_plants(user_plants: dict[str, Any], storage: PlantStorage) -> dict[str, dict[str, Any]]:
    """Translate stored user plants into the coordinator's plant config.

    Also attaches the cached, normalized species enrichment so entities can
    surface care context (watering, sunlight, toxicity, suggested profile...).
    """
    plants: dict[str, dict[str, Any]] = {}
    for plant_id, rec in user_plants.items():
        ents = rec.get("entities", {}) or {}
        species = rec.get("species")
        cached = storage.get_plant(species) if species else None
        plants[plant_id] = {
            "name": rec.get("custom_name") or plant_id,
            "species": species,
            "enrichment": summarize_enrichment(cached),
            "placement": ents.get("placement", DEFAULT_PLACEMENT),
            "profile": ents.get("profile", DEFAULT_PROFILE),
            "rain_limit_mm": float(ents.get("rain_limit_mm", DEFAULT_RAIN_LIMIT_MM) or DEFAULT_RAIN_LIMIT_MM),
            "custom_multiplier": ents.get("custom_multiplier"),
            "sensors": {
                "moisture": ents.get("soil_moisture"),
                "soil_temp": ents.get("soil_temperature"),
                "lux": ents.get("lux") or ents.get("room_lux"),
                "battery": ents.get("battery"),
            },
        }
    return plants


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Plant Helper from a config entry."""
    storage = PlantStorage(hass)
    await storage.async_load()

    learned = LearnedStore(hass)
    await learned.async_load()

    samples = SampleStore(hass)
    await samples.async_load()

    # Enrichment API (context only: common name, tips, facts, photos). Reached by
    # the config flow when caching/adding species; never drives care decisions.
    def _opt(key: str, default):
        return entry.options.get(key, entry.data.get(key, default))

    api = PlantDataAPI(
        async_get_clientsession(hass),
        perenual_key=_opt(CONF_PERENUAL_API_KEY, "") or None,
        storage=storage,
        trefle_key=_opt(CONF_TREFLE_API_KEY, "") or None,
        enable_trefle_fallback=_opt(CONF_ENABLE_TREFLE_FALLBACK, DEFAULT_ENABLE_TREFLE_FALLBACK),
        enable_inaturalist_enrichment=_opt(
            CONF_ENABLE_INATURALIST_ENRICHMENT, DEFAULT_ENABLE_INATURALIST_ENRICHMENT
        ),
    )

    plants = _coordinator_plants(storage.get_all_user_plants(), storage)
    forecast_entity = entry.options.get(CONF_FORECAST_ENTITY) or entry.data.get(CONF_FORECAST_ENTITY)
    ozone_entity = entry.options.get(CONF_OZONE_ENTITY) or entry.data.get(CONF_OZONE_ENTITY)
    radiation_source = entry.options.get(CONF_RADIATION_SOURCE, DEFAULT_RADIATION_SOURCE)

    coordinator = PlantHelperCoordinator(
        hass,
        learned=learned,
        samples=samples,
        plants=plants,
        strang_entities=None,          # defaults; overridable later
        forecast_entity=forecast_entity,
        ozone_entity=ozone_entity,
        api=api,
        radiation_source=radiation_source,
        latitude=hass.config.latitude,
        longitude=hass.config.longitude,
    )
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "storage": storage,
        "learned": learned,
        "samples": samples,
        "api": api,
        "coordinator": coordinator,
        "plants": plants,
        "ozone_enabled": bool(ozone_entity),
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    _register_services(hass, entry)
    _register_reset_listener(hass, entry, learned, samples)
    return True


def _register_reset_listener(hass, entry, learned, samples) -> None:
    """Clear learned baselines + sample buffers when the DB is reset.

    The config flow's "Reset Plant Database" fires EVENT_DATABASE_RESET; without
    this, a reset would wipe species/config but leave stale learned constants.
    """

    async def _on_reset(event) -> None:
        if not event.data.get("clear_user_plants", True):
            return
        clear_all_plants(learned.data)
        clear_key_prefix(samples.data, "")  # empty prefix clears every series
        learned.schedule_save()
        samples.schedule_save()
        _LOGGER.info("Cleared learned baselines and sample buffers on database reset")

    entry.async_on_unload(hass.bus.async_listen(EVENT_DATABASE_RESET, _on_reset))


async def _async_reload_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload when options (plants, bindings) change."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry and flush the stores."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    data = hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
    if data:
        # NB: do NOT re-save `storage` here. PlantStorage persists immediately on
        # every mutation (add/remove/update), so re-saving it on unload can write
        # a stale in-memory copy over a change made elsewhere (e.g. a plant
        # removed via the options flow) — resurrecting deleted plants. Only the
        # debounced stores (learned/samples) need an unload flush.
        for key in ("learned", "samples"):
            store = data.get(key)
            if store is not None and hasattr(store, "async_save"):
                await store.async_save()
    return True


def _register_services(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Register the recalibrate service (idempotent)."""
    if hass.services.has_service(DOMAIN, "recalibrate"):
        return

    async def handle_recalibrate(call: ServiceCall) -> None:
        """Wipe a plant's learned baseline + samples to restart calibration.

        Use after repotting, changing soil, or moving to a new location.
        """
        plant_id = call.data.get("plant_id")
        if not plant_id:
            return
        data = _runtime(hass)
        if not data:
            return
        learned = data["learned"]
        samples = data["samples"]
        learned_remove_plant(learned.data, plant_id)
        clear_key_prefix(samples.data, f"plant:{plant_id}:")
        learned.schedule_save()
        samples.schedule_save()
        coordinator = data.get("coordinator")
        if coordinator is not None:
            await coordinator.async_request_refresh()
        _LOGGER.info("Recalibration triggered for plant %s", plant_id)

    hass.services.async_register(DOMAIN, "recalibrate", handle_recalibrate)

    if hass.services.has_service(DOMAIN, "refresh_species"):
        return

    async def handle_refresh_species(call: ServiceCall) -> None:
        """Re-fetch species enrichment (Perenual/Trefle/iNaturalist) and reload.

        Meaningful runtime use of the APIs: refreshes care context and updates
        the provider diagnostic sensors. Targets one plant or all.
        """
        data = _runtime(hass)
        if not data:
            return
        storage = data["storage"]
        api = data["api"]
        plants = data["plants"]
        api.storage = storage
        plant_id = call.data.get("plant_id")
        targets = [plant_id] if plant_id else list(plants.keys())
        for pid in targets:
            species = plants.get(pid, {}).get("species")
            if not species:
                continue
            try:
                await api.fetch_plant(species, force_fetch=True)
            except Exception:  # noqa: BLE001 - enrichment is best-effort
                _LOGGER.debug("Species refresh failed for %s", species, exc_info=True)
        await hass.config_entries.async_reload(entry.entry_id)

    hass.services.async_register(DOMAIN, "refresh_species", handle_refresh_species)


def _runtime(hass: HomeAssistant) -> dict[str, Any] | None:
    domain_data = hass.data.get(DOMAIN, {})
    for value in domain_data.values():
        if isinstance(value, dict) and "coordinator" in value:
            return value
    return None
