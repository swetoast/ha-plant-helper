import asyncio
from domain.physical import PlantPhysicalProcessor,DEBOUNCE_SECONDS
from domain.runtime import RuntimeCollection
import pytest
from domain.placement import decide_placement_transition
from domain.storage_revision import check_plant_revision,next_revisions,StorageConflictError
import asyncio,copy
from domain.learning import LearningRuntime
from domain.storage import PlantHelperStorage

# ---- from test_physical.py ----
async def wait():await asyncio.sleep(DEBOUNCE_SECONDS+0.05)
def physical_run(c):return asyncio.run(c)
def physical_setup():
 runtime=RuntimeCollection();runtime.add('a',{'revision':1});calls=[]
 async def evaluate(uuid,env):calls.append((uuid,dict(env),dict(runtime.plants[uuid].state)))
 processor=PlantPhysicalProcessor(runtime,evaluate,lambda uuid:{'weather':'cached','air':'cached'})
 return runtime,processor,calls
def test_immediate_local_state_and_debounced_cached_evaluation_zero_external_calls():
 async def scenario():
  runtime,p,calls=physical_setup();assert p.accept('a','soil_moisture',40);assert runtime.plants['a'].state['soil_moisture']==40;assert calls==[];await wait();assert len(calls)==1 and calls[0][1]=={'weather':'cached','air':'cached'} and p.external_call_count==0
 physical_run(scenario())
def test_fixed_debounce_coalesces_burst_to_latest_values():
 async def scenario():
  runtime,p,calls=physical_setup();p.accept('a','soil_moisture',40);await asyncio.sleep(.1);p.accept('a','soil_moisture',41);await asyncio.sleep(.1);p.accept('a','lux',100);await wait();assert len(calls)==1;assert calls[0][2]['soil_moisture']==41 and calls[0][2]['lux']==100
 physical_run(scenario())
def test_material_change_filtering():
 async def scenario():
  runtime,p,calls=physical_setup();assert p.accept('a','soil_moisture',40);assert not p.accept('a','soil_moisture',40.05);assert p.accept('a','soil_moisture',40.1);assert p.accept('a','lux',100);assert not p.accept('a','lux',100.5);assert p.accept('a','lux',101);await wait();assert len(calls)==1
 physical_run(scenario())
def test_generation_change_discards_stale_debounce():
 async def scenario():
  runtime,p,calls=physical_setup();p.accept('a','soil_moisture',40);runtime.update('a',{'revision':2});await wait();assert calls==[]
 physical_run(scenario())
def test_block_and_unload_cancel_pending_evaluation():
 async def scenario():
  runtime,p,calls=physical_setup();p.accept('a','soil_moisture',40);p.block('a');await wait();assert calls==[];p.unblock('a');p.accept('a','soil_moisture',41);p.unload_plant('a');await wait();assert calls==[] and all(k[0]!='a' for k in p._values)
 physical_run(scenario())
def test_unavailable_transition_is_material_once():
 async def scenario():
  runtime,p,calls=physical_setup();assert p.accept('a','battery',80);assert p.accept('a','battery','unavailable');assert not p.accept('a','battery','unknown');await wait();assert len(calls)==1 and runtime.plants['a'].state['battery'] is None
 physical_run(scenario())


# ---- from test_placement_storage.py ----
def test_placement_transition_preserves_baselines():
    result=decide_placement_transition("indoor","outdoor",destination_baseline_complete=False)
    assert result.changed and result.clear_active_samples and result.preserve_indoor_baseline and result.preserve_outdoor_baseline and result.destination_requires_calibration

def test_no_transition():
    result=decide_placement_transition("indoor","indoor",destination_baseline_complete=False)
    assert not result.changed and not result.clear_active_samples and not result.destination_requires_calibration

def test_revisions():
    check_plant_revision(2,2)
    with pytest.raises(StorageConflictError): check_plant_revision(3,2)
    assert next_revisions(4,7)==(5,8)


# ---- from test_learning.py ----
class B:
 def __init__(self,data=None):self.data=copy.deepcopy(data)
 async def async_load(self):return copy.deepcopy(self.data)
 async def async_save(self,d):self.data=copy.deepcopy(d)
def learning_run(c):return asyncio.run(c)
def learning_setup():
 b=B();s=PlantHelperStorage(b);learning_run(s.async_load());learning_run(s.async_add_plant('a',{'display_name':'A','placement':'indoor'}));l=LearningRuntime(s);learning_run(l.load());return b,s,l
def test_independent_baselines_and_active_buffer():
 b,s,l=learning_setup();learning_run(l.set_baseline('a','indoor',{'complete':True,'mean':44}));learning_run(l.set_baseline('a','outdoor',{'complete':True,'mean':61}));learning_run(l.set_active_samples('a',{'values':[42,43]}))
 assert l.baselines['a']['indoor']['mean']==44 and l.baselines['a']['outdoor']['mean']==61 and l.active_samples['a']['values']==[42,43]
def test_transition_preserves_inactive_baselines_and_clears_only_active_state():
 b,s,l=learning_setup();learning_run(l.set_baseline('a','indoor',{'complete':True,'mean':44}));learning_run(l.set_baseline('a','outdoor',{'complete':True,'mean':61}));learning_run(l.set_active_samples('a',{'values':[42]}));change=learning_run(l.transition('a','outdoor'))
 assert change.changed and change.clear_active_samples and not change.destination_requires_calibration
 assert l.baselines['a']['indoor']['mean']==44 and l.baselines['a']['outdoor']['mean']==61 and l.active_samples['a']=={} and not l.state('a').calibrating
def test_transition_to_incomplete_destination_resumes_calibration():
 b,s,l=learning_setup();learning_run(l.set_baseline('a','indoor',{'complete':True}));change=learning_run(l.transition('a','outdoor'));assert change.destination_requires_calibration and l.state('a').calibrating
 assert l.resume_calibration('a')
def test_species_alias_preserves_learning():
 b,s,l=learning_setup();learning_run(l.set_baseline('a','indoor',{'complete':True,'mean':44}));learning_run(l.set_active_samples('a',{'values':[42]}));change=learning_run(l.species_change('a','Dracaena_trifasciata',' dracaena trifasciata '))
 assert change.kind=='alias' and change.preserve_baselines and l.baselines['a']['indoor']['mean']==44 and l.active_samples['a']['values']==[42]
def test_different_taxon_clears_both_baselines_and_active_buffer():
 b,s,l=learning_setup();learning_run(l.set_baseline('a','indoor',{'complete':True}));learning_run(l.set_baseline('a','outdoor',{'complete':True}));learning_run(l.set_active_samples('a',{'values':[1]}));change=learning_run(l.species_change('a','Dracaena trifasciata','Monstera deliciosa'))
 assert change.kind=='different_taxon' and not change.preserve_baselines and change.clear_active_samples
 assert l.baselines.get('a') is None and l.active_samples['a']=={} and l.state('a').calibrating
def test_persistence_across_restart():
 b,s,l=learning_setup();learning_run(l.set_baseline('a','indoor',{'complete':True,'mean':44}));learning_run(l.set_baseline('a','outdoor',{'complete':False,'values':[60]}));learning_run(l.set_active_samples('a',{'values':[42,43]}))
 s2=PlantHelperStorage(B(b.data));learning_run(s2.async_load());l2=LearningRuntime(s2);learning_run(l2.load())
 assert l2.baselines['a']['indoor']['mean']==44 and l2.baselines['a']['outdoor']['values']==[60] and l2.active_samples['a']['values']==[42,43] and not l2.state('a').calibrating
