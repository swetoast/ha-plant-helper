from __future__ import annotations

import asyncio
import copy
from dataclasses import dataclass
from typing import Any, Callable, Protocol

SCHEMA_VERSION = 1

class StorageError(RuntimeError):
    """Base storage failure."""

class StorageConflictError(StorageError):
    """Optimistic concurrency conflict."""

class PlantNotFoundError(StorageError):
    """Requested plant does not exist."""

class PlantExistsError(StorageError):
    """Requested plant UUID already exists."""

class StorageBackend(Protocol):
    async def async_load(self) -> dict[str, Any] | None: ...
    async def async_save(self, data: dict[str, Any]) -> None: ...

def empty_payload() -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "version": 0,
        "plants": {},
        "learned": {},
        "active_samples": {},
        "species_cache": {},
        "cleanup": {},
        "metadata": {},
    }

def _validate_payload(raw: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict): raise StorageError("invalid_store")
    if raw.get("schema_version") != SCHEMA_VERSION: raise StorageError("unsupported_schema")
    version=raw.get("version")
    if isinstance(version,bool) or not isinstance(version,int) or version < 0: raise StorageError("invalid_version")
    result=empty_payload()
    result.update(copy.deepcopy(raw))
    for key in ("plants","learned","active_samples","species_cache","cleanup","metadata"):
        if not isinstance(result.get(key),dict): raise StorageError(f"invalid_{key}")
    for plant_uuid, record in result["plants"].items():
        if not isinstance(plant_uuid,str) or not isinstance(record,dict): raise StorageError("invalid_plant")
        revision=record.get("revision")
        if isinstance(revision,bool) or not isinstance(revision,int) or revision < 1: raise StorageError("invalid_plant_revision")
    return result

@dataclass(frozen=True, slots=True)
class StorageSnapshot:
    version: int
    data: dict[str, Any]

@dataclass(frozen=True, slots=True)
class PlantSnapshot:
    store_version: int
    plant_uuid: str
    revision: int
    record: dict[str, Any]

class PlantHelperStorage:
    """Atomic Plant Helper store with top-level and per-plant revisions."""

    def __init__(self, backend: StorageBackend) -> None:
        self._backend=backend
        self._lock=asyncio.Lock()
        self._data=empty_payload()
        self._loaded=False

    @property
    def loaded(self) -> bool: return self._loaded

    async def async_load(self) -> StorageSnapshot:
        async with self._lock:
            raw=await self._backend.async_load()
            self._data=empty_payload() if raw is None else _validate_payload(raw)
            self._loaded=True
            return self._snapshot_unlocked()

    def _require_loaded(self) -> None:
        if not self._loaded: raise StorageError("not_loaded")

    def _snapshot_unlocked(self) -> StorageSnapshot:
        return StorageSnapshot(self._data["version"],copy.deepcopy(self._data))

    async def async_snapshot(self) -> StorageSnapshot:
        async with self._lock:
            self._require_loaded()
            return self._snapshot_unlocked()

    async def async_get_plant(self, plant_uuid: str) -> PlantSnapshot:
        async with self._lock:
            self._require_loaded()
            record=self._data["plants"].get(plant_uuid)
            if record is None: raise PlantNotFoundError("plant_not_found")
            return PlantSnapshot(self._data["version"],plant_uuid,record["revision"],copy.deepcopy(record))

    async def _async_commit(self, mutator: Callable[[dict[str, Any]], None]) -> StorageSnapshot:
        self._require_loaded()
        candidate=copy.deepcopy(self._data)
        mutator(candidate)
        candidate["version"]=self._data["version"]+1
        await self._backend.async_save(copy.deepcopy(candidate))
        self._data=candidate
        return self._snapshot_unlocked()

    async def async_add_plant(self, plant_uuid: str, record: dict[str, Any]) -> PlantSnapshot:
        async with self._lock:
            def mutate(data: dict[str, Any]) -> None:
                if plant_uuid in data["plants"]: raise PlantExistsError("plant_exists")
                new=copy.deepcopy(record); new["plant_uuid"]=plant_uuid; new["revision"]=1
                data["plants"][plant_uuid]=new
            snapshot=await self._async_commit(mutate)
            saved=snapshot.data["plants"][plant_uuid]
            return PlantSnapshot(snapshot.version,plant_uuid,1,saved)

    async def async_replace_plant(self, plant_uuid: str, expected_revision: int, record: dict[str, Any]) -> PlantSnapshot:
        async with self._lock:
            def mutate(data: dict[str, Any]) -> None:
                current=data["plants"].get(plant_uuid)
                if current is None: raise PlantNotFoundError("plant_not_found")
                if current["revision"] != expected_revision: raise StorageConflictError("plant_changed")
                new=copy.deepcopy(record); new["plant_uuid"]=plant_uuid; new["revision"]=expected_revision+1
                data["plants"][plant_uuid]=new
            snapshot=await self._async_commit(mutate)
            saved=snapshot.data["plants"][plant_uuid]
            return PlantSnapshot(snapshot.version,plant_uuid,saved["revision"],saved)

    async def async_remove_plant(self, plant_uuid: str, expected_revision: int) -> StorageSnapshot:
        async with self._lock:
            def mutate(data: dict[str, Any]) -> None:
                current=data["plants"].get(plant_uuid)
                if current is None: raise PlantNotFoundError("plant_not_found")
                if current["revision"] != expected_revision: raise StorageConflictError("plant_changed")
                del data["plants"][plant_uuid]
                data["cleanup"][plant_uuid]={"pending":True,"steps":[]}
            return await self._async_commit(mutate)

    async def async_set_learned(self, plant_uuid: str, placement: str, value: dict[str, Any]) -> StorageSnapshot:
        if placement not in {"indoor","outdoor"}: raise ValueError("placement")
        async with self._lock:
            return await self._async_commit(lambda data: data["learned"].setdefault(plant_uuid,{}).__setitem__(placement,copy.deepcopy(value)))

    async def async_set_active_samples(self, plant_uuid: str, value: dict[str, Any]) -> StorageSnapshot:
        async with self._lock:
            return await self._async_commit(lambda data: data["active_samples"].__setitem__(plant_uuid,copy.deepcopy(value)))

    async def async_set_species_cache(self, species_key: str, value: dict[str, Any]) -> StorageSnapshot:
        async with self._lock:
            return await self._async_commit(lambda data: data["species_cache"].__setitem__(species_key,copy.deepcopy(value)))

    async def async_record_cleanup_step(self, plant_uuid: str, step: str) -> StorageSnapshot:
        async with self._lock:
            def mutate(data: dict[str, Any]) -> None:
                marker=data["cleanup"].setdefault(plant_uuid,{"pending":True,"steps":[]})
                if step not in marker["steps"]: marker["steps"].append(step)
            return await self._async_commit(mutate)

    async def async_finish_cleanup(self, plant_uuid: str) -> StorageSnapshot:
        async with self._lock:
            def mutate(data: dict[str, Any]) -> None:
                data["cleanup"].pop(plant_uuid,None)
                data["learned"].pop(plant_uuid,None)
                data["active_samples"].pop(plant_uuid,None)
            return await self._async_commit(mutate)

    async def async_pending_cleanup(self) -> dict[str, dict[str, Any]]:
        async with self._lock:
            self._require_loaded()
            return copy.deepcopy(self._data["cleanup"])
