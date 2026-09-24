from __future__ import annotations
import re, pytest
from domain.config import GlobalSettings, PlantConfig, ValidationError, new_plant_uuid, replace_editable
import asyncio,copy
import pytest
from domain.add_plant import AddPlantError,AddPlantHooks,async_add_plant
from domain.runtime import RuntimeCollection
from domain.storage import PlantHelperStorage
import asyncio
import copy
from domain.add_plant import AddPlantHooks, async_add_plant
from domain.edit_plant import EditPlantError,EditPlantHooks,async_edit_plant,classify_species_change
from domain.remove_plant import RemoveHooks,RemovePlantError,async_remove_plant,async_reconcile_pending_removals
from domain.runtime import RuntimeCollection,PlantSetChange

# ---- from test_config.py ----
def test_global_minimum_and_clear():
    assert GlobalSettings.normalize({}).to_options()=={"perenual_access_level":"free","update_interval":300}
    assert GlobalSettings.normalize({"perenual_api_key":"  ","latitude":""}).to_options()=={"perenual_access_level":"free","update_interval":300}

@pytest.mark.parametrize("raw,key", [({"latitude":float("nan")},"latitude"),({"longitude":181},"longitude"),({"update_interval":True},"update_interval"),({"perenual_access_level":"x"},"perenual_access_level")])
def test_invalid_globals(raw,key):
    with pytest.raises(ValidationError) as err: GlobalSettings.normalize(raw)
    assert err.value.key==key

def test_uuid_and_indoor_outdoor_normalization():
    uid=new_plant_uuid(); assert re.fullmatch(r"[0-9a-f]{32}",uid)
    indoor=PlantConfig.normalize({"display_name":" A ","soil_moisture":"sensor.m","placement":"indoor","profile":"balanced"},plant_uuid=uid)
    assert indoor.display_name=="A" and indoor.rain_limit_mm is None
    outdoor=PlantConfig.normalize({"display_name":"A","soil_moisture":"sensor.m","placement":"outdoor","profile":"custom","custom_multiplier":1.5,"rain_limit_mm":2},plant_uuid=uid)
    assert outdoor.rain_limit_mm==2 and outdoor.custom_multiplier==1.5

def test_complete_replacement_clears_optionals():
    uid="a"*32
    old=PlantConfig.normalize({"display_name":"A","soil_moisture":"sensor.m","placement":"outdoor","profile":"custom","custom_multiplier":1,"rain_limit_mm":2,"lux":"sensor.l"},plant_uuid=uid)
    new=replace_editable(old,{"display_name":"B","soil_moisture":"sensor.m","placement":"indoor","profile":"balanced"})
    assert new.plant_uuid==uid and new.revision==2 and new.lux is None and new.rain_limit_mm is None and new.custom_multiplier is None


# ---- from test_add_plant.py ----
class add_plant_Backend:
 def __init__(self): self.data=None; self.fail=False; self.save_calls=0
 async def async_load(self): return copy.deepcopy(self.data)
 async def async_save(self,data):
  self.save_calls+=1
  if self.fail: raise OSError("save_failed")
  self.data=copy.deepcopy(data)

class add_plant_Calls:
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

def add_plant_run(coro): return asyncio.run(coro)

def add_plant_valid(**overrides):
 raw={"display_name":"Snake Plant","soil_moisture":"sensor.moisture","profile":"balanced","species":"Dracaena trifasciata"}; raw.update(overrides); return raw

def add_plant_setup():
 backend=add_plant_Backend(); storage=PlantHelperStorage(backend); add_plant_run(storage.async_load()); return backend,storage,RuntimeCollection(),add_plant_Calls()

def test_success_order_revision_entities_evaluation_enrichment_and_no_reload():
 backend,storage,runtime,calls=add_plant_setup()
 result=add_plant_run(async_add_plant(raw=add_plant_valid(),placement="indoor",storage=storage,runtime=runtime,moisture_reader=lambda _:45,hooks=calls.hooks(),uuid_factory=lambda:"a"*32))
 assert result.revision==1 and result.store_version==1 and result.reload_count==0
 assert result.listeners_registered and result.entities_requested and result.evaluated and result.enrichment_scheduled
 assert calls.items==[("listeners","a"*32),("entities","a"*32),("evaluate","a"*32),("enrichment","a"*32,"Dracaena trifasciata")]
 assert backend.data["plants"]["a"*32]["revision"]==1
 assert runtime.plants["a"*32].state["moisture"]==45

def test_outdoor_requires_and_persists_rain_limit():
 backend,storage,runtime,calls=add_plant_setup()
 result=add_plant_run(async_add_plant(raw=add_plant_valid(rain_limit_mm=2),placement="outdoor",storage=storage,runtime=runtime,moisture_reader=lambda _:0,hooks=calls.hooks(),uuid_factory=lambda:"b"*32))
 assert result.plant_uuid=="b"*32 and backend.data["plants"]["b"*32]["rain_limit_mm"]==2

def test_provider_failure_does_not_block_committed_plant():
 backend,storage,runtime,calls=add_plant_setup(); calls.enrichment_error=True
 result=add_plant_run(async_add_plant(raw=add_plant_valid(),placement="indoor",storage=storage,runtime=runtime,moisture_reader=lambda _:50,hooks=calls.hooks(),uuid_factory=lambda:"c"*32))
 assert not result.enrichment_scheduled and "c"*32 in backend.data["plants"] and "c"*32 in runtime.plants

def test_storage_failure_reports_no_success_and_no_runtime_actions():
 backend,storage,runtime,calls=add_plant_setup(); backend.fail=True
 with pytest.raises(OSError,match="save_failed"):
  add_plant_run(async_add_plant(raw=add_plant_valid(),placement="indoor",storage=storage,runtime=runtime,moisture_reader=lambda _:40,hooks=calls.hooks(),uuid_factory=lambda:"d"*32))
 assert runtime.plants=={} and calls.items==[] and backend.data is None

def test_activation_failure_keeps_persisted_authority_and_schedules_reconciliation():
 backend,storage,runtime,calls=add_plant_setup(); calls.activation_error="entities"
 result=add_plant_run(async_add_plant(raw=add_plant_valid(),placement="indoor",storage=storage,runtime=runtime,moisture_reader=lambda _:40,hooks=calls.hooks(),uuid_factory=lambda:"e"*32))
 assert "e"*32 in backend.data["plants"] and "e"*32 in runtime.plants
 assert not result.entities_requested and not result.evaluated
 assert ("reconcile","e"*32) in calls.items

@pytest.mark.parametrize("value,key",[("bad","moisture_not_numeric"),(-1,"moisture_out_of_range"),(101,"moisture_out_of_range")])
def test_bad_moisture_rejects_before_uuid_persistence(value,key):
 backend,storage,runtime,calls=add_plant_setup()
 with pytest.raises(AddPlantError) as err:
  add_plant_run(async_add_plant(raw=add_plant_valid(),placement="indoor",storage=storage,runtime=runtime,moisture_reader=lambda _:value,hooks=calls.hooks(),uuid_factory=lambda:"f"*32))
 assert err.value.key==key and backend.save_calls==0 and runtime.plants=={} and calls.items==[]

@pytest.mark.parametrize("value",[None,"unknown","unavailable"])
def test_unavailable_moisture_does_not_block_add(value):
 backend,storage,runtime,calls=add_plant_setup()
 result=add_plant_run(async_add_plant(raw=add_plant_valid(),placement="indoor",storage=storage,runtime=runtime,moisture_reader=lambda _:value,hooks=calls.hooks(),uuid_factory=lambda:"f"*32))
 assert result.plant_uuid=="f"*32 and runtime.plants["f"*32].state.get("moisture") is None

def test_no_species_means_no_enrichment_call():
 backend,storage,runtime,calls=add_plant_setup()
 result=add_plant_run(async_add_plant(raw=add_plant_valid(species=""),placement="indoor",storage=storage,runtime=runtime,moisture_reader=lambda _:30,hooks=calls.hooks(),uuid_factory=lambda:"1"*32))
 assert not result.enrichment_scheduled and all(item[0]!="enrichment" for item in calls.items)


# ---- from test_add_plant_regression_003.py ----
class MemoryBackend:
    def __init__(self):
        self.data = None

    async def async_load(self):
        return copy.deepcopy(self.data)

    async def async_save(self, data):
        self.data = copy.deepcopy(data)


async def noop(*_args, **_kwargs):
    return None


def test_real_add_form_submission_saves_with_dry_profile_and_empty_multiplier():
    async def scenario():
        backend = MemoryBackend()
        storage = PlantHelperStorage(backend)
        await storage.async_load()
        runtime = RuntimeCollection()
        raw = {
            "display_name": "Snake Plant",
            "soil_moisture": "sensor.soil_sensor_soil_moisture",
            "species": "Dracaena trifasciata",
            "soil_temperature": "sensor.soil_sensor_temperature",
            "humidity_sensor": "sensor.soil_sensor_humidity",
            "lux": "sensor.soil_sensor_illuminance",
            "battery": "sensor.soil_sensor_battery_state",
            "profile": "dry",
            "custom_multiplier": None,
        }
        result = await async_add_plant(
            raw=raw,
            placement="indoor",
            storage=storage,
            runtime=runtime,
            moisture_reader=lambda _entity_id: "38",
            hooks=AddPlantHooks(noop, noop, noop, noop, noop),
            uuid_factory=lambda: "b" * 32,
        )
        return backend, runtime, result

    backend, runtime, result = asyncio.run(scenario())
    assert result.plant_uuid == "b" * 32
    saved = backend.data["plants"]["b" * 32]
    assert saved["profile"] == "dry"
    assert saved["custom_multiplier"] is None
    assert saved["battery"] == "sensor.soil_sensor_battery_state"
    assert "b" * 32 in runtime.plants


# ---- from test_edit_plant.py ----
class edit_plant_Backend:
 def __init__(self): self.data=None; self.fail=False; self.save_calls=0
 async def async_load(self): return copy.deepcopy(self.data)
 async def async_save(self,data):
  self.save_calls+=1
  if self.fail: raise OSError("save_failed")
  self.data=copy.deepcopy(data)

class edit_plant_Calls:
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

def edit_plant_run(coro): return asyncio.run(coro)

def edit_plant_original(**overrides):
 data={"display_name":"Snake Plant","soil_moisture":"sensor.old","placement":"indoor","profile":"custom","species":"Dracaena trifasciata","lux":"sensor.lux","custom_multiplier":1.5}; data.update(overrides); return data

def edit_plant_replacement(**overrides):
 data={"display_name":"Snake Plant 2","soil_moisture":"sensor.new","profile":"balanced","species":"Dracaena trifasciata"}; data.update(overrides); return data

def edit_plant_setup(record=None):
 b=edit_plant_Backend(); st=PlantHelperStorage(b); edit_plant_run(st.async_load()); edit_plant_run(st.async_add_plant("a"*32,record or edit_plant_original())); rt=RuntimeCollection(); rt.add("a"*32,b.data["plants"]["a"*32]); return b,st,rt,edit_plant_Calls()

def test_complete_replacement_clears_optionals_stable_identity_and_no_reload():
 b,st,rt,c=edit_plant_setup()
 result=edit_plant_run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=edit_plant_replacement(),placement="indoor",storage=st,runtime=rt,moisture_reader=lambda _:55,destination_baseline_complete=True,hooks=c.hooks()))
 saved=b.data["plants"]["a"*32]
 assert result.revision==2 and result.reload_count==0 and result.runtime_generation==1
 assert saved["plant_uuid"]=="a"*32 and saved["revision"]==2
 assert saved["lux"] is None and saved["custom_multiplier"] is None and saved["rain_limit_mm"] is None
 assert rt.plants["a"*32].plant_uuid=="a"*32 and rt.plants["a"*32].state["moisture"]==55
 assert c.items==[("listeners","a"*32,"sensor.old","sensor.new"),("evaluate","a"*32)]

def test_stale_flow_has_no_write_runtime_or_listener_change():
 b,st,rt,c=edit_plant_setup(); calls=b.save_calls
 edit_plant_run(st.async_replace_plant("a"*32,1,edit_plant_original(display_name="Other")))
 with pytest.raises(EditPlantError,match="plant_changed"):
  edit_plant_run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=edit_plant_replacement(),placement="indoor",storage=st,runtime=rt,moisture_reader=lambda _:50,destination_baseline_complete=True,hooks=c.hooks()))
 assert b.save_calls==calls+1 and rt.plants["a"*32].config["revision"]==1 and c.items==[]

def test_storage_failure_preserves_runtime_and_listeners():
 b,st,rt,c=edit_plant_setup(); before=copy.deepcopy(rt.plants["a"*32].config); b.fail=True
 with pytest.raises(OSError): edit_plant_run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=edit_plant_replacement(),placement="indoor",storage=st,runtime=rt,moisture_reader=lambda _:50,destination_baseline_complete=True,hooks=c.hooks()))
 assert rt.plants["a"*32].config==before and c.items==[]

def test_placement_change_runs_after_storage_and_requests_destination_calibration():
 b,st,rt,c=edit_plant_setup()
 result=edit_plant_run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=edit_plant_replacement(rain_limit_mm=2),placement="outdoor",storage=st,runtime=rt,moisture_reader=lambda _:0,destination_baseline_complete=False,hooks=c.hooks()))
 assert result.placement.changed and result.placement.destination_requires_calibration
 assert c.items[0][0]=="listeners" and c.items[1]==("placement","a"*32,True) and c.items[2][0]=="evaluate"
 assert b.data["plants"]["a"*32]["placement"]=="outdoor"

def test_species_change_handles_identity_after_storage_and_schedules_enrichment():
 b,st,rt,c=edit_plant_setup()
 result=edit_plant_run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=edit_plant_replacement(species="Monstera deliciosa"),placement="indoor",storage=st,runtime=rt,moisture_reader=lambda _:42,destination_baseline_complete=True,hooks=c.hooks()))
 assert result.species.kind=="identity_pending" and result.enrichment_scheduled
 assert ("species","a"*32,"identity_pending") in c.items and c.items[-1]==("enrichment","a"*32,"Monstera deliciosa")

def test_species_alias_normalization_avoids_unnecessary_enrichment():
 assert classify_species_change(" Dracaena_trifasciata ","dracaena trifasciata").kind=="unchanged"

def test_edit_raw_without_species_clears_it_so_flow_must_preserve():
 # Documents the domain contract behind the options-flow fix: the edit form has
 # no species field, so if the flow does not re-inject the stored species the
 # normalized config drops it. The flow is responsible for preserving species.
 b,st,rt,c=edit_plant_setup()
 raw=edit_plant_replacement(); raw.pop("species")
 edit_plant_run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=raw,placement="indoor",storage=st,runtime=rt,moisture_reader=lambda _:42,destination_baseline_complete=True,hooks=c.hooks()))
 assert b.data["plants"]["a"*32].get("species") is None
 # And when species is supplied it round-trips unchanged.
 b2,st2,rt2,c2=edit_plant_setup()
 edit_plant_run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=edit_plant_replacement(species="Dracaena trifasciata"),placement="indoor",storage=st2,runtime=rt2,moisture_reader=lambda _:42,destination_baseline_complete=True,hooks=c2.hooks()))
 assert b2.data["plants"]["a"*32].get("species")=="Dracaena trifasciata"

def test_activation_failure_schedules_reconciliation_after_persisted_revision():
 b,st,rt,c=edit_plant_setup(); c.fail="listeners"
 result=edit_plant_run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=edit_plant_replacement(),placement="indoor",storage=st,runtime=rt,moisture_reader=lambda _:50,destination_baseline_complete=True,hooks=c.hooks()))
 assert b.data["plants"]["a"*32]["revision"]==2 and rt.plants["a"*32].generation==1
 assert not result.listeners_replaced and not result.evaluated
 assert c.items[-1]==("reconcile","a"*32)

@pytest.mark.parametrize("value,key",[("bad","moisture_not_numeric"),(101,"moisture_out_of_range")])
def test_new_moisture_source_must_be_valid_before_storage(value,key):
 b,st,rt,c=edit_plant_setup(); calls=b.save_calls
 with pytest.raises(EditPlantError) as err:
  edit_plant_run(async_edit_plant(plant_uuid="a"*32,expected_revision=1,raw=edit_plant_replacement(),placement="indoor",storage=st,runtime=rt,moisture_reader=lambda _:value,destination_baseline_complete=True,hooks=c.hooks()))
 assert err.value.key==key and b.save_calls==calls and c.items==[]


# ---- from test_remove_plant.py ----
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
def remove_plant_run(c):return asyncio.run(c)
def remove_plant_setup():
 b=B();s=PlantHelperStorage(b);remove_plant_run(s.async_load());remove_plant_run(s.async_add_plant('a',{'display_name':'A'}));remove_plant_run(s.async_add_plant('b',{'display_name':'B'}));remove_plant_run(s.async_set_learned('a','indoor',{'x':1}));remove_plant_run(s.async_set_active_samples('a',{'x':1}));r=RuntimeCollection();r.add('a',b.data['plants']['a']);r.add('b',b.data['plants']['b']);h=H();changes=[];r.subscribe(changes.append);return b,s,r,h,changes
def test_exact_order_no_cross_delete_no_reload():
 b,s,r,h,changes=remove_plant_setup();result=remove_plant_run(async_remove_plant(plant_uuid='a',expected_revision=1,storage=s,runtime=r,hooks=h.hooks()))
 assert h.calls==['tasks','listeners','evaluation','loaded_entities','entity_registry','verify_entities','device_registry','owned_state']
 assert result.completed and result.reload_count==0 and 'a' not in b.data['plants'] and 'b' in b.data['plants'] and 'b' in r.plants
 assert 'a' not in b.data['learned'] and 'a' not in b.data['active_samples'] and changes[-1].removed==frozenset({'a'})
def test_stale_revision_changes_nothing():
 b,s,r,h,_=remove_plant_setup()
 with pytest.raises(RemovePlantError,match='plant_changed'):remove_plant_run(async_remove_plant(plant_uuid='a',expected_revision=2,storage=s,runtime=r,hooks=h.hooks()))
 assert 'a' in b.data['plants'] and 'a' in r.plants and h.calls==[]
def test_entity_verification_failure_leaves_marker_for_retry():
 b,s,r,h,_=remove_plant_setup();h.entities_gone=False
 result=remove_plant_run(async_remove_plant(plant_uuid='a',expected_revision=1,storage=s,runtime=r,hooks=h.hooks()))
 assert not result.completed
 assert 'a' not in b.data['plants'] and 'a' in b.data['cleanup'];assert 'verify_entities' not in b.data['cleanup']['a']['steps']
 h.entities_gone=True;result=remove_plant_run(async_remove_plant(plant_uuid='a',expected_revision=1,storage=s,runtime=r,hooks=h.hooks(),retry=True));assert result.retried and 'a' not in b.data['cleanup']
def test_startup_reconciliation_resumes_pending_cleanup():
 b,s,r,h,_=remove_plant_setup();remove_plant_run(s.async_remove_plant('a',1));results=remove_plant_run(async_reconcile_pending_removals(storage=s,runtime=r,hooks_factory=lambda _:h.hooks()));assert results[0].retried and 'a' not in b.data['cleanup']
def test_retry_is_idempotent_for_completed_steps():
 b,s,r,h,_=remove_plant_setup();remove_plant_run(s.async_remove_plant('a',1));remove_plant_run(s.async_record_cleanup_step('a','tasks'));remove_plant_run(s.async_record_cleanup_step('a','listeners'));remove_plant_run(async_remove_plant(plant_uuid='a',expected_revision=1,storage=s,runtime=r,hooks=h.hooks(),retry=True));assert h.calls[:2]==['evaluation','loaded_entities']


# ---- from test_runtime_core.py ----
def test_load_add_update_remove_and_generations():
 changes=[]; runtime=RuntimeCollection(); runtime.subscribe(changes.append)
 runtime.load({"a":{"display_name":"A"}})
 assert changes[-1].added==frozenset({"a"}) and runtime.plants["a"].generation==0
 runtime.add("b",{"display_name":"B"})
 assert changes[-1].added==frozenset({"b"})
 plant=runtime.update("a",{"display_name":"A2"})
 assert plant.generation==1 and changes[-1].updated==frozenset({"a"})
 runtime.mark_removing("a"); assert plant.removing and plant.generation==2
 runtime.remove("a"); assert changes[-1].removed==frozenset({"a"}) and "b" in runtime.plants

def test_entity_reverse_index_and_ownership():
 runtime=RuntimeCollection(); runtime.add("a",{}); runtime.add("b",{})
 runtime.bind_entity("sensor.a","a")
 assert runtime.entity_index=={"sensor.a":"a"}
 with pytest.raises(ValueError,match="entity_owned_by_other_plant"): runtime.bind_entity("sensor.a","b")
 runtime.remove("a"); assert runtime.entity_index=={}

def test_listener_unsubscribe_and_unload():
 changes=[]; runtime=RuntimeCollection(); unsub=runtime.subscribe(changes.append)
 unsub(); runtime.add("a",{}); assert changes==[]
 runtime.unload(); assert runtime.unloaded and runtime.plants=={} and runtime.entity_index=={}
 with pytest.raises(RuntimeError,match="runtime_unloaded"): runtime.subscribe(changes.append)

def test_duplicate_missing_guards():
 runtime=RuntimeCollection(); runtime.add("a",{})
 with pytest.raises(ValueError,match="plant_exists"): runtime.add("a",{})
 with pytest.raises(KeyError): runtime.update("missing",{})
 with pytest.raises(KeyError): runtime.remove("missing")
