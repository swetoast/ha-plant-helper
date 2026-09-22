from __future__ import annotations
from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant,callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from plant_helper_domain.entity_contract import SENSORS
from plant_helper_domain.runtime import PlantSetChange,RuntimePlant
from . import PlantHelperConfigEntry
from .entity import PlantHelperEntity

async def async_setup_entry(hass:HomeAssistant,entry:PlantHelperConfigEntry,async_add_entities:AddEntitiesCallback)->None:
    runtime=entry.runtime_data;known:set[str]=set()
    def entities_for(plant:RuntimePlant):return [PlantHelperSensor(entry.entry_id,plant,item) for item in SENSORS]
    @callback
    def handle(change:PlantSetChange)->None:
        new=change.added-known
        if new:
            entities=[]
            for uuid in sorted(new):
                created=entities_for(runtime.plants.plants[uuid]);runtime.entities.setdefault(uuid,{})['sensor']=created;entities.extend(created);known.add(uuid)
            async_add_entities(entities)
        for uuid in change.updated:
            for entity in runtime.entities.get(uuid,{}).get('sensor',[]):entity.async_write_ha_state()
        for uuid in change.removed:
            known.discard(uuid)
            for entity in runtime.entities.get(uuid,{}).pop('sensor',[]):hass.async_create_task(entity.async_remove())
            if not runtime.entities.get(uuid):runtime.entities.pop(uuid,None)
    unsubscribe=runtime.plants.subscribe(handle);entry.async_on_unload(unsubscribe)
    existing=frozenset(runtime.plants.plants)
    if existing:handle(PlantSetChange(existing,frozenset(),frozenset()))

class PlantHelperSensor(PlantHelperEntity,SensorEntity):
    def __init__(self,entry_id,plant,description):
        super().__init__(entry_id,plant,description);self._attr_native_unit_of_measurement=description.unit;self._attr_device_class=description.device_class;self._attr_state_class=description.state_class
    @property
    def native_value(self):return self._plant.state.get(self.key)
