from __future__ import annotations

from datetime import datetime

from homeassistant.components.event import EventEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PlantHelperConfigEntry
from .domain.entity_contract import WATERING_EVENT_KEY, suggested_entity_id, unique_id
from .domain.runtime import RuntimePlant
from .entity import async_setup_plant_platform, device_info

EVENT_WATERED = "watered"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PlantHelperConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up one watering event entity per plant."""
    runtime = entry.runtime_data
    async_setup_plant_platform(
        hass,
        entry,
        async_add_entities,
        "event",
        lambda plant: [PlantHelperWateringEvent(runtime, entry.entry_id, plant)],
    )


class PlantHelperWateringEvent(EventEntity):
    """Fires once for each detected watering, for automations and the logbook.

    The runtime calls ``watered`` only when a genuinely new watering is
    detected; restoring the stored last watering after a restart never fires.
    """

    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_event_types = [EVENT_WATERED]

    def __init__(self, runtime, entry_id: str, plant: RuntimePlant) -> None:
        self._plant = plant
        self.plant_uuid = plant.plant_uuid
        display_name = str(plant.config.get("display_name", plant.plant_uuid))
        self._attr_unique_id = unique_id(entry_id, plant.plant_uuid, WATERING_EVENT_KEY)
        self._attr_suggested_object_id = suggested_entity_id(display_name, WATERING_EVENT_KEY)
        self._attr_name = "Watering"
        self._attr_translation_key = WATERING_EVENT_KEY
        self._attr_device_info = device_info(runtime, plant)

    @property
    def available(self) -> bool:
        return not self._plant.removing

    @callback
    def watered(self, when: datetime) -> None:
        self._trigger_event(EVENT_WATERED, {"watered_at": when.isoformat()})
        self.async_write_ha_state()
