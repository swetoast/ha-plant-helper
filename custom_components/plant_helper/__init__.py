"""Plant Helper integration for Home Assistant."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_COMMON_NAME,
    ATTR_FACTS,
    ATTR_SPECIES,
    ATTR_THRESHOLDS,
    ATTR_TIPS,
    CONF_ENABLE_INATURALIST_ENRICHMENT,
    CONF_ENABLE_TREFLE_FALLBACK,
    CONF_PERENUAL_API_KEY,
    CONF_TREFLE_API_KEY,
    CONF_UPDATE_INTERVAL,
    DEFAULT_ENABLE_INATURALIST_ENRICHMENT,
    DEFAULT_ENABLE_TREFLE_FALLBACK,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    EVENT_PLANT_ADDED,
    EVENT_PLANT_REMOVED,
    EVENT_PLANT_DATA_FETCHED,
    EVENT_USER_PLANT_ADDED,
    EVENT_USER_PLANT_REMOVED,
    EVENT_PLANT_WATERED,
    EVENT_PLANT_FERTILIZED,
    EVENT_PLANT_INSPECTED,
    EVENT_DATABASE_RESET,
)
from .plant_care_algorithms import PlantCareAlgorithms
from .plant_data_api import PlantDataAPI
from .storage import PlantStorage
from .helpers import (
    extract_common_name as _extract_common_name,
    extract_species_key as _extract_species_key,
)

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR, Platform.BINARY_SENSOR]

SERVICE_ADD_PLANT = "add_plant"
SERVICE_REMOVE_PLANT = "remove_plant"
SERVICE_FETCH_PLANT_DATA = "fetch_plant_data"
SERVICE_ADD_USER_PLANT = "add_user_plant"
SERVICE_REMOVE_USER_PLANT = "remove_user_plant"
SERVICE_MARK_WATERED = "mark_watered"
SERVICE_MARK_FERTILIZED = "mark_fertilized"
SERVICE_MARK_INSPECTED = "mark_inspected"
SERVICE_RESET_DATABASE = "reset_database"

SERVICES = (
    SERVICE_ADD_PLANT,
    SERVICE_REMOVE_PLANT,
    SERVICE_FETCH_PLANT_DATA,
    SERVICE_ADD_USER_PLANT,
    SERVICE_REMOVE_USER_PLANT,
    SERVICE_MARK_WATERED,
    SERVICE_MARK_FERTILIZED,
    SERVICE_MARK_INSPECTED,
    SERVICE_RESET_DATABASE,
)

SCHEMA_ADD_PLANT = vol.Schema(
    {
        vol.Required("species"): cv.string,
        vol.Optional("common_name"): cv.string,
        vol.Optional("thresholds", default={}): dict,
        vol.Optional("tips", default={}): dict,
        vol.Optional("facts", default=[]): list,
    }
)
SCHEMA_REMOVE_PLANT = vol.Schema({vol.Required("species"): cv.string})
SCHEMA_FETCH_PLANT_DATA = vol.Schema(
    {
        vol.Required("species"): cv.string,
        vol.Optional("force_fetch", default=False): cv.boolean,
        vol.Optional("fetch_care_guides", default=True): cv.boolean,
        vol.Optional("fetch_diseases", default=True): cv.boolean,
    }
)
SCHEMA_ADD_USER_PLANT = vol.Schema(
    {
        vol.Required("plant_id"): cv.string,
        vol.Required("species"): cv.string,
        vol.Optional("custom_name"): cv.string,
        # Old-style keys (kept for backward compatibility)
        vol.Optional("humidity_entity"): cv.entity_id,
        vol.Optional("temperature_entity"): cv.entity_id,
        vol.Optional("lux_entity"): cv.entity_id,
        vol.Optional("moisture_entity"): cv.entity_id,
        vol.Optional("air_humidity_entity"): cv.entity_id,
        # New clean keys (used by config_flow and recommended for direct service calls)
        vol.Optional("soil_temperature"): cv.entity_id,
        vol.Optional("soil_moisture"): cv.entity_id,
        vol.Optional("soil_humidity"): cv.entity_id,
        vol.Optional("room_temperature"): cv.entity_id,
        vol.Optional("room_humidity"): cv.entity_id,
        vol.Optional("room_lux"): cv.entity_id,
        # Base keys
        vol.Optional("temperature"): cv.entity_id,
        vol.Optional("moisture"): cv.entity_id,
        vol.Optional("humidity"): cv.entity_id,
        vol.Optional("lux"): cv.entity_id,
        vol.Optional("air_humidity"): cv.entity_id,
    }
)
SCHEMA_PLANT_ID = vol.Schema({vol.Required("plant_id"): cv.string})
SCHEMA_RESET_DATABASE = vol.Schema(
    {vol.Optional("clear_user_plants", default=True): cv.boolean}
)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up Plant Helper."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Plant Helper from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    api_key = _get_entry_value(entry, CONF_PERENUAL_API_KEY, "")
    trefle_key = _get_entry_value(entry, CONF_TREFLE_API_KEY, "")
    update_interval = _get_update_interval(entry)
    enable_trefle = bool(
        _get_entry_value(
            entry,
            CONF_ENABLE_TREFLE_FALLBACK,
            DEFAULT_ENABLE_TREFLE_FALLBACK,
        )
    )
    enable_inat = bool(
        _get_entry_value(
            entry,
            CONF_ENABLE_INATURALIST_ENRICHMENT,
            DEFAULT_ENABLE_INATURALIST_ENRICHMENT,
        )
    )

    storage = PlantStorage(hass)
    await storage.async_load()
    session = async_get_clientsession(hass)
    api = PlantDataAPI(
        session=session,
        perenual_key=api_key,
        storage=storage,
        trefle_key=trefle_key,
        enable_trefle_fallback=enable_trefle,
        enable_inaturalist_enrichment=enable_inat,
    )
    algorithms = PlantCareAlgorithms(hass, storage)

    async def _async_update_data() -> dict[str, Any]:
        return {
            "plants": storage.get_all_plants(),
            "user_plants": storage.get_all_user_plants(),
            "updated_at": dt_util.now().isoformat(),
        }

    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="Plant Helper",
        update_method=_async_update_data,
        update_interval=timedelta(seconds=update_interval),
    )
    await coordinator.async_config_entry_first_refresh()

    runtime_data = {
        "entry": entry,
        "storage": storage,
        "api": api,
        "algorithms": algorithms,
        "coordinator": coordinator,
        "session": session,
        "api_key": api_key,
        "trefle_key": trefle_key,
        "update_interval": update_interval,
    }
    hass.data[DOMAIN][entry.entry_id] = runtime_data
    hass.data[DOMAIN]["storage"] = storage
    hass.data[DOMAIN]["api"] = api
    hass.data[DOMAIN]["algorithms"] = algorithms
    hass.data[DOMAIN]["coordinator"] = coordinator

    if not hass.services.has_service(DOMAIN, SERVICE_ADD_PLANT):
        await async_setup_services(hass)
    else:
        hass.data[DOMAIN]["_services_registered"] = True

    entry.async_on_unload(entry.add_update_listener(async_update_options))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Plant Helper."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    domain_data = hass.data.get(DOMAIN, {})
    runtime_data = domain_data.pop(entry.entry_id, None)
    if runtime_data:
        for key in ("storage", "api", "algorithms", "coordinator"):
            if domain_data.get(key) is runtime_data.get(key):
                domain_data.pop(key, None)

    if not any(
        isinstance(v, dict) and "entry" in v and "storage" in v
        for v in domain_data.values()
    ):
        for service in SERVICES:
            if hass.services.has_service(DOMAIN, service):
                hass.services.async_remove(DOMAIN, service)
        domain_data.pop("_services_registered", None)
        domain_data.pop("algorithms", None)
        domain_data.pop("plant_sensor_entities", None)

    return True


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entry when options are updated."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_setup_services(hass: HomeAssistant) -> None:
    """Register services."""
    domain_data = hass.data.setdefault(DOMAIN, {})
    if domain_data.get("_services_registered") or hass.services.has_service(
        DOMAIN, SERVICE_ADD_PLANT
    ):
        domain_data["_services_registered"] = True
        return

    async def handle_add_plant(call: ServiceCall) -> None:
        runtime = _get_runtime_data(hass)
        storage = runtime.get("storage")
        if storage is None:
            return

        species = call.data["species"].strip()
        common_name = call.data.get("common_name", species).strip()
        plant_data = {
            ATTR_SPECIES: species,
            ATTR_COMMON_NAME: common_name or species,
            ATTR_THRESHOLDS: call.data.get("thresholds", {}),
            ATTR_TIPS: call.data.get("tips", {"direct": [], "seasonal": []}),
            ATTR_FACTS: call.data.get("facts", []),
            "source": "manual",
            "updated_at": dt_util.now().isoformat(),
        }
        await storage.async_add_plant(species, plant_data)
        await _async_refresh_coordinator(runtime)
        hass.bus.async_fire(
            EVENT_PLANT_ADDED,
            {
                "entry_id": runtime["entry"].entry_id,
                "species": species,
                "common_name": common_name or species,
            },
        )

    async def handle_remove_plant(call: ServiceCall) -> None:
        runtime = _get_runtime_data(hass)
        storage = runtime.get("storage")
        if storage is None:
            return

        species = call.data["species"].strip()
        removed = await storage.async_remove_plant(species)
        if removed:
            await _async_refresh_coordinator(runtime)
            hass.bus.async_fire(
                EVENT_PLANT_REMOVED,
                {"entry_id": runtime["entry"].entry_id, "species": species},
            )

    async def handle_fetch_plant_data(call: ServiceCall) -> None:
        runtime = _get_runtime_data(hass)
        storage = runtime.get("storage")
        api = runtime.get("api")
        if storage is None or api is None:
            return

        species = call.data["species"].strip()
        result = await api.fetch_plant(
            species,
            force_fetch=call.data.get("force_fetch", False),
            fetch_care_guides=call.data.get("fetch_care_guides", True),
            fetch_diseases=call.data.get("fetch_diseases", True),
        )
        if result.found and result.data:
            species_key = _extract_species_key(result.data, species)
            result.data.setdefault(ATTR_SPECIES, species_key)
            result.data.setdefault(
                ATTR_COMMON_NAME,
                _extract_common_name(result.data, species),
            )
            result.data["updated_at"] = dt_util.now().isoformat()
            await storage.async_add_plant(species_key, result.data)
            await _async_refresh_coordinator(runtime)
            hass.bus.async_fire(
                EVENT_PLANT_DATA_FETCHED,
                {
                    "entry_id": runtime["entry"].entry_id,
                    "species": species_key,
                    "common_name": result.data.get("common_name"),
                    "provider": result.provider,
                },
            )

    async def handle_add_user_plant(call: ServiceCall) -> None:
        runtime = _get_runtime_data(hass)
        storage = runtime.get("storage")
        if storage is None:
            return

        plant_id = call.data["plant_id"].strip()
        species = call.data["species"].strip()
        custom_name = call.data.get("custom_name")
        entities = {
            key: call.data[key]
            for key in (
                # Support old keys for backward compatibility
                "humidity_entity",
                "temperature_entity",
                "lux_entity",
                "moisture_entity",
                "air_humidity_entity",
                # Support new clean keys
                "soil_temperature",
                "soil_moisture",
                "soil_humidity",
                "room_temperature",
                "room_humidity",
                "room_lux",
                # Support base keys
                "temperature",
                "moisture",
                "humidity",
                "lux",
                "air_humidity",
            )
            if key in call.data and call.data[key]
        }
        if await storage.async_add_user_plant(
            plant_id=plant_id,
            species=species,
            custom_name=custom_name,
            entities=entities,
        ):
            await _async_refresh_coordinator(runtime)
            hass.bus.async_fire(
                EVENT_USER_PLANT_ADDED,
                {
                    "entry_id": runtime["entry"].entry_id,
                    "plant_id": plant_id,
                    "species": species,
                    "custom_name": custom_name or species,
                    "entities": entities,
                },
            )

    async def handle_remove_user_plant(call: ServiceCall) -> None:
        runtime = _get_runtime_data(hass)
        storage = runtime.get("storage")
        if storage is None:
            return

        plant_id = call.data["plant_id"].strip()
        if await storage.async_remove_user_plant(plant_id):
            await _async_refresh_coordinator(runtime)
            hass.bus.async_fire(
                EVENT_USER_PLANT_REMOVED,
                {"entry_id": runtime["entry"].entry_id, "plant_id": plant_id},
            )

    async def handle_mark_watered(call: ServiceCall) -> None:
        runtime = _get_runtime_data(hass)
        storage = runtime.get("storage")
        if storage is None:
            return

        plant_id = call.data["plant_id"].strip()
        ts = dt_util.now().isoformat()
        if await storage.async_update_user_plant(plant_id, {"last_watered": ts}):
            await _async_refresh_coordinator(runtime)
            hass.bus.async_fire(
                EVENT_PLANT_WATERED,
                {
                    "entry_id": runtime["entry"].entry_id,
                    "plant_id": plant_id,
                    "last_watered": ts,
                },
            )

    async def handle_mark_fertilized(call: ServiceCall) -> None:
        runtime = _get_runtime_data(hass)
        storage = runtime.get("storage")
        if storage is None:
            return

        plant_id = call.data["plant_id"].strip()
        ts = dt_util.now().isoformat()
        if await storage.async_update_user_plant(plant_id, {"last_fertilized": ts}):
            await _async_refresh_coordinator(runtime)
            hass.bus.async_fire(
                EVENT_PLANT_FERTILIZED,
                {
                    "entry_id": runtime["entry"].entry_id,
                    "plant_id": plant_id,
                    "last_fertilized": ts,
                },
            )

    async def handle_mark_inspected(call: ServiceCall) -> None:
        runtime = _get_runtime_data(hass)
        storage = runtime.get("storage")
        if storage is None:
            return

        plant_id = call.data["plant_id"].strip()
        ts = dt_util.now().isoformat()
        if await storage.async_update_user_plant(plant_id, {"last_inspected": ts}):
            await _async_refresh_coordinator(runtime)
            hass.bus.async_fire(
                EVENT_PLANT_INSPECTED,
                {
                    "entry_id": runtime["entry"].entry_id,
                    "plant_id": plant_id,
                    "last_inspected": ts,
                },
            )

    async def handle_reset_database(call: ServiceCall) -> None:
        runtime = _get_runtime_data(hass)
        storage = runtime.get("storage")
        if storage is None:
            return

        clear_user_plants = call.data.get("clear_user_plants", True)
        if hasattr(storage, "async_clear_database"):
            result = await storage.async_clear_database(
                clear_user_plants=clear_user_plants
            )
        else:
            result = {
                "removed_cached_species": 0,
                "removed_configured_plants": 0,
            }
            for species in list(storage.get_all_plants().keys()):
                if await storage.async_remove_plant(species):
                    result["removed_cached_species"] += 1
            if clear_user_plants:
                for plant_id in list(storage.get_all_user_plants().keys()):
                    if await storage.async_remove_user_plant(plant_id):
                        result["removed_configured_plants"] += 1

        await _async_refresh_coordinator(runtime)
        hass.bus.async_fire(
            EVENT_DATABASE_RESET,
            {
                "entry_id": runtime["entry"].entry_id,
                **result,
                "clear_user_plants": clear_user_plants,
            },
        )

    hass.services.async_register(
        DOMAIN, SERVICE_ADD_PLANT, handle_add_plant, schema=SCHEMA_ADD_PLANT
    )
    hass.services.async_register(
        DOMAIN, SERVICE_REMOVE_PLANT, handle_remove_plant, schema=SCHEMA_REMOVE_PLANT
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_FETCH_PLANT_DATA,
        handle_fetch_plant_data,
        schema=SCHEMA_FETCH_PLANT_DATA,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_ADD_USER_PLANT,
        handle_add_user_plant,
        schema=SCHEMA_ADD_USER_PLANT,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_REMOVE_USER_PLANT,
        handle_remove_user_plant,
        schema=SCHEMA_PLANT_ID,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_WATERED,
        handle_mark_watered,
        schema=SCHEMA_PLANT_ID,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_FERTILIZED,
        handle_mark_fertilized,
        schema=SCHEMA_PLANT_ID,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_MARK_INSPECTED,
        handle_mark_inspected,
        schema=SCHEMA_PLANT_ID,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_RESET_DATABASE,
        handle_reset_database,
        schema=SCHEMA_RESET_DATABASE,
    )
    domain_data["_services_registered"] = True


def _get_entry_value(entry: ConfigEntry, key: str, default: Any) -> Any:
    value = entry.options.get(key, None)
    if value is None:
        value = entry.data.get(key, None)
    return default if value is None else value


def _get_update_interval(entry: ConfigEntry) -> int:
    try:
        value = int(
            _get_entry_value(
                entry,
                CONF_UPDATE_INTERVAL,
                DEFAULT_UPDATE_INTERVAL,
            )
        )
    except (TypeError, ValueError):
        value = DEFAULT_UPDATE_INTERVAL
    return value if value > 0 else DEFAULT_UPDATE_INTERVAL


def _get_runtime_data(hass: HomeAssistant) -> dict[str, Any]:
    for value in hass.data.get(DOMAIN, {}).values():
        if (
            isinstance(value, dict)
            and "entry" in value
            and "storage" in value
            and "api" in value
        ):
            return value
    return hass.data.get(DOMAIN, {}) if "storage" in hass.data.get(DOMAIN, {}) else {}


async def _async_refresh_coordinator(runtime_data: dict[str, Any]) -> None:
    coordinator = runtime_data.get("coordinator")
    if coordinator is not None:
        try:
            await coordinator.async_request_refresh()
        except Exception:
            _LOGGER.exception("Failed to refresh Plant Helper coordinator")
