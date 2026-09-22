from __future__ import annotations
from dataclasses import dataclass,field
from typing import Any,Mapping
from .placement import decide_placement_transition,PlacementTransition
from .species import normalize_species_key
from .storage import PlantHelperStorage

@dataclass(frozen=True,slots=True)
class LearningState:
 placement:str; baseline:dict[str,Any]; active_samples:dict[str,Any]; calibrating:bool
@dataclass(frozen=True,slots=True)
class SpeciesLearningChange:
 kind:str; preserve_baselines:bool; clear_active_samples:bool
@dataclass(slots=True)
class LearningRuntime:
 storage:PlantHelperStorage
 baselines:dict[str,dict[str,dict[str,Any]]]=field(default_factory=dict)
 active_samples:dict[str,dict[str,Any]]=field(default_factory=dict)
 placement:dict[str,str]=field(default_factory=dict)
 calibrating:set[str]=field(default_factory=set)

 async def load(self)->None:
  snapshot=await self.storage.async_snapshot();data=snapshot.data
  self.baselines={u:{p:dict(v) for p,v in placements.items()} for u,placements in data['learned'].items()}
  self.active_samples={u:dict(v) for u,v in data['active_samples'].items()}
  for uuid,record in data['plants'].items():
   self.placement[uuid]=record.get('placement','indoor')
   baseline=self.baselines.get(uuid,{}).get(self.placement[uuid],{})
   if not baseline.get('complete',False):self.calibrating.add(uuid)
 def state(self,uuid:str)->LearningState:
  placement=self.placement[uuid];baseline=dict(self.baselines.get(uuid,{}).get(placement,{}));samples=dict(self.active_samples.get(uuid,{}))
  return LearningState(placement,baseline,samples,uuid in self.calibrating)
 async def set_baseline(self,uuid:str,placement:str,value:Mapping[str,Any])->None:
  baseline=dict(value);self.baselines.setdefault(uuid,{})[placement]=baseline
  await self.storage.async_set_learned(uuid,placement,baseline)
  if self.placement.get(uuid)==placement and baseline.get('complete',False):self.calibrating.discard(uuid)
 async def set_active_samples(self,uuid:str,value:Mapping[str,Any])->None:
  samples=dict(value);self.active_samples[uuid]=samples;await self.storage.async_set_active_samples(uuid,samples)
 async def transition(self,uuid:str,destination:str)->PlacementTransition:
  current=self.placement[uuid];destination_complete=self.baselines.get(uuid,{}).get(destination,{}).get('complete',False)
  change=decide_placement_transition(current,destination,destination_baseline_complete=destination_complete)
  if not change.changed:return change
  self.placement[uuid]=destination
  self.active_samples[uuid]={};await self.storage.async_set_active_samples(uuid,{})
  if change.destination_requires_calibration:self.calibrating.add(uuid)
  else:self.calibrating.discard(uuid)
  return change
 def resume_calibration(self,uuid:str)->bool:
  placement=self.placement[uuid];complete=self.baselines.get(uuid,{}).get(placement,{}).get('complete',False)
  if complete:self.calibrating.discard(uuid);return False
  self.calibrating.add(uuid);return True
 async def species_change(self,uuid:str,old_species:str|None,new_species:str|None)->SpeciesLearningChange:
  old=normalize_species_key(old_species or '');new=normalize_species_key(new_species or '')
  if old==new:return SpeciesLearningChange('alias',True,False)
  self.baselines.pop(uuid,None);self.active_samples[uuid]={};self.calibrating.add(uuid)
  await self.storage.async_set_learned(uuid,'indoor',{})
  await self.storage.async_set_learned(uuid,'outdoor',{})
  await self.storage.async_set_active_samples(uuid,{})
  return SpeciesLearningChange('different_taxon',False,True)
