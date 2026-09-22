import asyncio
import copy
import pytest

def async_test(function):
    def wrapper():
        return asyncio.run(function())
    wrapper.__name__ = function.__name__
    return wrapper

from plant_helper_domain.storage import (
    PlantHelperStorage, StorageConflictError, StorageError,
    PlantExistsError, PlantNotFoundError, empty_payload,
)

class MemoryBackend:
    def __init__(self, initial=None):
        self.data=copy.deepcopy(initial)
        self.fail=False
        self.save_calls=0
        self.active_saves=0
        self.max_active_saves=0

    async def async_load(self):
        return copy.deepcopy(self.data)

    async def async_save(self,data):
        self.save_calls+=1
        self.active_saves+=1
        self.max_active_saves=max(self.max_active_saves,self.active_saves)
        await asyncio.sleep(0)
        try:
            if self.fail: raise OSError("save_failed")
            self.data=copy.deepcopy(data)
        finally:
            self.active_saves-=1

@async_test
async def test_new_store_and_add():
    backend=MemoryBackend(); store=PlantHelperStorage(backend)
    snapshot=await store.async_load(); assert snapshot.version==0
    plant=await store.async_add_plant("a"*32,{"display_name":"A"})
    assert plant.revision==1 and plant.store_version==1
    assert backend.data["version"]==1 and backend.save_calls==1

@async_test
async def test_duplicate_and_missing():
    backend=MemoryBackend(); store=PlantHelperStorage(backend); await store.async_load()
    await store.async_add_plant("a",{})
    with pytest.raises(PlantExistsError): await store.async_add_plant("a",{})
    with pytest.raises(PlantNotFoundError): await store.async_get_plant("missing")
    assert backend.data["version"]==1

@async_test
async def test_stale_replace_and_remove_do_not_write():
    backend=MemoryBackend(); store=PlantHelperStorage(backend); await store.async_load()
    await store.async_add_plant("a",{"display_name":"A"})
    calls=backend.save_calls
    with pytest.raises(StorageConflictError): await store.async_replace_plant("a",2,{"display_name":"B"})
    with pytest.raises(StorageConflictError): await store.async_remove_plant("a",2)
    assert backend.save_calls==calls and backend.data["version"]==1

@async_test
async def test_replace_increments_each_revision_once():
    backend=MemoryBackend(); store=PlantHelperStorage(backend); await store.async_load()
    await store.async_add_plant("a",{})
    result=await store.async_replace_plant("a",1,{"display_name":"B"})
    assert result.revision==2 and result.store_version==2
    assert backend.data["plants"]["a"]["revision"]==2

@async_test
async def test_failed_save_keeps_memory_and_versions():
    backend=MemoryBackend(); store=PlantHelperStorage(backend); await store.async_load()
    await store.async_add_plant("a",{})
    before=await store.async_snapshot(); backend.fail=True
    with pytest.raises(OSError): await store.async_replace_plant("a",1,{"display_name":"broken"})
    after=await store.async_snapshot()
    assert after==before and backend.data["version"]==1

@async_test
async def test_concurrent_different_plants_are_serialized():
    backend=MemoryBackend(); store=PlantHelperStorage(backend); await store.async_load()
    await store.async_add_plant("a",{}); await store.async_add_plant("b",{})
    a,b=await asyncio.gather(store.async_replace_plant("a",1,{"x":1}),store.async_replace_plant("b",1,{"x":2}))
    assert {a.store_version,b.store_version}=={3,4}
    assert backend.max_active_saves==1 and backend.data["version"]==4
    assert backend.data["plants"]["a"]["x"]==1 and backend.data["plants"]["b"]["x"]==2

@async_test
async def test_species_write_does_not_change_plant_revision():
    backend=MemoryBackend(); store=PlantHelperStorage(backend); await store.async_load()
    plant=await store.async_add_plant("a",{})
    await store.async_set_species_cache("snake plant",{"status":"fresh"})
    updated=await store.async_replace_plant("a",plant.revision,{"name":"A"})
    assert updated.revision==2 and updated.store_version==3

@async_test
async def test_independent_learned_and_active_ownership():
    backend=MemoryBackend(); store=PlantHelperStorage(backend); await store.async_load()
    await store.async_add_plant("a",{})
    await store.async_set_learned("a","indoor",{"baseline":10})
    await store.async_set_learned("a","outdoor",{"baseline":20})
    await store.async_set_active_samples("a",{"placement":"indoor","samples":[1,2]})
    snap=await store.async_snapshot()
    assert snap.data["learned"]["a"]["indoor"]["baseline"]==10
    assert snap.data["learned"]["a"]["outdoor"]["baseline"]==20
    assert snap.data["active_samples"]["a"]["samples"]==[1,2]

@async_test
async def test_cleanup_markers_are_idempotent_and_reconcilable():
    backend=MemoryBackend(); store=PlantHelperStorage(backend); await store.async_load()
    await store.async_add_plant("a",{})
    await store.async_set_learned("a","indoor",{"baseline":1})
    await store.async_set_active_samples("a",{"samples":[1]})
    await store.async_remove_plant("a",1)
    await store.async_record_cleanup_step("a","entities")
    await store.async_record_cleanup_step("a","entities")
    pending=await store.async_pending_cleanup()
    assert pending["a"]["steps"]==["entities"]
    await store.async_finish_cleanup("a")
    await store.async_finish_cleanup("a")
    snap=await store.async_snapshot()
    assert "a" not in snap.data["cleanup"] and "a" not in snap.data["learned"] and "a" not in snap.data["active_samples"]

@async_test
async def test_snapshot_is_deep_copy():
    backend=MemoryBackend(); store=PlantHelperStorage(backend); await store.async_load()
    await store.async_add_plant("a",{"nested":{"x":1}})
    snap=await store.async_snapshot(); snap.data["plants"]["a"]["nested"]["x"]=9
    fresh=await store.async_snapshot(); assert fresh.data["plants"]["a"]["nested"]["x"]==1

@async_test
async def test_invalid_payload_rejected():
    invalid=empty_payload(); invalid["version"]=-1
    store=PlantHelperStorage(MemoryBackend(invalid))
    with pytest.raises(StorageError,match="invalid_version"): await store.async_load()
