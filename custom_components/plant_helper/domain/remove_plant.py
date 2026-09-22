from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Awaitable, Callable

from .runtime import RuntimeCollection
from .storage import PlantHelperStorage, PlantNotFoundError, StorageConflictError

_LOGGER = logging.getLogger(__name__)

STEPS = (
    "tasks",
    "listeners",
    "evaluation",
    "runtime",
    "platforms",
    "loaded_entities",
    "entity_registry",
    "verify_entities",
    "device_registry",
    "owned_state",
)


class RemovePlantError(RuntimeError):
    def __init__(self, key: str):
        super().__init__(key)
        self.key = key


@dataclass(slots=True)
class RemoveHooks:
    cancel_tasks: Callable[[str], Awaitable[None]]
    unsubscribe_listeners: Callable[[str], Awaitable[None]]
    block_evaluation: Callable[[str], Awaitable[None]]
    remove_loaded_entities: Callable[[str], Awaitable[None]]
    remove_entity_registry: Callable[[str], Awaitable[None]]
    verify_entities_gone: Callable[[str], Awaitable[bool]]
    remove_device_registry: Callable[[str], Awaitable[None]]
    remove_owned_state: Callable[[str], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class RemoveResult:
    plant_uuid: str
    completed: bool
    retried: bool
    reload_count: int = 0


async def _recorded_step(
    storage: PlantHelperStorage,
    plant_uuid: str,
    name: str,
    completed: set[str],
    action: Callable[[], Awaitable[None]],
) -> bool:
    if name in completed:
        return True
    try:
        await action()
        await storage.async_record_cleanup_step(plant_uuid, name)
    except Exception:
        _LOGGER.exception(
            "Plant cleanup step %s failed for %s and will be retried",
            name,
            plant_uuid,
        )
        return False
    completed.add(name)
    return True


async def async_remove_plant(
    *,
    plant_uuid: str,
    expected_revision: int,
    storage: PlantHelperStorage,
    runtime: RuntimeCollection,
    hooks: RemoveHooks,
    retry: bool = False,
) -> RemoveResult:
    """Remove durable plant data, then complete idempotent runtime cleanup.

    Once storage accepts the removal, cleanup failures must not make the UI claim
    that the plant still exists. Incomplete cleanup remains persisted and is
    retried during the next integration setup.
    """
    pending = await storage.async_pending_cleanup()
    if plant_uuid not in pending:
        try:
            await storage.async_remove_plant(plant_uuid, expected_revision)
        except StorageConflictError:
            raise RemovePlantError("plant_changed") from None
        except PlantNotFoundError:
            raise RemovePlantError("plant_not_found") from None

    pending = await storage.async_pending_cleanup()
    marker = pending.get(plant_uuid, {"steps": []})
    completed = set(marker.get("steps", []))
    all_ok = True

    all_ok &= await _recorded_step(
        storage, plant_uuid, "tasks", completed,
        lambda: hooks.cancel_tasks(plant_uuid),
    )
    all_ok &= await _recorded_step(
        storage, plant_uuid, "listeners", completed,
        lambda: hooks.unsubscribe_listeners(plant_uuid),
    )
    all_ok &= await _recorded_step(
        storage, plant_uuid, "evaluation", completed,
        lambda: hooks.block_evaluation(plant_uuid),
    )

    async def detach() -> None:
        if plant_uuid in runtime.plants:
            runtime.detach(plant_uuid)

    all_ok &= await _recorded_step(
        storage, plant_uuid, "runtime", completed, detach
    )

    async def notify_platforms() -> None:
        runtime.notify_removed(plant_uuid)

    all_ok &= await _recorded_step(
        storage, plant_uuid, "platforms", completed, notify_platforms
    )
    all_ok &= await _recorded_step(
        storage, plant_uuid, "loaded_entities", completed,
        lambda: hooks.remove_loaded_entities(plant_uuid),
    )
    all_ok &= await _recorded_step(
        storage, plant_uuid, "entity_registry", completed,
        lambda: hooks.remove_entity_registry(plant_uuid),
    )

    async def verify() -> None:
        if not await hooks.verify_entities_gone(plant_uuid):
            raise RemovePlantError("entities_remain")

    all_ok &= await _recorded_step(
        storage, plant_uuid, "verify_entities", completed, verify
    )
    all_ok &= await _recorded_step(
        storage, plant_uuid, "device_registry", completed,
        lambda: hooks.remove_device_registry(plant_uuid),
    )
    all_ok &= await _recorded_step(
        storage, plant_uuid, "owned_state", completed,
        lambda: hooks.remove_owned_state(plant_uuid),
    )

    if all_ok:
        await storage.async_finish_cleanup(plant_uuid)
    return RemoveResult(plant_uuid, all_ok, retry, 0)


async def async_reconcile_pending_removals(
    *,
    storage: PlantHelperStorage,
    runtime: RuntimeCollection,
    hooks_factory: Callable[[str], RemoveHooks],
) -> list[RemoveResult]:
    results = []
    for plant_uuid in sorted(await storage.async_pending_cleanup()):
        results.append(
            await async_remove_plant(
                plant_uuid=plant_uuid,
                expected_revision=0,
                storage=storage,
                runtime=runtime,
                hooks=hooks_factory(plant_uuid),
                retry=True,
            )
        )
    return results
