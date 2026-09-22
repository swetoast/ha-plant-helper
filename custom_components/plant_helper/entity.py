from __future__ import annotations
from homeassistant.helpers.entity import Entity
from plant_helper_domain.entity_contract import EntityContract,attributes_for,available,suggested_entity_id,unique_id
from plant_helper_domain.runtime import RuntimePlant
from .const import DOMAIN

class PlantHelperEntity(Entity):
    _attr_has_entity_name=True
    _attr_should_poll=False
    def __init__(self,entry_id:str,plant:RuntimePlant,description:EntityContract)->None:
        self.plant_uuid=plant.plant_uuid;self.entity_description=description;self.key=description.key;self._plant=plant
        display_name=str(plant.config.get('display_name',plant.plant_uuid))
        key=description.key
        self._attr_unique_id=f"{entry_id}_{plant.plant_uuid}_{key}"
        assert self._attr_unique_id==unique_id(entry_id,plant.plant_uuid,key)
        self._attr_suggested_object_id=suggested_entity_id(display_name,description.key)
        self._attr_name=description.name;self._attr_icon=description.icon
        self._attr_device_info={'identifiers':{(DOMAIN,plant.plant_uuid)},'name':display_name,'manufacturer':'Plant Helper','model':'Plant'}
    @property
    def available(self)->bool:return available(self._plant.removing,self._plant.state,self.key)
    @property
    def extra_state_attributes(self):return attributes_for(self.entity_description,self._plant.state)
