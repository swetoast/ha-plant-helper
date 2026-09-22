import asyncio,copy
import pytest
from plant_helper_domain.add_plant import AddPlantError,AddPlantHooks,async_add_plant
from plant_helper_domain.runtime import RuntimeCollection
from plant_helper_domain.storage import PlantHelperStorage

class Backend:
 def __init__(self): self.data=None; self.fail=False; self.save_calls=0
 async def async_load(self): return copy.deepcopy(self.data)
 async def async_save(self,data):
  self.save_calls+=1
  if self.fail: raise OSError("save_failed")
  self.data=copy.deepcopy(data)

class Calls:
 def __init__(self): self.items=[]; self.enrichment_error=False; self.activation_error=None
 async def listener(self,uuid,record):
  self.items.append(("listeners",uuid))
  if self.activation_error=="listeners": raise RuntimeError("listeners")
 async def entities(self,uuid):
  self.items.append(("entities",uuid))
  if self.activation_error=="entities": raise RuntimeError("entities")
 async def evaluate(self,uuid):
  self.items.append(("evaluate",uuid))
  if self.activation_error=="evaluate": raise RuntimeError("evaluate")
 async def enrich(self,uuid,species):
  self.items.append(("enrichment",uuid,species))
  if self.enrichment_error: raise RuntimeError("provider")
 async def reconcile(self,uuid): self.items.append(("reconcile",uuid))
 def hooks(self): return AddPlantHooks(self.listener,self.entities,self.evaluate,self.enrich,self.reconcile)

def run(coro): return asyncio.run(coro)

def valid(**overrides):
 raw={"display_name":"Snake Plant","soil_moisture":"sensor.moisture","profile":"balanced","species":"Dracaena trifasciata"}; raw.update(overrides); return raw

def setup():
 backend=Backend(); storage=PlantHelperStorage(backend); run(storage.async_load()); return backend,storage,RuntimeCollection(),Calls()

def test_success_order_revision_entities_evaluation_enrichment_and_no_reload():
 backend,storage,runtime,calls=setup()
 result=run(async_add_plant(raw=valid(),placement="indoor",storage=storage,runtime=runtime,moisture_reader=lambda _:45,hooks=calls.hooks(),uuid_factory=lambda:"a"*32))
 assert result.revision==1 and result.store_version==1 and result.reload_count==0
 assert result.listeners_registered and result.entities_requested and result.evaluated and result.enrichment_scheduled
 assert calls.items==[("listeners","a"*32),("entities","a"*32),("evaluate","a"*32),("enrichment","a"*32,"Dracaena trifasciata")]
 assert backend.data["plants"]["a"*32]["revision"]==1
 assert runtime.plants["a"*32].state["moisture"]==45

def test_outdoor_requires_and_persists_rain_limit():
 backend,storage,runtime,calls=setup()
 result=run(async_add_plant(raw=valid(rain_limit_mm=2),placement="outdoor",storage=storage,runtime=runtime,moisture_reader=lambda _:0,hooks=calls.hooks(),uuid_factory=lambda:"b"*32))
 assert result.plant_uuid=="b"*32 and backend.data["plants"]["b"*32]["rain_limit_mm"]==2

def test_provider_failure_does_not_block_committed_plant():
 backend,storage,runtime,calls=setup(); calls.enrichment_error=True
 result=run(async_add_plant(raw=valid(),placement="indoor",storage=storage,runtime=runtime,moisture_reader=lambda _:50,hooks=calls.hooks(),uuid_factory=lambda:"c"*32))
 assert not result.enrichment_scheduled and "c"*32 in backend.data["plants"] and "c"*32 in runtime.plants

def test_storage_failure_reports_no_success_and_no_runtime_actions():
 backend,storage,runtime,calls=setup(); backend.fail=True
 with pytest.raises(OSError,match="save_failed"):
  run(async_add_plant(raw=valid(),placement="indoor",storage=storage,runtime=runtime,moisture_reader=lambda _:40,hooks=calls.hooks(),uuid_factory=lambda:"d"*32))
 assert runtime.plants=={} and calls.items==[] and backend.data is None

def test_activation_failure_keeps_persisted_authority_and_schedules_reconciliation():
 backend,storage,runtime,calls=setup(); calls.activation_error="entities"
 with pytest.raises(RuntimeError,match="entities"):
  run(async_add_plant(raw=valid(),placement="indoor",storage=storage,runtime=runtime,moisture_reader=lambda _:40,hooks=calls.hooks(),uuid_factory=lambda:"e"*32))
 assert "e"*32 in backend.data["plants"] and "e"*32 in runtime.plants
 assert calls.items[-1]==("reconcile","e"*32)

@pytest.mark.parametrize("value,key",[(None,"moisture_not_ready"),("unknown","moisture_not_ready"),("unavailable","moisture_not_ready"),("bad","moisture_not_numeric"),(-1,"moisture_out_of_range"),(101,"moisture_out_of_range")])
def test_moisture_readiness_rejects_before_uuid_persistence(value,key):
 backend,storage,runtime,calls=setup()
 with pytest.raises(AddPlantError) as err:
  run(async_add_plant(raw=valid(),placement="indoor",storage=storage,runtime=runtime,moisture_reader=lambda _:value,hooks=calls.hooks(),uuid_factory=lambda:"f"*32))
 assert err.value.key==key and backend.save_calls==0 and runtime.plants=={} and calls.items==[]

def test_no_species_means_no_enrichment_call():
 backend,storage,runtime,calls=setup()
 result=run(async_add_plant(raw=valid(species=""),placement="indoor",storage=storage,runtime=runtime,moisture_reader=lambda _:30,hooks=calls.hooks(),uuid_factory=lambda:"1"*32))
 assert not result.enrichment_scheduled and all(item[0]!="enrichment" for item in calls.items)
