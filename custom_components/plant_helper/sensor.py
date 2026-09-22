from __future__ import annotations

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PlantHelperConfigEntry
from .domain.entity_contract import SENSORS
from .domain.runtime import PlantSetChange, RuntimePlant
from .entity import PlantHelperEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PlantHelperConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up all existing sensors and support live plant changes."""
    runtime = entry.runtime_data
    known: set[str] = set()

    def entities_for(plant: RuntimePlant) -> list[PlantHelperSensor]:
        return [PlantHelperSensor(entry.entry_id, plant, item) for item in SENSORS]

    @callback
    def ensure_plant(plant_uuid: str) -> None:
        """Create this plant's sensors once, independent of event timing."""
        if plant_uuid in known:
            return
        plant = runtime.plants.plants.get(plant_uuid)
        if plant is None:
            return
        created = entities_for(plant)
        runtime.entities.setdefault(plant_uuid, {})["sensor"] = created
        known.add(plant_uuid)
        async_add_entities(created)

    @callback
    def handle(change: PlantSetChange) -> None:
        for plant_uuid in sorted(change.added):
            ensure_plant(plant_uuid)
        for plant_uuid in change.updated:
            for entity in runtime.entities.get(plant_uuid, {}).get("sensor", []):
                entity.async_write_ha_state()
        for plant_uuid in change.removed:
            known.discard(plant_uuid)
            for entity in runtime.entities.get(plant_uuid, {}).pop("sensor", []):
                hass.async_create_task(entity.async_remove())
            if not runtime.entities.get(plant_uuid):
                runtime.entities.pop(plant_uuid, None)

    runtime.platform_callbacks["sensor"] = ensure_plant
    entry.async_on_unload(lambda: runtime.platform_callbacks.pop("sensor", None))
    entry.async_on_unload(runtime.plants.subscribe(handle))

    for plant_uuid in sorted(runtime.plants.plants):
        ensure_plant(plant_uuid)


class PlantHelperSensor(PlantHelperEntity, SensorEntity):
    """A Plant Helper sensor."""

    def __init__(self, entry_id, plant, description):
        super().__init__(entry_id, plant, description)
        self._attr_native_unit_of_measurement = description.unit
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class

    @property
    def native_value(self):
        return self._plant.state.get(self.key)
