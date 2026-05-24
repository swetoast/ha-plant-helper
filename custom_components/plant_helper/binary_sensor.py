"""Binary sensor platform for Plant Helper integration.

Monitors:
- Plant Helper API connectivity and provider status
- Plant water/light/temperature issues
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import DOMAIN, PERENUAL_DAILY_LIMIT

_LOGGER = logging.getLogger(__name__)


ENTITY_KEY_ALIASES = {
    "humidity": ("humidity", "humidity_entity", "moisture", "moisture_entity"),
    "moisture": ("moisture", "moisture_entity", "humidity", "humidity_entity"),
    "temperature": ("temperature", "temperature_entity", "temp", "temp_entity"),
    "temp": ("temp", "temp_entity", "temperature", "temperature_entity"),
    "lux": ("lux", "lux_entity", "light", "light_entity"),
    "air_humidity": ("air_humidity", "air_humidity_entity"),
}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Plant Helper binary sensors from config entry."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    storage = runtime_data["storage"]
    api = runtime_data.get("api")
    coordinator = runtime_data.get("coordinator")

    entities: list[BinarySensorEntity] = [
        PlantHelperAPIConnectivityBinarySensor(
            hass=hass,
            entry=entry,
            api=api,
            coordinator=coordinator,
        )
    ]

    user_plants = storage.get_all_user_plants()

    for plant_id, plant_data in user_plants.items():
        species = plant_data.get("species")
        plant_info = storage.get_plant(species)

        if not plant_info:
            _LOGGER.warning(
                "Species '%s' not found for configured plant '%s'",
                species,
                plant_id,
            )
            continue

        entities.extend(
            [
                PlantNeedsWaterSensor(
                    hass=hass,
                    entry=entry,
                    plant_id=plant_id,
                    plant_data=plant_data,
                    plant_info=plant_info,
                ),
                PlantLowLightSensor(
                    hass=hass,
                    entry=entry,
                    plant_id=plant_id,
                    plant_data=plant_data,
                    plant_info=plant_info,
                ),
                PlantTemperatureIssueSensor(
                    hass=hass,
                    entry=entry,
                    plant_id=plant_id,
                    plant_data=plant_data,
                    plant_info=plant_info,
                ),
            ]
        )

    async_add_entities(entities, True)
    _LOGGER.info("Created %d Plant Helper binary sensors", len(entities))


def _get_linked_entity(plant_data: dict[str, Any], key: str) -> str | None:
    """Get linked entity from configured plant data."""
    entities = plant_data.get("entities", {})

    for alias in ENTITY_KEY_ALIASES.get(key, (key,)):
        entity_id = entities.get(alias)
        if entity_id:
            return entity_id

    return None


def _safe_float(value: Any) -> float | None:
    """Convert value to float safely."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class PlantHelperBinaryBase(BinarySensorEntity):
    """Base binary sensor for Plant Helper."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
    ) -> None:
        """Initialize base binary sensor."""
        self.hass = hass
        self._entry = entry

    @property
    def device_info(self) -> DeviceInfo:
        """Return integration device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Plant Helper",
            manufacturer="Plant Helper",
            model="Plant Helper",
        )


class PlantHelperAPIConnectivityBinarySensor(PlantHelperBinaryBase):
    """Monitor Plant Helper API connectivity.

    Binary sensor is ON when the API layer is usable:
    - API orchestrator exists
    - Perenual provider has a key
    - Perenual daily limit is not reached
    - no current fatal provider error is recorded

    Binary sensor is OFF when there is an API problem.
    """

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        api: Any | None,
        coordinator: Any | None,
    ) -> None:
        """Initialize API connectivity sensor."""
        super().__init__(hass, entry)
        self._api = api
        self._coordinator = coordinator
        self._attr_name = "Plant Helper API Connectivity"
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_api_connectivity"
        self._attr_icon = "mdi:api"

    async def async_added_to_hass(self) -> None:
        """Start periodic update tracking."""
        await super().async_added_to_hass()

        self.async_on_remove(
            async_track_time_interval(
                self.hass,
                self._handle_time_update,
                timedelta(minutes=5),
            )
        )

    @callback
    def _handle_time_update(self, now) -> None:
        """Update state on interval."""
        self.async_schedule_update_ha_state(True)

    @property
    def is_on(self) -> bool:
        """Return true if API layer is usable."""
        if self._api is None:
            return False

        perenual_key = getattr(self._api, "perenual_key", None)
        if not perenual_key:
            return False

        calls_today = int(getattr(self._api, "_api_calls_today", 0))
        if calls_today >= PERENUAL_DAILY_LIMIT:
            return False

        last_error = getattr(self._api, "_last_error", None)
        if last_error:
            return False

        return True

    @property
    def icon(self) -> str:
        """Return API connectivity icon."""
        return "mdi:api" if self.is_on else "mdi:api-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return API provider status attributes."""
        if self._api is None:
            return {
                "status": "api_client_missing",
                "api_client_loaded": False,
                "api_usable": False,
                "perenual_key_configured": False,
                "trefle_key_configured": False,
                "trefle_enabled": False,
                "inaturalist_enabled": False,
                "perenual_daily_limit": PERENUAL_DAILY_LIMIT,
                "perenual_calls_today": None,
                "perenual_calls_remaining": None,
                "trefle_calls_today": None,
                "inaturalist_calls_today": None,
                "last_provider": None,
                "last_success": None,
                "last_error": "API client is not loaded",
                "updated_at": dt_util.now().isoformat(),
            }

        perenual_key = getattr(self._api, "perenual_key", None)
        trefle_key = getattr(self._api, "trefle_key", None)
        enable_trefle = bool(getattr(self._api, "enable_trefle_fallback", False))
        enable_inaturalist = bool(
            getattr(self._api, "enable_inaturalist_enrichment", False)
        )

        perenual_calls_today = int(getattr(self._api, "_api_calls_today", 0))
        perenual_calls_remaining = max(
            PERENUAL_DAILY_LIMIT - perenual_calls_today,
            0,
        )

        last_error = getattr(self._api, "_last_error", None)
        last_success = getattr(self._api, "_last_success", None)
        last_provider = getattr(self._api, "_last_provider", None)

        perenual_provider = getattr(self._api, "perenual", None)
        trefle_provider = getattr(self._api, "trefle", None)
        inaturalist_provider = getattr(self._api, "inaturalist", None)

        trefle_calls_today = None
        inaturalist_calls_today = None

        if trefle_provider is not None:
            limiter = getattr(trefle_provider, "limiter", None)
            if limiter is not None:
                trefle_calls_today = getattr(limiter, "calls_today", None)

        if inaturalist_provider is not None:
            limiter = getattr(inaturalist_provider, "limiter", None)
            if limiter is not None:
                inaturalist_calls_today = getattr(limiter, "calls_today", None)

        if not perenual_key:
            status = "perenual_key_missing"
        elif perenual_calls_today >= PERENUAL_DAILY_LIMIT:
            status = "perenual_daily_limit_reached"
        elif last_error:
            status = "api_error"
        else:
            status = "connected"

        return {
            "status": status,
            "api_client_loaded": True,
            "api_usable": self.is_on,
            "perenual_key_configured": bool(perenual_key),
            "trefle_key_configured": bool(trefle_key),
            "trefle_enabled": enable_trefle,
            "inaturalist_enabled": enable_inaturalist,
            "perenual_daily_limit": PERENUAL_DAILY_LIMIT,
            "perenual_calls_today": perenual_calls_today,
            "perenual_calls_remaining": perenual_calls_remaining,
            "perenual_usage_percent": round(
                (perenual_calls_today / PERENUAL_DAILY_LIMIT) * 100,
                1,
            ),
            "trefle_calls_today": trefle_calls_today,
            "inaturalist_calls_today": inaturalist_calls_today,
            "last_provider": last_provider,
            "last_success": last_success,
            "last_error": last_error,
            "perenual_last_error": getattr(perenual_provider, "last_error", None)
            if perenual_provider is not None
            else None,
            "trefle_last_error": getattr(trefle_provider, "last_error", None)
            if trefle_provider is not None
            else None,
            "inaturalist_last_error": getattr(
                inaturalist_provider,
                "last_error",
                None,
            )
            if inaturalist_provider is not None
            else None,
            "base_url": getattr(perenual_provider, "base_url", None)
            if perenual_provider is not None
            else getattr(self._api, "_base_url", None),
            "updated_at": dt_util.now().isoformat(),
        }


class PlantBinaryBase(PlantHelperBinaryBase):
    """Base binary sensor for configured plants."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        plant_id: str,
        plant_data: dict[str, Any],
        plant_info: dict[str, Any],
    ) -> None:
        """Initialize plant binary sensor."""
        super().__init__(hass, entry)
        self._plant_id = plant_id
        self._plant_data = plant_data
        self._plant_info = plant_info

    @property
    def device_info(self) -> DeviceInfo:
        """Return plant device info."""
        return DeviceInfo(
            identifiers={(DOMAIN, self._plant_id)},
            name=self._plant_data.get("custom_name") or self._plant_id,
            manufacturer="Plant Helper",
            model=self._plant_info.get(
                "common_name",
                self._plant_data.get("species", "Unknown"),
            ),
            sw_version=str(self._plant_info.get("care_level", "Unknown")),
        )

    def _get_sensor_value(self, key: str) -> float | None:
        """Get numeric value from linked Home Assistant entity."""
        entity_id = _get_linked_entity(self._plant_data, key)

        if not entity_id:
            return None

        state = self.hass.states.get(entity_id)
        if not state or state.state in ("unknown", "unavailable", None):
            return None

        return _safe_float(state.state)

    def _track_entities(self, keys: tuple[str, ...]) -> None:
        """Track linked entity changes."""
        tracked_entities: list[str] = []

        for key in keys:
            entity_id = _get_linked_entity(self._plant_data, key)
            if entity_id:
                tracked_entities.append(entity_id)

        if tracked_entities:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    tracked_entities,
                    self._handle_sensor_update,
                )
            )

    @callback
    def _handle_sensor_update(self, event: Any) -> None:
        """Handle linked entity update."""
        self.async_schedule_update_ha_state(True)

    @property
    def common_attributes(self) -> dict[str, Any]:
        """Return common attributes."""
        return {
            "plant_id": self._plant_id,
            "custom_name": self._plant_data.get("custom_name"),
            "species": self._plant_data.get("species"),
            "common_name": self._plant_info.get("common_name"),
            "scientific_name": self._plant_info.get("scientific_name"),
            "linked_entities": self._plant_data.get("entities", {}),
        }


class PlantNeedsWaterSensor(PlantBinaryBase):
    """Binary sensor for water status."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        plant_id: str,
        plant_data: dict[str, Any],
        plant_info: dict[str, Any],
    ) -> None:
        """Initialize water sensor."""
        super().__init__(hass, entry, plant_id, plant_data, plant_info)
        name = plant_data.get("custom_name") or plant_id
        self._attr_name = f"{name} Needs Water"
        self._attr_unique_id = f"{DOMAIN}_{plant_id}_needs_water"
        self._track_entities(("moisture",))

    @property
    def is_on(self) -> bool:
        """Return true if plant likely needs water."""
        moisture = self._get_sensor_value("moisture")

        if moisture is None:
            return False

        thresholds = self._plant_info.get("thresholds", {})
        moisture_min = thresholds.get("soil_moisture_min")

        if moisture_min is None:
            moisture_min = thresholds.get("humidity_min")

        if moisture_min is None:
            return False

        return moisture < float(moisture_min)

    @property
    def icon(self) -> str:
        """Return icon."""
        return "mdi:water-alert" if self.is_on else "mdi:water-check"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        attrs = self.common_attributes
        thresholds = self._plant_info.get("thresholds", {})
        attrs.update(
            {
                "soil_moisture": self._get_sensor_value("moisture"),
                "soil_moisture_min": thresholds.get("soil_moisture_min")
                or thresholds.get("humidity_min"),
                "source_entity": _get_linked_entity(self._plant_data, "moisture"),
            }
        )
        return attrs


class PlantLowLightSensor(PlantBinaryBase):
    """Binary sensor for low light status."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        plant_id: str,
        plant_data: dict[str, Any],
        plant_info: dict[str, Any],
    ) -> None:
        """Initialize low light sensor."""
        super().__init__(hass, entry, plant_id, plant_data, plant_info)
        name = plant_data.get("custom_name") or plant_id
        self._attr_name = f"{name} Low Light"
        self._attr_unique_id = f"{DOMAIN}_{plant_id}_low_light"
        self._track_entities(("lux",))

    @property
    def is_on(self) -> bool:
        """Return true if light is below threshold."""
        lux = self._get_sensor_value("lux")

        if lux is None:
            return False

        thresholds = self._plant_info.get("thresholds", {})
        lux_min = thresholds.get("lux_min")

        if lux_min is None:
            return False

        return lux < float(lux_min)

    @property
    def icon(self) -> str:
        """Return icon."""
        return "mdi:weather-sunny-alert" if self.is_on else "mdi:white-balance-sunny"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        attrs = self.common_attributes
        thresholds = self._plant_info.get("thresholds", {})
        attrs.update(
            {
                "lux": self._get_sensor_value("lux"),
                "lux_min": thresholds.get("lux_min"),
                "source_entity": _get_linked_entity(self._plant_data, "lux"),
            }
        )
        return attrs


class PlantTemperatureIssueSensor(PlantBinaryBase):
    """Binary sensor for temperature issues."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        plant_id: str,
        plant_data: dict[str, Any],
        plant_info: dict[str, Any],
    ) -> None:
        """Initialize temperature issue sensor."""
        super().__init__(hass, entry, plant_id, plant_data, plant_info)
        name = plant_data.get("custom_name") or plant_id
        self._attr_name = f"{name} Temperature Issue"
        self._attr_unique_id = f"{DOMAIN}_{plant_id}_temperature_issue"
        self._track_entities(("temperature",))

    @property
    def is_on(self) -> bool:
        """Return true if temperature is outside threshold."""
        temperature = self._get_sensor_value("temperature")

        if temperature is None:
            return False

        thresholds = self._plant_info.get("thresholds", {})
        temp_min = thresholds.get("temperature_min")
        temp_max = thresholds.get("temperature_max")

        if temp_min is not None and temperature < float(temp_min):
            return True

        if temp_max is not None and temperature > float(temp_max):
            return True

        return False

    @property
    def icon(self) -> str:
        """Return icon."""
        return "mdi:thermometer-alert" if self.is_on else "mdi:thermometer-check"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return attributes."""
        attrs = self.common_attributes
        thresholds = self._plant_info.get("thresholds", {})
        attrs.update(
            {
                "temperature": self._get_sensor_value("temperature"),
                "temperature_min": thresholds.get("temperature_min"),
                "temperature_max": thresholds.get("temperature_max"),
                "source_entity": _get_linked_entity(self._plant_data, "temperature"),
            }
        )
        return attrs