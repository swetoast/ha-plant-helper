"""Plant Helper sensors (v4) — thin readers of the engine result.

Every sensor pulls from the coordinator's per-plant `EngineResult`; all logic
lives in the engine. No decisions are made here.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .entity import PlantEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    data = hass.data[DOMAIN][entry.entry_id]
    coordinator = data["coordinator"]
    plants = data["plants"]

    entities: list[SensorEntity] = []
    for plant_id, cfg in plants.items():
        name = cfg.get("name", plant_id)
        entities.extend(
            [
                PlantHealthSensor(coordinator, entry, plant_id, name),
                PlantCareActionSensor(coordinator, entry, plant_id, name),
                PlantMoistureStateSensor(coordinator, entry, plant_id, name),
                PlantLightStateSensor(coordinator, entry, plant_id, name),
                PlantThermalStateSensor(coordinator, entry, plant_id, name),
                PlantCalibrationSensor(coordinator, entry, plant_id, name),
                PlantSpeciesInfoSensor(coordinator, entry, plant_id, name),
            ]
        )
    async_add_entities(entities)


class _PlantSensorBase(PlantEntity, SensorEntity):
    """Sensor flavour of the shared plant entity base."""


class PlantHealthSensor(_PlantSensorBase):
    _attr_native_unit_of_measurement = "%"
    _attr_icon = "mdi:heart-pulse"

    def __init__(self, coordinator, entry, plant_id, name):
        super().__init__(coordinator, entry, plant_id, name, "health", "Health")

    @property
    def native_value(self) -> float | None:
        r = self._result
        if not r or r.calibrating:
            return None
        return r.health.score

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self._result
        if not r:
            return {}
        return {
            "health_state": r.health.state,
            "components": r.health.components,
            "primary_issue": r.precedence.primary_issue,
            "reason": r.precedence.reason,
            "dormant": r.dormant,
            "calibrating": r.calibrating,
        }


class PlantCareActionSensor(_PlantSensorBase):
    _attr_icon = "mdi:clipboard-check"

    def __init__(self, coordinator, entry, plant_id, name):
        super().__init__(coordinator, entry, plant_id, name, "care_action", "Care action")

    @property
    def native_value(self) -> str | None:
        r = self._result
        return r.precedence.care_action if r else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self._result
        if not r:
            return {}
        return {
            "primary_issue": r.precedence.primary_issue,
            "reason": r.precedence.reason,
            "severity": r.precedence.severity,
        }


class PlantMoistureStateSensor(_PlantSensorBase):
    _attr_icon = "mdi:water"

    def __init__(self, coordinator, entry, plant_id, name):
        super().__init__(coordinator, entry, plant_id, name, "moisture_state", "Moisture")

    @property
    def native_value(self) -> str | None:
        r = self._result
        return r.moisture.state if (r and r.moisture) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self._result
        if not r or not r.moisture:
            return {}
        m = r.moisture
        run = r.run_minutes or {}
        return {
            "calculated_moisture": m.calculated_moisture,
            "days_until_dry": m.days_until_dry,
            "days_since_watered": m.days_since_watered,
            "watering_urgency": m.urgency,
            "suppressed_by_rain": m.suppressed,
            "days_dry": round(run["dry"] / 1440.0, 2) if run.get("dry") else 0,
            "days_wet": round(run["wet"] / 1440.0, 2) if run.get("wet") else 0,
        }


class PlantLightStateSensor(_PlantSensorBase):
    _attr_icon = "mdi:white-balance-sunny"

    def __init__(self, coordinator, entry, plant_id, name):
        super().__init__(coordinator, entry, plant_id, name, "light_state", "Light")

    @property
    def native_value(self) -> str | None:
        r = self._result
        return r.light.state if (r and r.light) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self._result
        if not r or not r.light:
            return {}
        return {
            "light_score": r.light.score,
            "adequacy_ratio": r.light.adequacy_ratio,
            "obstruction": r.light.obstruction,
            "source": r.light.source,
            "light_hours_today": r.light_hours_today,
            "daylight_hours": r.daylight_hours,
        }


class PlantThermalStateSensor(_PlantSensorBase):
    _attr_icon = "mdi:thermometer"

    def __init__(self, coordinator, entry, plant_id, name):
        super().__init__(coordinator, entry, plant_id, name, "thermal_state", "Temperature")

    @property
    def native_value(self) -> str | None:
        r = self._result
        return r.thermal.state if (r and r.thermal) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        r = self._result
        if not r or not r.thermal:
            return {}
        run = r.run_minutes or {}
        return {
            "drying_modifier": r.thermal.drying_modifier,
            "hazard": r.thermal.hazard,
            "hazard_type": r.thermal.hazard_type,
            "days_cold": round(run["cold"] / 1440.0, 2) if run.get("cold") else 0,
            "days_warm": round(run["warm"] / 1440.0, 2) if run.get("warm") else 0,
        }


class PlantCalibrationSensor(_PlantSensorBase):
    _attr_icon = "mdi:progress-wrench"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator, entry, plant_id, name):
        super().__init__(coordinator, entry, plant_id, name, "calibration", "Calibration")

    @property
    def native_value(self) -> str | None:
        r = self._result
        if not r:
            return None
        return "calibrating" if r.calibrating else "active"


class PlantSpeciesInfoSensor(_PlantSensorBase):
    """Species context from the enrichment providers (Perenual/Trefle/iNaturalist).

    Reference/context only — it never affects care. State is the common name;
    attributes carry care guidance, toxicity, a suggested profile, a reference
    watering interval, and environmental preferences. A photo (if any) is shown
    as the entity picture.
    """

    _attr_icon = "mdi:sprout"

    def __init__(self, coordinator, entry, plant_id, name):
        super().__init__(coordinator, entry, plant_id, name, "species_info", "Species")

    def _info(self) -> dict[str, Any]:
        enrichment = getattr(self.coordinator, "enrichment", {}) or {}
        return enrichment.get(self._plant_id, {})

    @property
    def available(self) -> bool:
        # Independent of the engine result; available once enrichment exists.
        return bool(self._info())

    @property
    def native_value(self) -> str | None:
        info = self._info()
        return info.get("common_name") or info.get("scientific_name")

    @property
    def entity_picture(self) -> str | None:
        return self._info().get("photo")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        # Enrichment display context + the read-only species-insight layer
        # (confidence, provider-vs-learned comparison, explanations). None of it
        # affects care — the calibrated engine still owns every decision.
        from .enrichment import species_insight

        info = dict(self._info())
        result = self._result
        calibrating = bool(result.calibrating) if result is not None else True
        learned_interval = (
            result.learned_watering_interval_days if result is not None else None
        )
        info.update(
            species_insight(
                info, calibrating=calibrating, learned_interval_days=learned_interval
            )
        )
        return info
