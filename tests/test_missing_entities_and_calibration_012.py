from __future__ import annotations
from pathlib import Path

from domain.entity_contract import BY_KEY, SENSORS


def test_humidity_entity_contract_is_meaningful():
    humidity = BY_KEY["humidity"]
    assert humidity in SENSORS
    assert humidity.platform == "sensor"
    assert humidity.name == "Humidity"
    assert humidity.unit == "%"
    assert humidity.device_class == "humidity"
    assert humidity.state_class == "measurement"


def test_battery_entity_contract_supports_mixed_verified_source_formats():
    battery = BY_KEY["battery"]
    assert battery in SENSORS
    assert battery.platform == "sensor"
    assert battery.name == "Battery"
    assert battery.unit is None
    assert battery.device_class is None
    assert battery.state_class is None


def test_calibration_explains_that_source_sensor_calibration_is_used():
    source = (Path(__file__).parents[1] / "custom_components" / "plant_helper" / "runtime.py").read_text()
    assert 'state["calibration"] = "source_sensor"' in source
    assert "no additional Plant Helper setup is required" in source
    calibration = BY_KEY["calibration"]
    assert calibration.attributes == ("summary",)


def test_new_entity_ids_follow_existing_contract_without_renaming_old_entities():
    keys = [item.key for item in SENSORS]
    assert "humidity" in keys
    assert "battery" in keys
    for existing in (
        "care_status",
        "moisture",
        "light",
        "temperature",
        "health",
        "calibration",
        "species_context",
    ):
        assert existing in keys
