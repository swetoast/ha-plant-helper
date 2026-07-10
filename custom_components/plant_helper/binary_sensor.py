"""Plant Helper binary sensors (v4) — thin readers of the engine result."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .engine import precedence as prec
from .entity import PlantEntity, hub_device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    plants = data["plants"]
    ozone_enabled = data.get("ozone_enabled", False)

    entities: list[BinarySensorEntity] = []
    for plant_id, cfg in plants.items():
        name = cfg.get("name", plant_id)
        entities.extend(
            [
                PlantNeedsWaterBinary(coordinator, entry, plant_id, name),
                PlantWeatherHazardBinary(coordinator, entry, plant_id, name),
                PlantSensorFaultBinary(coordinator, entry, plant_id, name),
                PlantObstructionBinary(coordinator, entry, plant_id, name),
                PlantDormantBinary(coordinator, entry, plant_id, name),
            ]
        )
        # Optional ozone advisory: only for outdoor plants, only when configured.
        if ozone_enabled and cfg.get("placement") == "outdoor":
            entities.append(PlantOzoneAdvisoryBinary(coordinator, entry, plant_id, name))

    # Hub-level API diagnostics (one per enrichment provider).
    if data.get("api") is not None:
        for provider_key, label in (
            ("perenual", "Perenual"),
            ("trefle", "Trefle"),
            ("inaturalist", "iNaturalist"),
        ):
            entities.append(ApiHealthBinary(coordinator, entry, provider_key, label))

    async_add_entities(entities)


class _PlantBinaryBase(PlantEntity, BinarySensorEntity):
    """Binary-sensor flavour of the shared plant entity base."""


class PlantNeedsWaterBinary(_PlantBinaryBase):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:water-alert"

    def __init__(self, coordinator, entry, plant_id, name):
        super().__init__(coordinator, entry, plant_id, name, "needs_water", "Needs water")

    @property
    def is_on(self) -> bool:
        r = self._result
        return bool(r and r.precedence.care_action in (prec.WATER_NOW, prec.WATER_SOON))


class PlantWeatherHazardBinary(_PlantBinaryBase):
    _attr_device_class = BinarySensorDeviceClass.SAFETY
    _attr_icon = "mdi:weather-lightning"

    def __init__(self, coordinator, entry, plant_id, name):
        super().__init__(coordinator, entry, plant_id, name, "weather_hazard", "Weather hazard")

    @property
    def is_on(self) -> bool:
        r = self._result
        return bool(r and r.thermal and r.thermal.hazard)


class PlantSensorFaultBinary(_PlantBinaryBase):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:alert-circle"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, plant_id, name):
        super().__init__(coordinator, entry, plant_id, name, "sensor_fault", "Sensor fault")

    @property
    def is_on(self) -> bool:
        r = self._result
        return bool(r and not r.care_ok)

    @property
    def extra_state_attributes(self) -> dict:
        r = self._result
        if not r:
            return {}
        return {
            "reason": r.care_reason,
            "battery_level": r.battery_level,
            "battery_percent": r.battery_percent,
        }


class PlantObstructionBinary(_PlantBinaryBase):
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:blinds"

    def __init__(self, coordinator, entry, plant_id, name):
        super().__init__(coordinator, entry, plant_id, name, "light_obstruction", "Light obstruction")

    @property
    def is_on(self) -> bool:
        r = self._result
        return bool(r and r.light and r.light.obstruction)


class PlantDormantBinary(_PlantBinaryBase):
    _attr_icon = "mdi:sleep"

    def __init__(self, coordinator, entry, plant_id, name):
        super().__init__(coordinator, entry, plant_id, name, "dormant", "Dormant")

    @property
    def is_on(self) -> bool:
        r = self._result
        return bool(r and r.dormant)


class PlantOzoneAdvisoryBinary(_PlantBinaryBase):
    """Advisory only: elevated ground-level ozone may stress outdoor foliage."""

    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_icon = "mdi:molecule"

    def __init__(self, coordinator, entry, plant_id, name):
        super().__init__(coordinator, entry, plant_id, name, "ozone_advisory", "Ozone advisory")

    @property
    def is_on(self) -> bool:
        r = self._result
        return bool(r and r.air_quality and r.air_quality.active)

    @property
    def extra_state_attributes(self) -> dict:
        r = self._result
        if not r or not r.air_quality:
            return {}
        aq = r.air_quality
        return {
            "advisory": aq.advisory,
            "ozone_ugm3": aq.ozone_ugm3,
            "message": aq.message,
        }


class ApiHealthBinary(CoordinatorEntity, BinarySensorEntity):
    """Diagnostics for one enrichment provider (Perenual / Trefle / iNaturalist).

    On = a problem (last call errored, or the provider is disabled). Attributes
    expose last success/error, daily call count and limit, and enabled state —
    mirroring the STRÅNG / AccuWeather API-issue sensors.
    """

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_icon = "mdi:api"

    def __init__(self, coordinator, entry: ConfigEntry, provider_key: str, label: str) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._provider_key = provider_key
        self._attr_name = f"{label} API"
        self._attr_unique_id = f"{entry.entry_id}_api_{provider_key}"

    @property
    def device_info(self):
        return hub_device_info(self._entry)

    def _health(self) -> dict:
        return (getattr(self.coordinator, "api_health", {}) or {}).get(self._provider_key, {})

    @property
    def is_on(self) -> bool:
        # Problem only when the provider is configured/enabled AND its last call
        # errored. An unconfigured provider (no API key) is not a problem.
        health = self._health()
        if not health or not health.get("enabled", True):
            return False
        return health.get("last_error") is not None

    @property
    def extra_state_attributes(self) -> dict:
        health = self._health()
        if not health:
            return {"status": "not_yet_queried"}
        return {
            "provider": health.get("provider"),
            "enabled": health.get("enabled"),
            "last_success": health.get("last_success"),
            "last_error": health.get("last_error"),
            "calls_today": health.get("calls_today"),
            "daily_limit": health.get("daily_limit"),
        }
