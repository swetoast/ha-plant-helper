from pathlib import Path

ROOT = Path(__file__).parents[2] / "custom_components" / "plant_helper"


def test_new_entities_are_not_written_before_home_assistant_attaches_them():
    for platform in ("sensor.py", "binary_sensor.py"):
        source = (ROOT / platform).read_text()
        assert "if entity.hass is not None:" in source
        assert source.index("if entity.hass is not None:") < source.index(
            "entity.async_write_ha_state()"
        )


def test_add_form_filters_required_physical_sensor_classes():
    source = (ROOT / "options.py").read_text()
    assert 'domain="sensor",device_class="moisture"' in source
    battery_line = next(line for line in source.splitlines() if 'vol.Optional("battery")' in line)
    assert 'domain="sensor"' in battery_line
    assert 'device_class="battery"' not in battery_line
