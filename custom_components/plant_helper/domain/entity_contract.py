from __future__ import annotations
import re,unicodedata
from dataclasses import dataclass
from typing import Any,Mapping

@dataclass(frozen=True,slots=True)
class EntityContract:
 platform:str
 key:str
 name:str
 unit:str|None=None
 device_class:str|None=None
 state_class:str|None=None
 icon:str|None=None
 attributes:tuple[str,...]=()

SENSORS=(
 EntityContract('sensor','care_status','Status',icon='mdi:sprout',attributes=('summary','reason','since','confidence','drying_context','light_context','humidity_context','dormant','placement','rain_suppression','frost_hours','exposure','external_daylight')),
 EntityContract('sensor','moisture','Moisture','%',device_class='moisture',state_class='measurement',icon='mdi:water-percent'),
 EntityContract('sensor','light','Light','lx',device_class='illuminance',state_class='measurement',icon='mdi:brightness-5'),
 EntityContract('sensor','temperature','Temperature','\u00b0C',device_class='temperature',state_class='measurement',icon='mdi:thermometer'),
 EntityContract('sensor','humidity','Humidity','%',device_class='humidity',state_class='measurement',icon='mdi:water-percent'),
 EntityContract('sensor','battery','Battery',icon='mdi:battery'),
 EntityContract('sensor','health','Health',icon='mdi:leaf',attributes=('summary',)),
 EntityContract('sensor','calibration','Calibration',icon='mdi:tune',attributes=('summary',)),
 EntityContract('sensor','species_context','Species',icon='mdi:flower',attributes=('scientific_name','common_name','family','genus','watering_category','sunlight_requirements','image_url','light_requirement','humidity_requirement','soil_moisture_requirement','ph_minimum','ph_maximum','minimum_temperature_c','maximum_temperature_c','growth_habit','growth_rate','toxicity','average_height_cm','duration','edible')),
)
BINARY_SENSORS=(EntityContract('binary_sensor','needs_attention','Needs attention',device_class='problem',icon='mdi:alert-circle-outline',attributes=('reason',)),)
BY_KEY={item.key:item for item in (*SENSORS,*BINARY_SENSORS)}
SPECIES_IMAGE_KEY='species_image'
CURRENT_KEYS=frozenset((*BY_KEY,SPECIES_IMAGE_KEY))
def is_retired_unique_id(entry_id:str,unique_id:str)->bool:
 # unique ids are f'{entry_id}_{plant_uuid}_{key}'; the uuid has no underscores,
 # so everything after it is the key, which may itself contain underscores.
 prefix=f'{entry_id}_'
 if not unique_id.startswith(prefix):return False
 _,sep,key=unique_id[len(prefix):].partition('_')
 return bool(sep) and key not in CURRENT_KEYS
PROVIDER_DEBUG_KEYS=frozenset({'provider','providers','provenance','raw','debug','trace','error','cache','generation','backoff','auth_suspended','api_key','token'})

def slug(value:str)->str:
 value=unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().casefold()
 return re.sub(r'_+','_',re.sub(r'[^a-z0-9]+','_',value)).strip('_') or 'plant'
def unique_id(entry_id:str,plant_uuid:str,key:str)->str:return f'{entry_id}_{plant_uuid}_{key}'
def suggested_entity_id(display_name:str,key:str)->str:return f'{slug(display_name)}_{key}'
def available(removing:bool,state:Mapping[str,Any],key:str)->bool:return not removing and key in state and state.get(key) not in {'unavailable'}
def attributes_for(contract:EntityContract,state:Mapping[str,Any])->dict[str,Any]:
 source=state.get(f'{contract.key}_attributes',{})
 if not isinstance(source,Mapping):return {}
 return {name:source[name] for name in contract.attributes if name in source and name not in PROVIDER_DEBUG_KEYS and source[name] is not None}
def validate_contract()->None:
 keys=[item.key for item in (*SENSORS,*BINARY_SENSORS)]
 if len(keys)!=len(set(keys)):raise ValueError('duplicate_key')
 for item in (*SENSORS,*BINARY_SENSORS):
  if set(item.attributes)&PROVIDER_DEBUG_KEYS:raise ValueError('debug_attribute')
  if item.state_class and item.state_class!='measurement':raise ValueError('state_class')
validate_contract()
