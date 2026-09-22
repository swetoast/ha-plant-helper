from __future__ import annotations
from dataclasses import dataclass
from typing import Awaitable,Callable,Any
from .runtime import RuntimeCollection
from .storage import PlantHelperStorage,StorageConflictError,PlantNotFoundError

STEPS=("tasks","listeners","evaluation","runtime","loaded_entities","entity_registry","verify_entities","device_registry","owned_state","platforms")
class RemovePlantError(RuntimeError):
 def __init__(self,key:str): super().__init__(key); self.key=key
@dataclass(slots=True)
class RemoveHooks:
 cancel_tasks:Callable[[str],Awaitable[None]]
 unsubscribe_listeners:Callable[[str],Awaitable[None]]
 block_evaluation:Callable[[str],Awaitable[None]]
 remove_loaded_entities:Callable[[str],Awaitable[None]]
 remove_entity_registry:Callable[[str],Awaitable[None]]
 verify_entities_gone:Callable[[str],Awaitable[bool]]
 remove_device_registry:Callable[[str],Awaitable[None]]
 remove_owned_state:Callable[[str],Awaitable[None]]
@dataclass(frozen=True,slots=True)
class RemoveResult:
 plant_uuid:str; completed:bool; retried:bool; reload_count:int=0
async def _step(storage,uuid,name,done,action):
 if name in done:return
 await action(); await storage.async_record_cleanup_step(uuid,name); done.add(name)
async def async_remove_plant(*,plant_uuid:str,expected_revision:int,storage:PlantHelperStorage,runtime:RuntimeCollection,hooks:RemoveHooks,retry:bool=False)->RemoveResult:
 pending=await storage.async_pending_cleanup()
 if plant_uuid not in pending:
  try: await storage.async_remove_plant(plant_uuid,expected_revision)
  except StorageConflictError: raise RemovePlantError("plant_changed") from None
  except PlantNotFoundError: raise RemovePlantError("plant_not_found") from None
 pending=await storage.async_pending_cleanup(); done=set(pending[plant_uuid].get("steps",[]))
 await _step(storage,plant_uuid,"tasks",done,lambda:hooks.cancel_tasks(plant_uuid))
 await _step(storage,plant_uuid,"listeners",done,lambda:hooks.unsubscribe_listeners(plant_uuid))
 await _step(storage,plant_uuid,"evaluation",done,lambda:hooks.block_evaluation(plant_uuid))
 async def detach():
  if plant_uuid in runtime.plants: runtime.detach(plant_uuid)
 await _step(storage,plant_uuid,"runtime",done,detach)
 await _step(storage,plant_uuid,"loaded_entities",done,lambda:hooks.remove_loaded_entities(plant_uuid))
 await _step(storage,plant_uuid,"entity_registry",done,lambda:hooks.remove_entity_registry(plant_uuid))
 async def verify():
  if not await hooks.verify_entities_gone(plant_uuid): raise RemovePlantError("entities_remain")
 await _step(storage,plant_uuid,"verify_entities",done,verify)
 await _step(storage,plant_uuid,"device_registry",done,lambda:hooks.remove_device_registry(plant_uuid))
 await _step(storage,plant_uuid,"owned_state",done,lambda:hooks.remove_owned_state(plant_uuid))
 async def notify(): runtime.notify_removed(plant_uuid)
 await _step(storage,plant_uuid,"platforms",done,notify)
 await storage.async_finish_cleanup(plant_uuid)
 return RemoveResult(plant_uuid,True,retry,0)
async def async_reconcile_pending_removals(*,storage:PlantHelperStorage,runtime:RuntimeCollection,hooks_factory:Callable[[str],RemoveHooks])->list[RemoveResult]:
 results=[]
 for uuid in sorted(await storage.async_pending_cleanup()):
  results.append(await async_remove_plant(plant_uuid=uuid,expected_revision=0,storage=storage,runtime=runtime,hooks=hooks_factory(uuid),retry=True))
 return results
