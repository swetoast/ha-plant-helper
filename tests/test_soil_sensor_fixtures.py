from __future__ import annotations

import json
from pathlib import Path

from domain.environment import normalize_physical_state

FIXTURES = Path(__file__).parent / "fixtures" / "soil_sensors"


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text())


def entities(snapshot: dict) -> dict[str, dict]:
    return {item["entity_id"]: item for item in snapshot["entities"]}


def test_primary_real_sensor_values_are_preserved():
    data = entities(load("soil_sensor_primary.json"))
    assert data["sensor.soil_sensor_soil_moisture"]["state"] == "36"
    assert data["sensor.soil_sensor_temperature"]["state"] == "26"
    assert data["sensor.soil_sensor_humidity"]["state"] == "43"
    assert data["sensor.soil_sensor_illuminance"]["state"] == "256"


def test_secondary_real_sensor_values_are_preserved():
    data = entities(load("soil_sensor_secondary.json"))
    assert data["sensor.soil_sensor_2_soil_moisture"]["state"] == "43"
    assert data["sensor.soil_sensor_2_temperature"]["state"] == "24.9"
    assert data["sensor.soil_sensor_2_humidity"]["state"] == "71"
    assert data["sensor.soil_sensor_2_battery"]["state"] == "100"


def test_real_numeric_values_normalize_for_runtime_ranges():
    primary = entities(load("soil_sensor_primary.json"))
    secondary = entities(load("soil_sensor_secondary.json"))
    cases = (
        (primary["sensor.soil_sensor_soil_moisture"]["state"], 0, 100, 36.0),
        (primary["sensor.soil_sensor_temperature"]["state"], -100, 200, 26.0),
        (primary["sensor.soil_sensor_humidity"]["state"], 0, 100, 43.0),
        (primary["sensor.soil_sensor_illuminance"]["state"], 0, 1000000, 256.0),
        (secondary["sensor.soil_sensor_2_battery"]["state"], 0, 100, 100.0),
    )
    for raw, minimum, maximum, expected in cases:
        result = normalize_physical_state(raw, minimum=minimum, maximum=maximum)
        assert result.status == "valid"
        assert result.value == expected


def test_categorical_battery_state_is_not_misreported_as_numeric():
    primary = entities(load("soil_sensor_primary.json"))
    result = normalize_physical_state(
        primary["sensor.soil_sensor_battery_state"]["state"],
        minimum=0,
        maximum=100,
    )
    assert result.status == "invalid"
    assert result.value is None


def test_control_entities_are_fixture_evidence_not_physical_inputs():
    for fixture in FIXTURES.glob("*.json"):
        data = load(fixture.name)
        physical = {
            item["entity_id"]
            for item in data["entities"]
            if item["entity_id"].startswith("sensor.")
            and item.get("attributes", {}).get("device_class")
            in {"battery", "humidity", "illuminance", "moisture", "temperature"}
        }
        assert not any(entity_id.startswith("number.") for entity_id in physical)
        assert not any(entity_id.startswith("select.") for entity_id in physical)


def test_fixtures_contain_no_remote_urls_or_secrets():
    for fixture in FIXTURES.glob("*.json"):
        text = fixture.read_text()
        assert "http://" not in text
        assert "https://" not in text
        assert "token" not in text.casefold()
        assert "api_key" not in text.casefold()
