from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import PlantHelperConfigEntry
from .domain.entity_contract import BINARY_SENSORS
from .domain.runtime import PlantSetChange
from .entity import PlantHelperEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: PlantHelperConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up all existing binary sensors and support live plant changes."""
    runtime = entry.runtime_data
    known: set[str] = set()

    @callback
    def ensure_plant(plant_uuid: str) -> None:
        """Create this plant's binary sensors once, independent of event timing."""
        if plant_uuid in known:
            return
        plant = runtime.plants.plants.get(plant_uuid)
        if plant is None:
            return
        created = [
            PlantHelperBinarySensor(entry.entry_id, plant, item)
            for item in BINARY_SENSORS
        ]
        runtime.entities.setdefault(plant_uuid, {})["binary_sensor"] = created
        known.add(plant_uuid)
        async_add_entities(created)

    @callback
    def handle(change: PlantSetChange) -> None:
        for plant_uuid in sorted(change.added):
            ensure_plant(plant_uuid)
        for plant_uuid in change.updated:
            for entity in runtime.entities.get(plant_uuid, {}).get("binary_sensor", []):
                entity.async_write_ha_state()
        for plant_uuid in change.removed:
            known.discard(plant_uuid)
            for entity in runtime.entities.get(plant_uuid, {}).pop("binary_sensor", []):
                hass.async_create_task(entity.async_remove())
            if not runtime.entities.get(plant_uuid):
                runtime.entities.pop(plant_uuid, None)

    runtime.platform_callbacks["binary_sensor"] = ensure_plant
    entry.async_on_unload(
        lambda: runtime.platform_callbacks.pop("binary_sensor", None)
    )
    entry.async_on_unload(runtime.plants.subscribe(handle))

    for plant_uuid in sorted(runtime.plants.plants):
        ensure_plant(plant_uuid)


class PlantHelperBinarySensor(PlantHelperEntity, BinarySensorEntity):
    """A Plant Helper binary sensor."""

    @property
    def is_on(self):
        return bool(self._plant.state.get(self.key))
