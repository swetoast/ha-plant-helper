from __future__ import annotations

import asyncio
import json
from pathlib import Path

from domain.physical import PlantPhysicalProcessor, normalize_battery_state
from domain.runtime import RuntimeCollection

ROOT = Path(__file__).parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "soil_sensors"


def fixture_entity(file_name: str, entity_id: str) -> dict:
    payload = json.loads((FIXTURES / file_name).read_text())
    return next(item for item in payload["entities"] if item["entity_id"] == entity_id)


def test_battery_selector_accepts_numeric_and_categorical_sensor_entities():
    source = (ROOT / "custom_components" / "plant_helper" / "options.py").read_text()
    battery_line = next(line for line in source.splitlines() if 'vol.Optional("battery")' in line)
    assert 'domain="sensor"' in battery_line
    assert 'device_class="battery"' not in battery_line


def test_real_soil_sensor_battery_shapes_are_normalized_without_inventing_values():
    categorical = fixture_entity(
        "soil_sensor_primary.json", "sensor.soil_sensor_battery_state"
    )
    numeric = fixture_entity(
        "soil_sensor_secondary.json", "sensor.soil_sensor_2_battery"
    )
    assert normalize_battery_state(categorical["state"]) == "middle"
    assert normalize_battery_state(numeric["state"]) == 100.0
    assert normalize_battery_state("unknown") is None
    assert normalize_battery_state("not-a-battery-state") is None


def test_categorical_battery_state_is_preserved_in_runtime():
    runtime = RuntimeCollection()
    runtime.add("plant", {"display_name": "Fixture plant"})
    evaluations = []

    async def evaluate(plant_uuid, environment):
        evaluations.append((plant_uuid, environment))

    processor = PlantPhysicalProcessor(runtime, evaluate, lambda _uuid: {})

    async def scenario():
        assert processor.accept("plant", "battery", "middle")
        await asyncio.sleep(0.4)

    asyncio.run(scenario())
    assert runtime.plants["plant"].state["battery"] == "middle"
    assert evaluations == [("plant", {})]
