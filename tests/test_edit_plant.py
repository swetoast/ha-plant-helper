import asyncio,copy
import pytest
from domain.edit_plant import EditPlantError,EditPlantHooks,async_edit_plant,classify_species_change
from domain.runtime import RuntimeCollection
from domain.storage import PlantHelperStorage

class Backend:
 def __init__(self): self.data=None; self.fail=False; self.save_calls=0
 async def async_load(self): return copy.deepcopy(self.data)
 async def async_save(self,data):
  self.save_calls+=1
  if self.fail: raise OSError("save_failed")
  self.data=copy.deepcopy(data)

class Calls:
 def __init__(self): self.items=[]; self.fail=None; self.enrichment_error=False
 async def listeners(self,uuid,old,new): self.items.append(("listeners",uuid,old["soil_moisture"],new["soil_moisture"])); self._fail("listeners")
 async def evaluate(self,uuid): self.items.append(("evaluate",uuid)); self._fail("evaluate")
 async def placement(self,uuid,change): self.items.append(("placement",uuid,change.destination_requires_calibration)); self._fail("placement")
 async def species(self,uuid,change): self.items.append(("species",uuid,change.kind)); self._fail("species")
 async def enrich(self,uuid,species): self.items.append(("enrichment",uuid,species));
 async def reconcile(self,uuid): self.items.append(("reconcile",uuid))
 def _fail(self,name):
  if self.fail==name: raise RuntimeError(name)
 def hooks(self): return EditPlantHooks(self.listeners,self.evaluate,self.placement,self.species,self.enrich,self.reconcile)

def run(coro): return asyncio.run(coro)

def original(**overrides):
 data={"display_name":"Snake Plant","soil_moisture":"sensor.old","placement":"indoor","profile":"custom","species":"Dracaena trifasciata","lux":"sensor.lux","custom_multiplier":1.5}; data.update(overrides); return data

def replacement(**overrides):
 data={"display_name":"Snake Plant 2","soil_moisture":"sensor.new","profile":"balanced","species":"Dracaena trifasciata"}; data.update(overrides); return data

def setup(record=None):
 b=Backend(); st=PlantHelperStorage(b); run(st.async_load()); run(st.async_add_plant("a"*32,record or original())); rt=RuntimeCollection(); rt.add("a"*32,b.data["plants"]["a"*32]); return b,st,rt,Calls()

def test_complete_replacement_clears_optionals_stable_identity_and_no_reload():
 b,st,rt,c=setup()
 result=run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=replacement(),placement="indoor",storage=st,runtime=rt,moisture_reader=lambda _:55,destination_baseline_complete=True,hooks=c.hooks()))
 saved=b.data["plants"]["a"*32]
 assert result.revision==2 and result.reload_count==0 and result.runtime_generation==1
 assert saved["plant_uuid"]=="a"*32 and saved["revision"]==2
 assert saved["lux"] is None and saved["custom_multiplier"] is None and saved["rain_limit_mm"] is None
 assert rt.plants["a"*32].plant_uuid=="a"*32 and rt.plants["a"*32].state["moisture"]==55
 assert c.items==[("listeners","a"*32,"sensor.old","sensor.new"),("evaluate","a"*32)]

def test_stale_flow_has_no_write_runtime_or_listener_change():
 b,st,rt,c=setup(); calls=b.save_calls
 run(st.async_replace_plant("a"*32,1,original(display_name="Other")))
 with pytest.raises(EditPlantError,match="plant_changed"):
  run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=replacement(),placement="indoor",storage=st,runtime=rt,moisture_reader=lambda _:50,destination_baseline_complete=True,hooks=c.hooks()))
 assert b.save_calls==calls+1 and rt.plants["a"*32].config["revision"]==1 and c.items==[]

def test_storage_failure_preserves_runtime_and_listeners():
 b,st,rt,c=setup(); before=copy.deepcopy(rt.plants["a"*32].config); b.fail=True
 with pytest.raises(OSError): run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=replacement(),placement="indoor",storage=st,runtime=rt,moisture_reader=lambda _:50,destination_baseline_complete=True,hooks=c.hooks()))
 assert rt.plants["a"*32].config==before and c.items==[]

def test_placement_change_runs_after_storage_and_requests_destination_calibration():
 b,st,rt,c=setup()
 result=run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=replacement(rain_limit_mm=2),placement="outdoor",storage=st,runtime=rt,moisture_reader=lambda _:0,destination_baseline_complete=False,hooks=c.hooks()))
 assert result.placement.changed and result.placement.destination_requires_calibration
 assert c.items[0][0]=="listeners" and c.items[1]==("placement","a"*32,True) and c.items[2][0]=="evaluate"
 assert b.data["plants"]["a"*32]["placement"]=="outdoor"

def test_species_change_handles_identity_after_storage_and_schedules_enrichment():
 b,st,rt,c=setup()
 result=run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=replacement(species="Monstera deliciosa"),placement="indoor",storage=st,runtime=rt,moisture_reader=lambda _:42,destination_baseline_complete=True,hooks=c.hooks()))
 assert result.species.kind=="identity_pending" and result.enrichment_scheduled
 assert ("species","a"*32,"identity_pending") in c.items and c.items[-1]==("enrichment","a"*32,"Monstera deliciosa")

def test_species_alias_normalization_avoids_unnecessary_enrichment():
 assert classify_species_change(" Dracaena_trifasciata ","dracaena trifasciata").kind=="unchanged"

def test_activation_failure_schedules_reconciliation_after_persisted_revision():
 b,st,rt,c=setup(); c.fail="listeners"
 with pytest.raises(RuntimeError,match="listeners"):
  run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=replacement(),placement="indoor",storage=st,runtime=rt,moisture_reader=lambda _:50,destination_baseline_complete=True,hooks=c.hooks()))
 assert b.data["plants"]["a"*32]["revision"]==2 and rt.plants["a"*32].generation==1
 assert c.items[-1]==("reconcile","a"*32)

@pytest.mark.parametrize("value,key",[(None,"moisture_not_ready"),("bad","moisture_not_numeric"),(101,"moisture_out_of_range")])
def test_new_moisture_source_must_be_valid_before_storage(value,key):
 b,st,rt,c=setup(); calls=b.save_calls
 with pytest.raises(EditPlantError) as err:
  run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=replacement(),placement="indoor",storage=st,runtime=rt,moisture_reader=lambda _:value,destination_baseline_complete=True,hooks=c.hooks()))
 assert err.value.key==key and b.save_calls==calls and c.items==[]
