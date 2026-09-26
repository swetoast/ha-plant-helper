from __future__ import annotations

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PlantHelperConfigEntry
from .domain.entity_contract import SENSORS
from .domain.physical import BATTERY_STATES
from .entity import PlantHelperEntity, async_setup_plant_platform

# low, middle, high: the order a user reads them in.
BATTERY_OPTIONS = sorted(BATTERY_STATES, key=("low", "middle", "high").index)
BATTERY_ICONS = {"low": "mdi:battery-low", "middle": "mdi:battery-medium", "high": "mdi:battery-high"}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PlantHelperConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up all existing sensors and support live plant changes."""
    runtime = entry.runtime_data

    def build(plant):
        return [
            (PlantHelperBattery if item.key == "battery" else PlantHelperSensor)(
                runtime, entry.entry_id, plant, item
            )
            for item in SENSORS
        ]

    async_setup_plant_platform(hass, entry, async_add_entities, "sensor", build)


class PlantHelperSensor(PlantHelperEntity, SensorEntity):
    """A Plant Helper sensor."""

    def __init__(self, runtime, entry_id, plant, description):
        super().__init__(runtime, entry_id, plant, description)
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_class = (
            SensorDeviceClass(description.device_class) if description.device_class else None
        )
        self._attr_state_class = (
            SensorStateClass(description.state_class) if description.state_class else None
        )
        self._attr_suggested_display_precision = description.precision
        self._attr_options = list(description.options) or None

    @property
    def native_value(self):
        value = self._plant.state.get(self.key)
        if self._contract.options and value not in self._contract.options:
            # An enum sensor may only report a listed state; anything else
            # (health "unknown", no verdict yet) is shown as unknown.
            return None
        return value


class PlantHelperBattery(PlantHelperSensor):
    """Battery level as a percentage, or the source's low/middle/high state.

    Some soil sensors only report a battery category. The entity follows the
    source: numeric sources get the battery device class and a percentage,
    categorical sources become an enum with the three states.
    """

    @property
    def _categorical(self) -> bool:
        return isinstance(self._plant.state.get(self.key), str)

    @property
    def device_class(self):
        return SensorDeviceClass.ENUM if self._categorical else SensorDeviceClass.BATTERY

    @property
    def native_unit_of_measurement(self):
        return None if self._categorical else PERCENTAGE

    @property
    def state_class(self):
        return None if self._categorical else SensorStateClass.MEASUREMENT

    @property
    def suggested_display_precision(self):
        return None if self._categorical else self._contract.precision

    @property
    def options(self):
        return BATTERY_OPTIONS if self._categorical else None

    @property
    def icon(self):
        # Numeric levels use Home Assistant's battery-level icons.
        return BATTERY_ICONS.get(self._plant.state.get(self.key)) if self._categorical else None
