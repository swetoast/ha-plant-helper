"""Plant Helper integration setup."""
from __future__ import annotations
import logging
import math
from typing import Any
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import (
    CONF_ENABLE_INATURALIST_ENRICHMENT,
    CONF_ENABLE_TREFLE_FALLBACK,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_OZONE_ENTITY,
    CONF_PERENUAL_API_KEY,
    CONF_TREFLE_API_KEY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_ENABLE_INATURALIST_ENRICHMENT,
    DEFAULT_ENABLE_TREFLE_FALLBACK,
    DEFAULT_PLACEMENT,
    DEFAULT_PROFILE,
    DEFAULT_RAIN_LIMIT_MM,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "binary_sensor"]

def _finite_float(value: Any, default: float) -> float:
    """Return a finite float or a safe default."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _coordinator_plants(
    user_plants: dict[str, Any], storage: Any
) -> dict[str, dict[str, Any]]:
    """Build coordinator plant records from persisted user configuration."""
    from .enrichment import summarize_enrichment

    plants: dict[str, dict[str, Any]] = {}
    for plant_id, record in user_plants.items():
        rec = record if isinstance(record, dict) else {}
        raw_entities = rec.get("entities", {})
        entities = raw_entities if isinstance(raw_entities, dict) else {}
        species = rec.get("species")
        if not isinstance(species, str) or not species.strip():
            species = None

        rain_limit = _finite_float(
            entities.get("rain_limit_mm", DEFAULT_RAIN_LIMIT_MM),
            DEFAULT_RAIN_LIMIT_MM,
        )
        if rain_limit < 0:
            rain_limit = DEFAULT_RAIN_LIMIT_MM

        custom_multiplier = entities.get("custom_multiplier")
        if custom_multiplier is not None:
            custom_multiplier = _finite_float(custom_multiplier, 0.0)
            if not 0.0 < custom_multiplier <= 1.0:
                custom_multiplier = None

        plants[plant_id] = {
            "name": rec.get("custom_name") or plant_id,
            "species": species,
            "enrichment": summarize_enrichment(
                storage.get_plant(species) if species else None
            ),
            "placement": entities.get("placement", DEFAULT_PLACEMENT),
            "profile": entities.get("profile", DEFAULT_PROFILE),
            "rain_limit_mm": rain_limit,
            "custom_multiplier": custom_multiplier,
            "sensors": {
                "moisture": entities.get("soil_moisture"),
                "soil_temp": entities.get("soil_temperature"),
                "lux": entities.get("lux") or entities.get("room_lux"),
                "battery": entities.get("battery"),
                "humidity": entities.get("humidity_sensor"),
            },
        }
    return plants



async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up domain services before any config entry is loaded."""
    _register_services(hass)
    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    from .coordinator import PlantHelperCoordinator
    from .learned_store import LearnedStore
    from .plant_data_api import PlantDataAPI
    from .sample_store import SampleStore
    from .storage import PlantStorage
    storage=PlantStorage(hass); await storage.async_load()
    learned=LearnedStore(hass); await learned.async_load()
    samples=SampleStore(hass); await samples.async_load()
    def _opt(key, default):
        value = entry.options.get(key, entry.data.get(key, default))
        return default if value in (None, "") else value
    api=PlantDataAPI(async_get_clientsession(hass), perenual_key=_opt(CONF_PERENUAL_API_KEY,"") or None, storage=storage, trefle_key=_opt(CONF_TREFLE_API_KEY,"") or None, enable_trefle_fallback=_opt(CONF_ENABLE_TREFLE_FALLBACK,DEFAULT_ENABLE_TREFLE_FALLBACK), enable_inaturalist_enrichment=_opt(CONF_ENABLE_INATURALIST_ENRICHMENT,DEFAULT_ENABLE_INATURALIST_ENRICHMENT))
    plants = _coordinator_plants(storage.get_all_user_plants(), storage)

    update_interval = int(
        _finite_float(
            _opt(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
            DEFAULT_UPDATE_INTERVAL,
        )
    )
    update_interval = max(60, min(update_interval, 3600))

    latitude = _finite_float(
        _opt(CONF_LATITUDE, hass.config.latitude), hass.config.latitude
    )
    if not -90.0 <= latitude <= 90.0:
        latitude = hass.config.latitude

    longitude = _finite_float(
        _opt(CONF_LONGITUDE, hass.config.longitude), hass.config.longitude
    )
    if not -180.0 <= longitude <= 180.0:
        longitude = hass.config.longitude

    coordinator = PlantHelperCoordinator(
        hass,
        learned=learned,
        samples=samples,
        plants=plants,
        ozone_entity=_opt(CONF_OZONE_ENTITY, None),
        api=api,
        update_interval_seconds=update_interval,
        latitude=latitude,
        longitude=longitude,
    )
    runtime={"storage":storage,"learned":learned,"samples":samples,"api":api,"coordinator":coordinator,"plants":plants,"ozone_enabled":bool(_opt(CONF_OZONE_ENTITY,None)),"entry_id": entry.entry_id}
    try:
        await coordinator.async_config_entry_first_refresh()
        hass.data.setdefault(DOMAIN,{})[entry.entry_id]=runtime
        await hass.config_entries.async_forward_entry_setups(entry,PLATFORMS)
    except BaseException:
        hass.data.get(DOMAIN, {}).pop(entry.entry_id, None)
        await coordinator.async_shutdown()
        raise
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry))
    return True

async def _async_reload_entry(hass,entry): await hass.config_entries.async_reload(entry.entry_id)
async def async_unload_entry(hass,entry):
    ok=await hass.config_entries.async_unload_platforms(entry,PLATFORMS)
    if not ok: return False
    data=hass.data.get(DOMAIN,{}).pop(entry.entry_id,None)
    if data:
        coordinator=data.get("coordinator")
        if coordinator is not None and hasattr(coordinator,"async_shutdown"): await coordinator.async_shutdown()
        for key in ("learned", "samples"):
            store=data.get(key)
            if store is not None and hasattr(store,"async_save"): await store.async_save()
    return True

def _register_services(hass):
    async def handle_recalibrate(call: ServiceCall):
        from .learned_store import reset_placement as learned_reset_placement
        from .sample_store import clear_key_prefix
        plant_id=call.data.get("plant_id"); data=_runtime(hass)
        if not data:
            raise ServiceValidationError("Plant Helper is not loaded")
        if not plant_id:
            raise ServiceValidationError("plant_id is required")
        plant = data["plants"].get(plant_id)
        if not plant:
            raise ServiceValidationError(f"Unknown Plant Helper plant_id: {plant_id}")
        placement = plant.get("placement", DEFAULT_PLACEMENT)
        learned_reset_placement(data["learned"].data, plant_id, placement)
        clear_key_prefix(data["samples"].data, f"plant:{plant_id}:")
        data["learned"].schedule_save(); data["samples"].schedule_save(); await data["coordinator"].async_request_refresh()
    if not hass.services.has_service(DOMAIN, "recalibrate"): hass.services.async_register(DOMAIN, "recalibrate", handle_recalibrate)
    async def handle_refresh_species(call: ServiceCall):
        data=_runtime(hass)
        if not data:
            raise ServiceValidationError("Plant Helper is not loaded")
        requested = call.data.get("plant_id")
        if requested and requested not in data["plants"]:
            raise ServiceValidationError(f"Unknown Plant Helper plant_id: {requested}")
        targets=[requested] if requested else list(data["plants"])
        refreshed = 0
        for pid in targets:
            species=data["plants"].get(pid,{}).get("species")
            if not species:
                if requested:
                    raise ServiceValidationError(f"Plant has no species configured: {pid}")
                continue
            try:
                await data["api"].fetch_plant(species,force_fetch=True)
                refreshed += 1
            except Exception as err:
                _LOGGER.warning("Species refresh failed for %s: %s", pid, type(err).__name__)
        if requested and refreshed == 0:
            raise ServiceValidationError(f"Species refresh failed for plant_id: {requested}")
        entry_id = data.get("entry_id")
        if entry_id: await hass.config_entries.async_reload(entry_id)
    if not hass.services.has_service(DOMAIN, "refresh_species"): hass.services.async_register(DOMAIN, "refresh_species", handle_refresh_species)

def _runtime(hass):
    for value in hass.data.get(DOMAIN,{}).values():
        if isinstance(value,dict) and "coordinator" in value: return value
    return None
