from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .domain.entity_contract import EntityContract, attributes_for, available, suggested_entity_id, unique_id
from .domain.runtime import PlantSetChange, RuntimePlant

CATEGORIES = {"diagnostic": EntityCategory.DIAGNOSTIC, "config": EntityCategory.CONFIG}


def device_info(runtime: Any, plant: RuntimePlant) -> DeviceInfo:
    """The plant device; every Plant Helper entity of a plant shares it."""
    return DeviceInfo(
        identifiers={(DOMAIN, plant.plant_uuid)},
        name=str(plant.config.get("display_name", plant.plant_uuid)),
        manufacturer="Plant Helper",
        model=runtime.device_model(plant.plant_uuid),
        sw_version=runtime.version,
    )


def async_setup_plant_platform(
    hass: HomeAssistant,
    entry: Any,
    async_add_entities: AddEntitiesCallback,
    platform: str,
    build: Callable[[RuntimePlant], list[Entity]],
    wanted: Callable[[RuntimePlant], bool] = lambda _plant: True,
) -> None:
    """Create each plant's entities for one platform and follow plant changes.

    ``wanted`` lets a platform exist only for some plants (the rain limit is
    outdoor-only); when an edit makes a plant unwanted, its entities are removed
    from the entity registry so they do not linger as unavailable.
    """
    runtime = entry.runtime_data
    known: set[str] = set()

    @callback
    def ensure_plant(plant_uuid: str) -> None:
        """Create this plant's entities once, independent of event timing."""
        if plant_uuid in known:
            return
        plant = runtime.plants.plants.get(plant_uuid)
        if plant is None or plant.removing or not wanted(plant):
            return
        created = build(plant)
        runtime.entities.setdefault(plant_uuid, {})[platform] = created
        known.add(plant_uuid)
        async_add_entities(created)

    @callback
    def drop(plant_uuid: str, *, from_registry: bool) -> None:
        known.discard(plant_uuid)
        registry = er.async_get(hass)
        for entity in runtime.entities.get(plant_uuid, {}).pop(platform, []):
            if from_registry and entity.registry_entry is not None:
                registry.async_remove(entity.entity_id)
            else:
                hass.async_create_task(entity.async_remove())
        if not runtime.entities.get(plant_uuid):
            runtime.entities.pop(plant_uuid, None)

    @callback
    def handle(change: PlantSetChange) -> None:
        for plant_uuid in sorted(change.added):
            ensure_plant(plant_uuid)
        for plant_uuid in change.updated:
            plant = runtime.plants.plants.get(plant_uuid)
            if plant is None:
                continue
            if plant_uuid in known and not wanted(plant):
                drop(plant_uuid, from_registry=True)
                continue
            ensure_plant(plant_uuid)
            for entity in runtime.entities.get(plant_uuid, {}).get(platform, []):
                if entity.hass is not None:
                    entity.async_write_ha_state()
        for plant_uuid in change.removed:
            drop(plant_uuid, from_registry=False)

    runtime.platform_callbacks[platform] = ensure_plant
    entry.async_on_unload(lambda: runtime.platform_callbacks.pop(platform, None))
    entry.async_on_unload(runtime.plants.subscribe(handle))

    for plant_uuid in sorted(runtime.plants.plants):
        ensure_plant(plant_uuid)


class PlantHelperEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, runtime: Any, entry_id: str, plant: RuntimePlant, description: EntityContract) -> None:
        self.plant_uuid = plant.plant_uuid
        self._runtime = runtime
        self._contract = description
        self.key = description.key
        self._plant = plant
        display_name = str(plant.config.get("display_name", plant.plant_uuid))
        self._attr_unique_id = unique_id(entry_id, plant.plant_uuid, description.key)
        self._attr_suggested_object_id = suggested_entity_id(display_name, description.key)
        self._attr_name = description.name
        # The translation key carries the state icons (icons.json) and the state
        # names (translations); no _attr_icon, which would override both.
        self._attr_translation_key = description.key
        self._attr_entity_category = CATEGORIES.get(description.category or "")
        self._attr_device_info = device_info(runtime, plant)

    @property
    def available(self) -> bool:
        return available(self._plant.removing, self._plant.state, self.key)

    @property
    def extra_state_attributes(self):
        return attributes_for(self._contract, self._plant.state)
