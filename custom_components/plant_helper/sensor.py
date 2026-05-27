"""Sensor platform for Plant Helper integration.

Creates:
- One database summary sensor
- One configured plants summary sensor
- One grouped status sensor per configured plant
- High-value derived sensors per plant for moisture, light, stress, health,
  and next care action
"""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers import device_registry as dr
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .const import (
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

ENTITY_KEY_ALIASES = {
    "moisture": ("moisture", "moisture_entity", "humidity", "humidity_entity", "soil_moisture", "soil_humidity"),
    "temperature": ("temperature", "temperature_entity", "temp", "temp_entity", "room_temperature", "soil_temperature"),
    "lux": ("lux", "lux_entity", "light", "light_entity", "room_lux"),
    "air_humidity": ("air_humidity", "air_humidity_entity", "room_humidity"),
}

CARE_ACTION_OPTIONS = [
    "none",
    "monitor",
    "water_now",
    "water_soon",
    "increase_light",
    "cool_location",
    "warm_location",
    "raise_humidity",
    "inspect_plant",
    "fertilize",
]

HEALTH_STATE_OPTIONS = ["excellent", "good", "fair", "poor", "critical"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up Plant Helper sensors from config entry."""
    runtime_data = hass.data[DOMAIN][entry.entry_id]
    storage = runtime_data["storage"]

    algorithms = runtime_data.get("algorithms")
    if algorithms is None:
        algorithms = PlantCareAlgorithms(hass, storage)
        runtime_data["algorithms"] = algorithms

    hass.data[DOMAIN].setdefault("plant_sensor_entities", {})
    plant_entities: dict[str, list[SensorEntity]] = hass.data[DOMAIN][
        "plant_sensor_entities"
    ].setdefault(entry.entry_id, {})

    summary_entities: list[SensorEntity] = [
        PlantDatabaseSensor(hass=hass, entry=entry, storage=storage),
        PlantConfiguredPlantsSensor(hass=hass, entry=entry, storage=storage),
    ]
    async_add_entities(summary_entities, True)

    initial_entities: list[SensorEntity] = []
    for plant_id in storage.get_all_user_plants():
        suite = _build_plant_sensor_suite(
            hass=hass,
            entry=entry,
            storage=storage,
            algorithms=algorithms,
            plant_id=plant_id,
        )
        if not suite:
            continue
        plant_entities[plant_id] = suite
        initial_entities.extend(suite)

    if initial_entities:
        async_add_entities(initial_entities, True)

    async def _handle_plant_added(event: Event) -> None:
        if event.data.get("entry_id") not in (None, entry.entry_id):
            return

        plant_id = event.data.get("plant_id")
        if not plant_id or plant_id in plant_entities:
            return

        suite = _build_plant_sensor_suite(
            hass=hass,
            entry=entry,
            storage=storage,
            algorithms=algorithms,
            plant_id=plant_id,
        )
        if not suite:
            return

        plant_entities[plant_id] = suite
        async_add_entities(suite, True)

    async def _handle_plant_removed(event: Event) -> None:
        if event.data.get("entry_id") not in (None, entry.entry_id):
            return

        plant_id = event.data.get("plant_id")
        if not plant_id:
            return

        # Remove all entities for this plant
        for entity in plant_entities.pop(plant_id, []):
            try:
                await entity.async_remove()
            except Exception:
                _LOGGER.debug("Failed removing dynamic entity for plant %s", plant_id)

        # Remove the device from device registry
        device_reg = dr.async_get(hass)
        device = device_reg.async_get_device(identifiers={(DOMAIN, plant_id)})
        if device:
            device_reg.async_remove_device(device.id)

        algorithms.clear_plant(plant_id)

    async def _handle_database_reset(event: Event) -> None:
        if event.data.get("entry_id") not in (None, entry.entry_id):
            return

        device_reg = dr.async_get(hass)
        
        for plant_id in list(plant_entities):
            # Remove all entities
            for entity in plant_entities.pop(plant_id, []):
                try:
                    await entity.async_remove()
                except Exception:
                    _LOGGER.debug("Failed removing dynamic entity for plant %s", plant_id)
            
            # Remove device
            device = device_reg.async_get_device(identifiers={(DOMAIN, plant_id)})
            if device:
                device_reg.async_remove_device(device.id)
            
            algorithms.clear_plant(plant_id)

    entry.async_on_unload(
        hass.bus.async_listen(EVENT_USER_PLANT_ADDED, _handle_plant_added)
    )
    entry.async_on_unload(
        hass.bus.async_listen(EVENT_USER_PLANT_REMOVED, _handle_plant_removed)
    )
    entry.async_on_unload(
        hass.bus.async_listen(EVENT_DATABASE_RESET, _handle_database_reset)
    )


def _build_plant_sensor_suite(
    *,
    hass: HomeAssistant,
    entry: ConfigEntry,
    storage: Any,
    algorithms: PlantCareAlgorithms,
    plant_id: str,
) -> list[SensorEntity]:
    plant_data = storage.get_user_plant(plant_id)
    if not plant_data:
        return []

    plant_info = storage.get_plant(plant_data.get("species")) or {}

    return [
        PlantGroupedStatusSensor(
            hass, entry, storage, plant_id, plant_data, plant_info, algorithms
        ),
        PlantCalculatedSoilMoistureSensor(
            hass, entry, storage, plant_id, plant_data, plant_info, algorithms
        ),
        PlantLightScoreSensor(
            hass, entry, storage, plant_id, plant_data, plant_info, algorithms
        ),
        PlantTemperatureStressLoadSensor(
            hass, entry, storage, plant_id, plant_data, plant_info, algorithms
        ),
        PlantHealthScoreSensor(
            hass, entry, storage, plant_id, plant_data, plant_info, algorithms
        ),
        PlantCareActionSensor(
            hass, entry, storage, plant_id, plant_data, plant_info, algorithms
        ),
    ]


def _get_linked_entity(plant_data: dict[str, Any], key: str) -> str | None:
    entities = plant_data.get("entities", {}) if isinstance(plant_data, dict) else {}
    for alias in ENTITY_KEY_ALIASES.get(key, (key, f"{key}_entity")):
        value = entities.get(alias)
        if value:
            return str(value)
    return None


class PlantSummaryBaseSensor(SensorEntity):
    """Base class for summary sensors."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, storage: Any) -> None:
        self.hass = hass
        self._entry = entry
        self._storage = storage

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._entry.entry_id)},
            name="Plant Helper",
            manufacturer="Plant Helper",
            model="Integration Summary",
        )


class PlantDatabaseSensor(PlantSummaryBaseSensor):
    """Sensor exposing cached Plant Helper database species."""

    _attr_icon = "mdi:database"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, storage: Any) -> None:
        super().__init__(hass, entry, storage)
        self._attr_name = "Plant Helper Database"
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_database"

    @property
    def native_value(self) -> int:
        return len(self._storage.get_all_plants())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        plants = self._storage.get_all_plants()
        names = sorted(
            [data.get("common_name") or species for species, data in plants.items()],
            key=lambda item: item.lower(),
        )
        return {
            "cached_species_count": len(plants),
            "cached_common_names": ", ".join(names),
            "cached_species": ", ".join(sorted(plants.keys())),
            "updated_at": dt_util.now().isoformat(),
        }


class PlantConfiguredPlantsSensor(PlantSummaryBaseSensor):
    """Sensor exposing configured/user plants."""

    _attr_icon = "mdi:flower-outline"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, storage: Any) -> None:
        super().__init__(hass, entry, storage)
        self._attr_name = "Plant Helper Configured Plants"
        self._attr_unique_id = f"{DOMAIN}_{entry.entry_id}_configured_plants"

    @property
    def native_value(self) -> int:
        return len(self._storage.get_all_user_plants())

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        user_plants = self._storage.get_all_user_plants()
        configured_entries = []
        for plant_id, plant_data in sorted(user_plants.items()):
            configured_entries.append(
                {
                    "plant_id": plant_id,
                    "custom_name": plant_data.get("custom_name") or plant_id,
                    "species": plant_data.get("species"),
                    "last_watered": plant_data.get("last_watered"),
                    "last_fertilized": plant_data.get("last_fertilized"),
                    "last_inspected": plant_data.get("last_inspected"),
                }
            )
        return {
            "configured_plants_count": len(user_plants),
            "configured_entries": configured_entries,
            "plant_ids": list(sorted(user_plants.keys())),
            "updated_at": dt_util.now().isoformat(),
        }


class PlantDerivedBaseSensor(SensorEntity):
    """Base class for per-plant derived sensors."""

    _attr_has_entity_name = True

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        storage: Any,
        plant_id: str,
        plant_data: dict[str, Any],
        plant_info: dict[str, Any],
        algorithms: PlantCareAlgorithms,
    ) -> None:
        self.hass = hass
        self._entry = entry
        self._storage = storage
        self._plant_id = plant_id
        self._plant_data = plant_data
        self._plant_info = plant_info
        self._algorithms = algorithms
        self._cached_metrics: dict[str, Any] | None = None

    @property
    def device_info(self) -> DeviceInfo:
        return DeviceInfo(
            identifiers={(DOMAIN, self._plant_id)},
            name=self._plant_data.get("custom_name") or self._plant_id,
            manufacturer="Plant Helper",
            model=self._plant_info.get("common_name")
            or self._plant_data.get("species")
            or "Plant",
            sw_version=str(self._plant_info.get("care_level", "Unknown")),
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()

        tracked_entities = [
            entity_id
            for key in ("moisture", "temperature", "lux", "air_humidity")
            if (entity_id := _get_linked_entity(self._plant_data, key))
        ]

        if tracked_entities:
            self.async_on_remove(
                async_track_state_change_event(
                    self.hass,
                    tracked_entities,
                    self._handle_source_update,
                )
            )

        for event_type in (
            EVENT_PLANT_WATERED,
            EVENT_PLANT_FERTILIZED,
            EVENT_PLANT_INSPECTED,
            EVENT_USER_PLANT_ADDED,
            EVENT_PLANT_DATA_FETCHED,
        ):
            self.async_on_remove(
                self.hass.bus.async_listen(event_type, self._handle_plant_event)
            )

        self.hass.async_create_task(
            self._algorithms.record_runtime_sample(self._plant_id, self._plant_data)
        )

    @callback
    def _handle_source_update(self, event: Event) -> None:
        self.hass.async_create_task(
            self._algorithms.record_runtime_sample(self._plant_id, self._plant_data)
        )
        self._cached_metrics = None
        self.async_schedule_update_ha_state(True)

    @callback
    def _handle_plant_event(self, event: Event) -> None:
        if event.data.get("entry_id") not in (None, self._entry.entry_id):
            return
        if event.data.get("plant_id") not in (None, self._plant_id):
            return

        latest_plant_data = self._storage.get_user_plant(self._plant_id)
        if latest_plant_data:
            self._plant_data = latest_plant_data

        species = self._plant_data.get("species")
        latest_plant_info = self._storage.get_plant(species)
        if latest_plant_info:
            self._plant_info = latest_plant_info

        self._cached_metrics = None
        self.async_schedule_update_ha_state(True)

    def _metrics(self) -> dict[str, Any]:
        if self._cached_metrics is None:
            self._cached_metrics = self._algorithms.compute_metrics(
                self._plant_id,
                self._plant_data,
                self._plant_info,
            )
        return self._cached_metrics

    def _common_attrs(self) -> dict[str, Any]:
        metrics = self._metrics()
        return {
            "plant_id": self._plant_id,
            "custom_name": self._plant_data.get("custom_name") or self._plant_id,
            "species": self._plant_data.get("species"),
            "common_name": self._plant_info.get("common_name")
            or self._plant_data.get("species"),
            "growth_mode": metrics.get("growth_mode"),
            "updated_at": metrics.get("updated_at"),
        }


class PlantGroupedStatusSensor(PlantDerivedBaseSensor):
    """Single grouped status sensor for one configured plant."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = HEALTH_STATE_OPTIONS
    _attr_icon = "mdi:sprout"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_name = "Plant Status"
        self._attr_unique_id = f"{DOMAIN}_{self._entry.entry_id}_{self._plant_id}_status"

    @property
    def native_value(self) -> str:
        return self._metrics()["health_state"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        metrics = self._metrics()
        attrs = self._common_attrs()
        attrs.update(
            {
                "health_score": metrics.get("health_score"),
                "primary_issue": metrics.get("primary_issue"),
                "care_action": metrics.get("care_action"),
                "watering_state": metrics.get("watering_state"),
                "light_state": metrics.get("light_state"),
                "temperature_state": metrics.get("temperature_state"),
                "air_humidity_state": metrics.get("air_humidity_state"),
                "maintenance_state": metrics.get("maintenance_state"),
                "calculated_soil_moisture": metrics.get("calculated_soil_moisture"),
                "watering_urgency": metrics.get("watering_urgency"),
                "days_until_watering": metrics.get("days_until_watering"),
                "light_score": metrics.get("light_score"),
                "temperature_stress_load": metrics.get("temperature_stress_load"),
                "air_humidity_score": metrics.get("air_humidity_score"),
                "drying_rate_factor": metrics.get("drying_rate_factor"),
                "days_since_watered": metrics.get("days_since_watered"),
                "days_since_fertilized": metrics.get("days_since_fertilized"),
                "days_since_inspected": metrics.get("days_since_inspected"),
                "soil_moisture_source": metrics.get("soil_moisture_source"),
                "thresholds": {
                    "soil_moisture_min": metrics.get("soil_moisture_min"),
                    "soil_moisture_max": metrics.get("soil_moisture_max"),
                    "temperature_min": metrics.get("temperature_min"),
                    "temperature_max": metrics.get("temperature_max"),
                    "air_humidity_min": metrics.get("air_humidity_min"),
                    "air_humidity_max": metrics.get("air_humidity_max"),
                    "lux_min": metrics.get("lux_min"),
                },
            }
        )
        
        # Add iNaturalist enrichment data if available
        inat_data = self._plant_info.get("inat", {}) if isinstance(self._plant_info, dict) else {}
        
        # Always show enrichment status for debugging
        enrichment_status = self._plant_info.get("inaturalist_enriched", False) if isinstance(self._plant_info, dict) else False
        enrichment_msg = self._plant_info.get("inaturalist_message", "Not available") if isinstance(self._plant_info, dict) else "Not available"
        
        attrs["inaturalist_enriched"] = enrichment_status
        attrs["inaturalist_message"] = enrichment_msg
        
        if inat_data:
            photos = inat_data.get("photos", [])[:3]  # Top 3 photos only
            
            # Always add observation count and error info if present
            attrs["inat_count"] = inat_data.get("observation_count", 0)
            if inat_data.get("error"):
                attrs["inat_error"] = inat_data["error"]
            
            if photos:
                # Primary photo for easy dashboard use
                attrs["inat_photo"] = photos[0].get("url")
                
                # All photos with attribution (for advanced use)
                attrs["inat_photos"] = [
                    {
                        "url": p.get("url"),
                        "license": p.get("license_code"),
                        "attribution": p.get("attribution"),
                    }
                    for p in photos
                    if p.get("url")
                ]
                
                # Link to view all observations
                # Use scientific_name for accurate iNaturalist search, fall back to species if not available
                scientific_name = self._plant_info.get("scientific_name") or self._plant_data.get("species")
                if scientific_name:
                    attrs["inat_url"] = f"https://www.inaturalist.org/observations?taxon_name={scientific_name.replace(' ', '+')}"
        
        return attrs


class PlantCalculatedSoilMoistureSensor(PlantDerivedBaseSensor):
    """Calculated soil moisture estimate for the plant."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:water-percent"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_name = "Calculated Soil Moisture"
        self._attr_unique_id = (
            f"{DOMAIN}_{self._entry.entry_id}_{self._plant_id}_calculated_soil_moisture"
        )

    @property
    def native_value(self) -> float:
        return self._metrics()["calculated_soil_moisture"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        metrics = self._metrics()
        return {
            "watering_state": metrics.get("watering_state"),
            "watering_urgency": metrics.get("watering_urgency"),
            "days_until_watering": metrics.get("days_until_watering"),
            "days_since_watered": metrics.get("days_since_watered"),
            "drying_rate_factor": metrics.get("drying_rate_factor"),
            "drying_rate_per_hour": metrics.get("drying_rate_per_hour"),
            "soil_moisture_model": metrics.get("soil_moisture_model"),
            "soil_moisture_source": metrics.get("soil_moisture_source"),
            "real_soil_moisture": metrics.get("soil_moisture_sensor"),
            "soil_moisture_min": metrics.get("soil_moisture_min"),
            "soil_moisture_max": metrics.get("soil_moisture_max"),
        }


class PlantLightScoreSensor(PlantDerivedBaseSensor):
    """Daily accumulated light score for the plant."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:white-balance-sunny"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_name = "Light Score"
        self._attr_unique_id = f"{DOMAIN}_{self._entry.entry_id}_{self._plant_id}_light_score"

    @property
    def native_value(self) -> float:
        return self._metrics()["light_score"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        metrics = self._metrics()
        return {
            "light_state": metrics.get("light_state"),
            "current_lux": metrics.get("current_lux"),
            "peak_lux_today": metrics.get("peak_lux_today"),
            "sufficient_light_minutes_today": metrics.get(
                "sufficient_light_minutes_today"
            ),
            "bright_light_minutes_today": metrics.get("bright_light_minutes_today"),
            "low_light_minutes_today": metrics.get("low_light_minutes_today"),
            "daily_light_target_minutes": metrics.get("daily_light_target_minutes"),
            "lux_min": metrics.get("lux_min"),
        }


class PlantTemperatureStressLoadSensor(PlantDerivedBaseSensor):
    """Temperature stress duration/load for the plant."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:thermometer-alert"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_name = "Temperature Stress Load"
        self._attr_unique_id = (
            f"{DOMAIN}_{self._entry.entry_id}_{self._plant_id}_temperature_stress_load"
        )

    @property
    def native_value(self) -> float:
        return self._metrics()["temperature_stress_load"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        metrics = self._metrics()
        return {
            "temperature_state": metrics.get("temperature_state"),
            "current_temperature": metrics.get("temperature"),
            "cold_stress_minutes_today": metrics.get("cold_stress_minutes_today"),
            "heat_stress_minutes_today": metrics.get("heat_stress_minutes_today"),
            "min_temp_today": metrics.get("min_temp_today"),
            "max_temp_today": metrics.get("max_temp_today"),
            "temperature_min": metrics.get("temperature_min"),
            "temperature_max": metrics.get("temperature_max"),
        }


class PlantHealthScoreSensor(PlantDerivedBaseSensor):
    """Weighted overall health score for the plant."""

    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_icon = "mdi:heart-pulse"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_name = "Health Score"
        self._attr_unique_id = f"{DOMAIN}_{self._entry.entry_id}_{self._plant_id}_health_score"

    @property
    def native_value(self) -> float:
        return self._metrics()["health_score"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        metrics = self._metrics()
        return {
            "health_state": metrics.get("health_state"),
            "primary_issue": metrics.get("primary_issue"),
            "care_action": metrics.get("care_action"),
            "moisture_score": metrics.get("moisture_score"),
            "light_score": metrics.get("light_score"),
            "temperature_score": metrics.get("temperature_score"),
            "air_humidity_score": metrics.get("air_humidity_score"),
            "maintenance_score": metrics.get("maintenance_score"),
        }


class PlantCareActionSensor(PlantDerivedBaseSensor):
    """Enum sensor telling the user what action matters most right now."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = CARE_ACTION_OPTIONS
    _attr_icon = "mdi:clipboard-pulse-outline"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._attr_name = "Care Action"
        self._attr_unique_id = f"{DOMAIN}_{self._entry.entry_id}_{self._plant_id}_care_action"

    @property
    def native_value(self) -> str:
        return self._metrics()["care_action"]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        metrics = self._metrics()
        return {
            "primary_issue": metrics.get("primary_issue"),
            "health_state": metrics.get("health_state"),
            "watering_state": metrics.get("watering_state"),
            "light_state": metrics.get("light_state"),
            "temperature_state": metrics.get("temperature_state"),
            "air_humidity_state": metrics.get("air_humidity_state"),
            "maintenance_state": metrics.get("maintenance_state"),
        }
