from pathlib import Path
import json

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "plant_helper"


def test_platforms_reconcile_existing_plants_directly():
    for name, key in (("sensor.py", "sensor"), ("binary_sensor.py", "binary_sensor")):
        source = (INTEGRATION / name).read_text()
        assert 'for plant_uuid in sorted(runtime.plants.plants):' in source
        assert 'ensure_plant(plant_uuid)' in source
        assert f'runtime.platform_callbacks["{key}"] = ensure_plant' in source


def test_add_flow_explicitly_requests_both_loaded_platforms():
    source = (INTEGRATION / "options.py").read_text()
    assert 'for platform in ("sensor", "binary_sensor"):' in source
    assert 'callback = runtime.platform_callbacks.get(platform)' in source
    assert 'callback(plant_uuid)' in source


def test_entity_creation_is_idempotent():
    for name in ("sensor.py", "binary_sensor.py"):
        source = (INTEGRATION / name).read_text()
        assert 'if plant_uuid in known:' in source
        assert 'known.add(plant_uuid)' in source


def test_release_version_is_current():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    assert manifest["version"] == "0.0.13"
    assert "## 0.0.13 - 2026-09-22" in (ROOT / "CHANGELOG.md").read_text()
