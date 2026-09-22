import asyncio
from plant_helper_domain.physical import PlantPhysicalProcessor,DEBOUNCE_SECONDS
from plant_helper_domain.runtime import RuntimeCollection
async def wait():await asyncio.sleep(DEBOUNCE_SECONDS+0.05)
def run(c):return asyncio.run(c)
def setup():
 runtime=RuntimeCollection();runtime.add('a',{'revision':1});calls=[]
 async def evaluate(uuid,env):calls.append((uuid,dict(env),dict(runtime.plants[uuid].state)))
 processor=PlantPhysicalProcessor(runtime,evaluate,lambda uuid:{'weather':'cached','air':'cached'})
 return runtime,processor,calls
def test_immediate_local_state_and_debounced_cached_evaluation_zero_external_calls():
 async def scenario():
  runtime,p,calls=setup();assert p.accept('a','soil_moisture',40);assert runtime.plants['a'].state['soil_moisture']==40;assert calls==[];await wait();assert len(calls)==1 and calls[0][1]=={'weather':'cached','air':'cached'} and p.external_call_count==0
 run(scenario())
def test_fixed_debounce_coalesces_burst_to_latest_values():
 async def scenario():
  runtime,p,calls=setup();p.accept('a','soil_moisture',40);await asyncio.sleep(.1);p.accept('a','soil_moisture',41);await asyncio.sleep(.1);p.accept('a','lux',100);await wait();assert len(calls)==1;assert calls[0][2]['soil_moisture']==41 and calls[0][2]['lux']==100
 run(scenario())
def test_material_change_filtering():
 async def scenario():
  runtime,p,calls=setup();assert p.accept('a','soil_moisture',40);assert not p.accept('a','soil_moisture',40.05);assert p.accept('a','soil_moisture',40.1);assert p.accept('a','lux',100);assert not p.accept('a','lux',100.5);assert p.accept('a','lux',101);await wait();assert len(calls)==1
 run(scenario())
def test_generation_change_discards_stale_debounce():
 async def scenario():
  runtime,p,calls=setup();p.accept('a','soil_moisture',40);runtime.update('a',{'revision':2});await wait();assert calls==[]
 run(scenario())
def test_block_and_unload_cancel_pending_evaluation():
 async def scenario():
  runtime,p,calls=setup();p.accept('a','soil_moisture',40);p.block('a');await wait();assert calls==[];p.unblock('a');p.accept('a','soil_moisture',41);p.unload_plant('a');await wait();assert calls==[] and all(k[0]!='a' for k in p._values)
 run(scenario())
def test_unavailable_transition_is_material_once():
 async def scenario():
  runtime,p,calls=setup();assert p.accept('a','battery',80);assert p.accept('a','battery','unavailable');assert not p.accept('a','battery','unknown');await wait();assert len(calls)==1 and runtime.plants['a'].state['battery'] is None
 run(scenario())
