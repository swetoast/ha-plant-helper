from __future__ import annotations

import asyncio
import copy

from domain.add_plant import AddPlantHooks, async_add_plant
from domain.runtime import RuntimeCollection
from domain.storage import PlantHelperStorage


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
