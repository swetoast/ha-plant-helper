from __future__ import annotations

import asyncio
import copy

from domain.remove_plant import RemoveHooks, async_reconcile_pending_removals, async_remove_plant
from domain.runtime import RuntimeCollection
from domain.storage import PlantHelperStorage


class Backend:
    def __init__(self):
        self.data = None

    async def async_load(self):
        return copy.deepcopy(self.data)

    async def async_save(self, data):
        self.data = copy.deepcopy(data)


class Cleanup:
    def __init__(self, fail_once: str | None = None):
        self.calls = []
        self.fail_once = fail_once

    async def step(self, name: str, plant_uuid: str):
        self.calls.append((name, plant_uuid))
        if self.fail_once == name:
            self.fail_once = None
            raise RuntimeError(name)

    async def verify(self, plant_uuid: str) -> bool:
        await self.step("verify_entities", plant_uuid)
        return True

    def hooks(self):
        return RemoveHooks(
            lambda uuid: self.step("tasks", uuid),
            lambda uuid: self.step("listeners", uuid),
            lambda uuid: self.step("evaluation", uuid),
            lambda uuid: self.step("loaded_entities", uuid),
            lambda uuid: self.step("entity_registry", uuid),
            self.verify,
            lambda uuid: self.step("device_registry", uuid),
            lambda uuid: self.step("owned_state", uuid),
        )


def run(awaitable):
    return asyncio.run(awaitable)


def setup():
    backend = Backend()
    storage = PlantHelperStorage(backend)
    run(storage.async_load())
    record = {
        "plant_uuid": "a" * 32,
        "revision": 1,
        "display_name": "Fixture plant",
        "placement": "indoor",
        "soil_moisture": "sensor.fixture_moisture",
        "species": None,
        "soil_temperature": None,
        "humidity_sensor": None,
        "lux": None,
        "battery": None,
        "profile": "balanced",
        "custom_multiplier": None,
        "rain_limit_mm": None,
    }
    run(storage.async_add_plant("a" * 32, record))
    runtime = RuntimeCollection()
    runtime.add("a" * 32, record)
    return backend, storage, runtime


def test_durable_remove_is_successful_even_when_cleanup_needs_retry():
    backend, storage, runtime = setup()
    cleanup = Cleanup(fail_once="entity_registry")
    result = run(async_remove_plant(
        plant_uuid="a" * 32,
        expected_revision=1,
        storage=storage,
        runtime=runtime,
        hooks=cleanup.hooks(),
    ))
    assert not result.completed
    assert "a" * 32 not in backend.data["plants"]
    assert "a" * 32 not in runtime.plants
    assert "a" * 32 in backend.data["cleanup"]


def test_pending_cleanup_retries_on_setup_and_finishes_marker():
    backend, storage, runtime = setup()
    first = Cleanup(fail_once="entity_registry")
    run(async_remove_plant(
        plant_uuid="a" * 32,
        expected_revision=1,
        storage=storage,
        runtime=runtime,
        hooks=first.hooks(),
    ))
    retry = Cleanup()
    results = run(async_reconcile_pending_removals(
        storage=storage,
        runtime=runtime,
        hooks_factory=lambda _uuid: retry.hooks(),
    ))
    assert results[0].completed and results[0].retried
    assert backend.data["cleanup"] == {}
    assert any(name == "entity_registry" for name, _uuid in retry.calls)
