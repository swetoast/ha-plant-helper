from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PlantHelperConfigEntry
from .domain.entity_contract import BINARY_SENSORS
from .entity import PlantHelperEntity, async_setup_plant_platform


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PlantHelperConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up all existing binary sensors and support live plant changes."""
    runtime = entry.runtime_data
    async_setup_plant_platform(
        hass,
        entry,
        async_add_entities,
        "binary_sensor",
        lambda plant: [
            PlantHelperBinarySensor(runtime, entry.entry_id, plant, item)
            for item in BINARY_SENSORS
        ],
    )


class PlantHelperBinarySensor(PlantHelperEntity, BinarySensorEntity):
    """A Plant Helper binary sensor."""

    def __init__(self, runtime, entry_id, plant, description):
        super().__init__(runtime, entry_id, plant, description)
        self._attr_device_class = BinarySensorDeviceClass(description.device_class)

    @property
    def is_on(self):
        return bool(self._plant.state.get(self.key))
