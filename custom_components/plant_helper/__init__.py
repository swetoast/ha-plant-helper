"""Plant Helper integration setup."""
from __future__ import annotations
import logging
from typing import Any
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from .const import *
from .coordinator import PlantHelperCoordinator
from .enrichment import summarize_enrichment
from .learned_store import LearnedStore
from .learned_store import remove_plant as learned_remove_plant
from .plant_data_api import PlantDataAPI
from .sample_store import SampleStore, clear_key_prefix
from .storage import PlantStorage
_LOGGER = logging.getLogger(__name__)
PLATFORMS = ["sensor", "binary_sensor"]

def _coordinator_plants(user_plants: dict[str, Any], storage: PlantStorage) -> dict[str, dict[str, Any]]:
    plants = {}
    for plant_id, rec in user_plants.items():
        ents = rec.get("entities", {}) or {}
        species = rec.get("species")
        plants[plant_id] = {
            "name": rec.get("custom_name") or plant_id, "species": species,
            "enrichment": summarize_enrichment(storage.get_plant(species) if species else None),
            "placement": ents.get("placement", DEFAULT_PLACEMENT),
            "profile": ents.get("profile", DEFAULT_PROFILE),
            "rain_limit_mm": float(ents.get("rain_limit_mm", DEFAULT_RAIN_LIMIT_MM) or DEFAULT_RAIN_LIMIT_MM),
            "custom_multiplier": ents.get("custom_multiplier"),
            "sensors": {"moisture": ents.get("soil_moisture"), "soil_temp": ents.get("soil_temperature"), "lux": ents.get("lux") or ents.get("room_lux"), "battery": ents.get("battery")},
        }
    return plants

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    storage=PlantStorage(hass); await storage.async_load()
    learned=LearnedStore(hass); await learned.async_load()
    samples=SampleStore(hass); await samples.async_load()
    def _opt(key, default): return entry.options.get(key, entry.data.get(key, default))
    api=PlantDataAPI(async_get_clientsession(hass), perenual_key=_opt(CONF_PERENUAL_API_KEY,"") or None, storage=storage, trefle_key=_opt(CONF_TREFLE_API_KEY,"") or None, enable_trefle_fallback=_opt(CONF_ENABLE_TREFLE_FALLBACK,DEFAULT_ENABLE_TREFLE_FALLBACK), enable_inaturalist_enrichment=_opt(CONF_ENABLE_INATURALIST_ENRICHMENT,DEFAULT_ENABLE_INATURALIST_ENRICHMENT))
    plants=_coordinator_plants(storage.get_all_user_plants(),storage)
    radiation_source = _opt(CONF_RADIATION_SOURCE, DEFAULT_RADIATION_SOURCE)
    update_interval = _opt(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    coordinator=PlantHelperCoordinator(hass, learned=learned, samples=samples, plants=plants, strang_entities=None, forecast_entity=_opt(CONF_FORECAST_ENTITY,None), ozone_entity=_opt(CONF_OZONE_ENTITY,None), api=api, radiation_source=radiation_source, update_interval_seconds=update_interval, latitude=hass.config.latitude, longitude=hass.config.longitude)
    await coordinator.async_config_entry_first_refresh()
    hass.data.setdefault(DOMAIN,{})[entry.entry_id]={"storage":storage,"learned":learned,"samples":samples,"api":api,"coordinator":coordinator,"plants":plants,"ozone_enabled":bool(_opt(CONF_OZONE_ENTITY,None)),"entry_id": entry.entry_id}
    await hass.config_entries.async_forward_entry_setups(entry,PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload_entry)); _register_services(hass,entry)
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
    if not hass.data.get(DOMAIN):
        for service in ("recalibrate", "refresh_species"):
            if hass.services.has_service(DOMAIN, service): hass.services.async_remove(DOMAIN, service)
    return True

def _register_services(hass,entry):
    async def handle_recalibrate(call: ServiceCall):
        plant_id=call.data.get("plant_id"); data=_runtime(hass)
        if not plant_id or not data: return
        learned_remove_plant(data["learned"].data,plant_id); clear_key_prefix(data["samples"].data,f"plant:{plant_id}:")
        data["learned"].schedule_save(); data["samples"].schedule_save(); await data["coordinator"].async_request_refresh()
    if not hass.services.has_service(DOMAIN, "recalibrate"): hass.services.async_register(DOMAIN, "recalibrate", handle_recalibrate)
    async def handle_refresh_species(call: ServiceCall):
        data=_runtime(hass)
        if not data: return
        targets=[call.data.get("plant_id")] if call.data.get("plant_id") else list(data["plants"])
        for pid in targets:
            species=data["plants"].get(pid,{}).get("species")
            if species:
                try: await data["api"].fetch_plant(species,force_fetch=True)
                except Exception: _LOGGER.debug("Species refresh failed",exc_info=True)
        entry_id = data.get("entry_id")
        if entry_id: await hass.config_entries.async_reload(entry_id)
    if not hass.services.has_service(DOMAIN, "refresh_species"): hass.services.async_register(DOMAIN, "refresh_species", handle_refresh_species)

def _runtime(hass):
    for value in hass.data.get(DOMAIN,{}).values():
        if isinstance(value,dict) and "coordinator" in value: return value
    return None
