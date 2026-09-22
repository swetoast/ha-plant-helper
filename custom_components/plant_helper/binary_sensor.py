from __future__ import annotations
from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import HomeAssistant,callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from .domain.entity_contract import BINARY_SENSORS
from .domain.runtime import PlantSetChange,RuntimePlant
from . import PlantHelperConfigEntry
from .entity import PlantHelperEntity

async def async_setup_entry(hass:HomeAssistant,entry:PlantHelperConfigEntry,async_add_entities:AddEntitiesCallback)->None:
    runtime=entry.runtime_data;known:set[str]=set()
    @callback
    def handle(change:PlantSetChange)->None:
        new=change.added-known
        if new:
            entities=[]
            for uuid in sorted(new):
                created=[PlantHelperBinarySensor(entry.entry_id,runtime.plants.plants[uuid],item) for item in BINARY_SENSORS];runtime.entities.setdefault(uuid,{})['binary_sensor']=created;entities.extend(created);known.add(uuid)
            async_add_entities(entities)
        for uuid in change.updated:
            for entity in runtime.entities.get(uuid,{}).get('binary_sensor',[]):entity.async_write_ha_state()
        for uuid in change.removed:
            known.discard(uuid)
            for entity in runtime.entities.get(uuid,{}).pop('binary_sensor',[]):hass.async_create_task(entity.async_remove())
            if not runtime.entities.get(uuid):runtime.entities.pop(uuid,None)
    unsubscribe=runtime.plants.subscribe(handle);entry.async_on_unload(unsubscribe)
    existing=frozenset(runtime.plants.plants)
    if existing:handle(PlantSetChange(existing,frozenset(),frozenset()))

class PlantHelperBinarySensor(PlantHelperEntity,BinarySensorEntity):
    def __init__(self,entry_id,plant,description):super().__init__(entry_id,plant,description);self._attr_device_class=description.device_class
    @property
    def is_on(self)->bool|None:
        value=self._plant.state.get(self.key);return value if isinstance(value,bool) else None
