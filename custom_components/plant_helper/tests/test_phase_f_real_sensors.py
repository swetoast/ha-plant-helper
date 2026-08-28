"""Phase F contracts based on real Home Assistant soil-sensor entities."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from plant_helper.engine.validation import MOISTURE_SPEC, battery_status, current_reading_stale
from plant_helper.plant_config import validate_plant
ROOT = Path(__file__).resolve().parents[1]
def test_real_numeric_battery_and_categorical_middle_are_supported():
    numeric = battery_status("100%")
    assert numeric.valid and not numeric.critical and numeric.percent == 100.0
    categorical = battery_status("middle")
    assert categorical.valid and not categorical.critical
    assert categorical.percent is None and categorical.level == "middle"
def test_real_moisture_values_validate_at_both_observed_levels():
    for state in ("85", "69"):
        errors = validate_plant({"name": "Plant", "soil_moisture": "sensor.soil_moisture", "profile": "balanced"}, moisture_state=state)
        assert errors == {}
def test_30_and_600_second_source_updates_are_fresh():
    now = datetime.now(timezone.utc)
    assert not current_reading_stale(now - timedelta(seconds=30), now, MOISTURE_SPEC)
    assert not current_reading_stale(now - timedelta(seconds=600), now, MOISTURE_SPEC)
def test_config_flow_keeps_real_sensor_compatibility_without_control_entities():
    source = (ROOT / "config_flow.py").read_text(encoding="utf-8")
    assert 'moisture_field: _sensor(["moisture", "humidity"])' in source
    assert '_optional(CONF_SOIL_TEMP' in source and '_sensor(["temperature"])' in source
    assert '_optional(CONF_LUX' in source and '_sensor(["illuminance"])' in source
    assert '_optional(CONF_BATTERY' in source and '_sensor()' in source
    assert '{"domain": "sensor"}' in source
def test_linked_sources_are_exposed_on_fault_diagnostic():
    coordinator = (ROOT / "coordinator.py").read_text(encoding="utf-8")
    binary = (ROOT / "binary_sensor.py").read_text(encoding="utf-8")
    assert "def linked_sources" in coordinator
    assert '{"moisture", "soil_temp", "lux", "battery"}' in coordinator
    assert '"linked_sources": self.coordinator.linked_sources(self._plant_id)' in binary
