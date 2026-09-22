from pathlib import Path
import json

ROOT = Path(__file__).parents[1]
INTEGRATION = ROOT / "custom_components" / "plant_helper"


def test_runtime_starts_before_platform_forwarding():
    source = (INTEGRATION / "__init__.py").read_text()
    assert source.index("async_start(hass)") < source.index("async_forward_entry_setups")


def test_physical_sources_map_to_public_entity_keys():
    source = (INTEGRATION / "domain" / "physical.py").read_text()
    assert '"soil_moisture":"moisture"' in source
    assert '"soil_temperature":"temperature"' in source
    assert '"lux":"light"' in source


def test_runtime_has_live_subscriptions_evaluation_and_cleanup():
    source = (INTEGRATION / "runtime.py").read_text()
    for required in (
        "PhysicalSubscriptions",
        "register_listeners",
        "await self.evaluate(plant_uuid)",
        "notify_updated(plant_uuid)",
        "remove_entity_registry",
        "remove_device_registry",
        "async_unload",
    ):
        assert required in source


def test_public_entity_contract_is_unchanged():
    source = (INTEGRATION / "domain" / "entity_contract.py").read_text()
    assert "('care_status','moisture','light','temperature','health','calibration','species_context')" not in source
    assert "EntityContract('sensor','care_status','Status'" in source
    assert "EntityContract('sensor','moisture','Moisture','%'" in source
    assert "EntityContract('binary_sensor','needs_attention','Needs attention'" in source


def test_patch_release_metadata_is_aligned():
    manifest = json.loads((INTEGRATION / "manifest.json").read_text())
    assert manifest["version"] == "0.0.7"
    assert "## 0.0.7 - 2026-09-22" in (ROOT / "CHANGELOG.md").read_text()
