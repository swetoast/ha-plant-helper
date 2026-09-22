import asyncio,copy
import pytest
from plant_helper_domain.remove_plant import RemoveHooks,RemovePlantError,async_remove_plant,async_reconcile_pending_removals
from plant_helper_domain.runtime import RuntimeCollection
from plant_helper_domain.storage import PlantHelperStorage
class B:
 def __init__(self):self.data=None
 async def async_load(self):return copy.deepcopy(self.data)
 async def async_save(self,d):self.data=copy.deepcopy(d)
class H:
 def __init__(self):self.calls=[];self.fail=None;self.entities_gone=True
 async def x(self,name,u):self.calls.append(name); 
 async def tasks(self,u):await self.x('tasks',u)
 async def listeners(self,u):await self.x('listeners',u)
 async def evaluation(self,u):await self.x('evaluation',u)
 async def loaded(self,u):await self.x('loaded_entities',u)
 async def entities(self,u):await self.x('entity_registry',u)
 async def verify(self,u):self.calls.append('verify_entities');return self.entities_gone
 async def device(self,u):await self.x('device_registry',u)
 async def owned(self,u):await self.x('owned_state',u)
 def hooks(self):return RemoveHooks(self.tasks,self.listeners,self.evaluation,self.loaded,self.entities,self.verify,self.device,self.owned)
def run(c):return asyncio.run(c)
def setup():
 b=B();s=PlantHelperStorage(b);run(s.async_load());run(s.async_add_plant('a',{'display_name':'A'}));run(s.async_add_plant('b',{'display_name':'B'}));run(s.async_set_learned('a','indoor',{'x':1}));run(s.async_set_active_samples('a',{'x':1}));r=RuntimeCollection();r.add('a',b.data['plants']['a']);r.add('b',b.data['plants']['b']);h=H();changes=[];r.subscribe(changes.append);return b,s,r,h,changes
def test_exact_order_no_cross_delete_no_reload():
 b,s,r,h,changes=setup();result=run(async_remove_plant(plant_uuid='a',expected_revision=1,storage=s,runtime=r,hooks=h.hooks()))
 assert h.calls==['tasks','listeners','evaluation','loaded_entities','entity_registry','verify_entities','device_registry','owned_state']
 assert result.completed and result.reload_count==0 and 'a' not in b.data['plants'] and 'b' in b.data['plants'] and 'b' in r.plants
 assert 'a' not in b.data['learned'] and 'a' not in b.data['active_samples'] and changes[-1].removed==frozenset({'a'})
def test_stale_revision_changes_nothing():
 b,s,r,h,_=setup()
 with pytest.raises(RemovePlantError,match='plant_changed'):run(async_remove_plant(plant_uuid='a',expected_revision=2,storage=s,runtime=r,hooks=h.hooks()))
 assert 'a' in b.data['plants'] and 'a' in r.plants and h.calls==[]
def test_entity_verification_failure_leaves_marker_for_retry():
 b,s,r,h,_=setup();h.entities_gone=False
 with pytest.raises(RemovePlantError,match='entities_remain'):run(async_remove_plant(plant_uuid='a',expected_revision=1,storage=s,runtime=r,hooks=h.hooks()))
 assert 'a' not in b.data['plants'] and 'a' in b.data['cleanup'];assert b.data['cleanup']['a']['steps']==['tasks','listeners','evaluation','runtime','loaded_entities','entity_registry']
 h.entities_gone=True;result=run(async_remove_plant(plant_uuid='a',expected_revision=1,storage=s,runtime=r,hooks=h.hooks(),retry=True));assert result.retried and 'a' not in b.data['cleanup']
def test_startup_reconciliation_resumes_pending_cleanup():
 b,s,r,h,_=setup();run(s.async_remove_plant('a',1));results=run(async_reconcile_pending_removals(storage=s,runtime=r,hooks_factory=lambda _:h.hooks()));assert results[0].retried and 'a' not in b.data['cleanup']
def test_retry_is_idempotent_for_completed_steps():
 b,s,r,h,_=setup();run(s.async_remove_plant('a',1));run(s.async_record_cleanup_step('a','tasks'));run(s.async_record_cleanup_step('a','listeners'));run(async_remove_plant(plant_uuid='a',expected_revision=1,storage=s,runtime=r,hooks=h.hooks(),retry=True));assert h.calls[:2]==['evaluation','loaded_entities']
