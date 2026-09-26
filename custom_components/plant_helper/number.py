from __future__ import annotations

from homeassistant.components.number import NumberDeviceClass, NumberEntity, NumberMode
from homeassistant.const import UnitOfPrecipitationDepth
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PlantHelperConfigEntry
from .domain.config import RAIN_LIMIT_RANGE
from .domain.entity_contract import RAIN_LIMIT_KEY, suggested_entity_id, unique_id
from .domain.runtime import RuntimePlant
from .entity import CATEGORIES, async_setup_plant_platform, device_info


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PlantHelperConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the rain limit of every outdoor plant."""
    runtime = entry.runtime_data
    async_setup_plant_platform(
        hass,
        entry,
        async_add_entities,
        "number",
        lambda plant: [PlantHelperRainLimit(runtime, entry.entry_id, plant)],
        wanted=lambda plant: plant.config.get("placement") == "outdoor",
    )


class PlantHelperRainLimit(NumberEntity):
    """Forecast rain (mm) at or above which an outdoor plant's watering is paused."""

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_device_class = NumberDeviceClass.PRECIPITATION
    _attr_native_unit_of_measurement = UnitOfPrecipitationDepth.MILLIMETERS
    _attr_native_min_value, _attr_native_max_value = RAIN_LIMIT_RANGE
    _attr_native_step = 0.1
    _attr_mode = NumberMode.BOX
    _attr_entity_category = CATEGORIES["config"]

    def __init__(self, runtime, entry_id: str, plant: RuntimePlant) -> None:
        self._runtime = runtime
        self._plant = plant
        self.plant_uuid = plant.plant_uuid
        display_name = str(plant.config.get("display_name", plant.plant_uuid))
        self._attr_unique_id = unique_id(entry_id, plant.plant_uuid, RAIN_LIMIT_KEY)
        self._attr_suggested_object_id = suggested_entity_id(display_name, RAIN_LIMIT_KEY)
        self._attr_name = "Rain limit"
        self._attr_translation_key = RAIN_LIMIT_KEY
        self._attr_device_info = device_info(runtime, plant)

    @property
    def available(self) -> bool:
        return not self._plant.removing

    @property
    def native_value(self) -> float | None:
        value = self._plant.config.get("rain_limit_mm")
        return float(value) if value is not None else None

    async def async_set_native_value(self, value: float) -> None:
        await self._runtime.async_change_setting(self.plant_uuid, "rain_limit_mm", value)
