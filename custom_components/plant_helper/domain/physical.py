from __future__ import annotations
import asyncio
from dataclasses import dataclass,field
from typing import Any,Awaitable,Callable,Mapping
from .environment import normalize_physical_state
from .runtime import RuntimeCollection

DEBOUNCE_SECONDS=0.350
TOLERANCES={"soil_moisture":0.1,"soil_temperature":0.1,"humidity_sensor":0.1,"lux":1.0,"battery":1.0}
RANGES={"soil_moisture":(0,100),"soil_temperature":(-100,200),"humidity_sensor":(0,100),"lux":(0,1000000),"battery":(0,100)}
STATE_KEYS={"soil_moisture":"moisture","soil_temperature":"temperature","humidity_sensor":"humidity","lux":"light","battery":"battery"}
BATTERY_STATES=frozenset({"low","middle","high"})

def normalize_battery_state(raw:Any)->float|str|None:
 if isinstance(raw,str):
  state=raw.strip().casefold()
  if state in {"unknown","unavailable","none",""}:return None
  if state in BATTERY_STATES:return state
 normalized=normalize_physical_state(raw,minimum=0,maximum=100)
 return normalized.value if normalized.status=="valid" else None

@dataclass(frozen=True,slots=True)
class PhysicalChange:
 plant_uuid:str; source_key:str; old_value:float|str|None; new_value:float|str|None; generation:int
@dataclass(slots=True)
class PlantPhysicalProcessor:
 runtime:RuntimeCollection
 evaluate:Callable[[str,Mapping[str,Any]],Awaitable[None]]
 cached_environment:Callable[[str],Mapping[str,Any]]
 external_call_count:int=0
 _values:dict[tuple[str,str],float|str|None]=field(default_factory=dict)
 _tasks:dict[str,asyncio.Task[None]]=field(default_factory=dict)
 _blocked:set[str]=field(default_factory=set)

 def material_change(self,key:str,old:float|str|None,new:float|str|None)->bool:
  if old is None or new is None:return old!=new
  if isinstance(old,str) or isinstance(new,str):return old!=new
  return abs(new-old)>=TOLERANCES.get(key,0.0)
 def accept(self,plant_uuid:str,key:str,raw:Any)->bool:
  plant=self.runtime.plants.get(plant_uuid)
  if plant is None or plant.removing or plant_uuid in self._blocked:return False
  if key=="battery":
   value=normalize_battery_state(raw)
  else:
   minimum,maximum=RANGES[key]
   normalized=normalize_physical_state(raw,minimum=minimum,maximum=maximum)
   value=normalized.value if normalized.status=="valid" else None
  token=(plant_uuid,key);old=self._values.get(token)
  if token in self._values and not self.material_change(key,old,value):return False
  self._values[token]=value;plant.state[key]=value;plant.state[STATE_KEYS[key]]=value
  generation=plant.generation
  previous=self._tasks.pop(plant_uuid,None)
  if previous is not None:previous.cancel()
  self._tasks[plant_uuid]=asyncio.create_task(self._debounced(plant_uuid,generation))
  return True
 async def _debounced(self,plant_uuid:str,generation:int)->None:
  try:await asyncio.sleep(DEBOUNCE_SECONDS)
  except asyncio.CancelledError:return
  plant=self.runtime.plants.get(plant_uuid)
  if plant is None or plant.removing or plant.generation!=generation or plant_uuid in self._blocked:return
  await self.evaluate(plant_uuid,self.cached_environment(plant_uuid))
  self._tasks.pop(plant_uuid,None)
 def block(self,plant_uuid:str)->None:
  self._blocked.add(plant_uuid);task=self._tasks.pop(plant_uuid,None)
  if task is not None:task.cancel()
 def unblock(self,plant_uuid:str)->None:self._blocked.discard(plant_uuid)
 def unload_plant(self,plant_uuid:str)->None:
  self.block(plant_uuid)
  for token in tuple(self._values):
   if token[0]==plant_uuid:del self._values[token]
 def unload(self)->None:
  for task in tuple(self._tasks.values()):task.cancel()
  self._tasks.clear();self._values.clear();self._blocked.clear()
