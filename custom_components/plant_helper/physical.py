from __future__ import annotations
from typing import Any
from homeassistant.core import HomeAssistant,Event,callback
from homeassistant.helpers.event import async_track_state_change_event
from plant_helper_domain.physical import PlantPhysicalProcessor

PHYSICAL_KEYS=("soil_moisture","soil_temperature","humidity_sensor","lux","battery")
class PhysicalSubscriptions:
 def __init__(self,hass:HomeAssistant,processor:PlantPhysicalProcessor)->None:
  self.hass=hass;self.processor=processor;self._unsubs:dict[str,list[Any]]={}
 def replace(self,plant_uuid:str,config:dict[str,Any])->None:
  self.unsubscribe(plant_uuid)
  unsubs=[]
  for key in PHYSICAL_KEYS:
   entity_id=config.get(key)
   if entity_id:
    @callback
    def changed(event:Event,key:str=key,plant_uuid:str=plant_uuid)->None:
     new_state=event.data.get("new_state")
     self.processor.accept(plant_uuid,key,None if new_state is None else new_state.state)
    unsubs.append(async_track_state_change_event(self.hass,[entity_id],changed))
  self._unsubs[plant_uuid]=unsubs
 def unsubscribe(self,plant_uuid:str)->None:
  for unsub in self._unsubs.pop(plant_uuid,[]):unsub()
  self.processor.unload_plant(plant_uuid)
 def unload(self)->None:
  for plant_uuid in tuple(self._unsubs):self.unsubscribe(plant_uuid)
  self.processor.unload()
