"""Tests for the pure config logic (plant_config).

Proves the sensor validation the setup relies on. No Home Assistant.
Run: python3 tests/test_config_flow.py
"""

import sys
import types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if "plant_helper" not in sys.modules:
    _pkg = types.ModuleType("plant_helper")
    _pkg.__path__ = [str(_ROOT)]
    sys.modules["plant_helper"] = _pkg
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from plant_helper import plant_config as pc  # noqa: E402


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


print("== validation: required fields ==")

check("empty form -> name + moisture required",
      pc.validate_plant({}, moisture_state=None) ==
      {"name": "name_required", "soil_moisture": "moisture_required"})

base = {pc.CONF_NAME: "Fern", pc.CONF_MOISTURE: "sensor.fern_moisture", pc.CONF_PROFILE: "balanced"}
check("name + moisture provided -> valid", pc.validate_plant(base, moisture_state="42") == {})
check("moisture unavailable is not an error", pc.validate_plant(base, moisture_state="unavailable") == {})
check("moisture unknown is not an error", pc.validate_plant(base, moisture_state="unknown") == {})


print("== validation: moisture plausibility ==")

check("non-numeric moisture flagged",
      pc.validate_plant(base, moisture_state="wet")["soil_moisture"] == "moisture_not_numeric")
check("moisture > 100 flagged",
      pc.validate_plant(base, moisture_state="150")["soil_moisture"] == "moisture_out_of_range")
check("moisture < 0 flagged",
      pc.validate_plant(base, moisture_state="-5")["soil_moisture"] == "moisture_out_of_range")
check("0 and 100 are valid bounds",
      pc.validate_plant(base, moisture_state="0") == {} and pc.validate_plant(base, moisture_state="100") == {})


print("== validation: custom profile multiplier ==")

custom = {pc.CONF_NAME: "Cactus", pc.CONF_MOISTURE: "sensor.m", pc.CONF_PROFILE: "custom"}
check("custom profile without multiplier -> error",
      pc.validate_plant(custom, moisture_state="30")["custom_multiplier"] == "custom_multiplier_range")
check("custom multiplier out of range -> error",
      pc.validate_plant({**custom, pc.CONF_CUSTOM_MULTIPLIER: 1.5}, moisture_state="30")["custom_multiplier"] == "custom_multiplier_range")
check("custom multiplier 0 -> error (must be > 0)",
      pc.validate_plant({**custom, pc.CONF_CUSTOM_MULTIPLIER: 0}, moisture_state="30")["custom_multiplier"] == "custom_multiplier_range")
check("valid custom multiplier -> ok",
      pc.validate_plant({**custom, pc.CONF_CUSTOM_MULTIPLIER: 0.3}, moisture_state="30") == {})
check("non-custom profile ignores multiplier",
      pc.validate_plant(base, moisture_state="30") == {})


print("== split_record: field mapping ==")

form = {
    pc.CONF_NAME: "  Monstera  ",
    pc.CONF_SPECIES: "Monstera deliciosa",
    pc.CONF_MOISTURE: "sensor.m",
    pc.CONF_SOIL_TEMP: "sensor.t",
    pc.CONF_LUX: "sensor.l",
    pc.CONF_BATTERY: "sensor.b",
    pc.CONF_PLACEMENT: "outdoor",
    pc.CONF_PROFILE: "moisture_loving",
    pc.CONF_RAIN_LIMIT_MM: 2.0,
}
name, species, entities = pc.split_record(form)
check("name trimmed", name == "Monstera")
check("species kept", species == "Monstera deliciosa")
check("all sensors mapped", entities["soil_moisture"] == "sensor.m" and entities["lux"] == "sensor.l" and entities["battery"] == "sensor.b")
check("placement/profile/rain carried", entities["placement"] == "outdoor" and entities["profile"] == "moisture_loving" and entities["rain_limit_mm"] == 2.0)
check("no custom multiplier for non-custom profile", "custom_multiplier" not in entities)

# Species omitted -> falls back to the plant name (v4: species optional).
n2, sp2, ent2 = pc.split_record({pc.CONF_NAME: "Basil", pc.CONF_MOISTURE: "sensor.m"})
check("species falls back to name when omitted", sp2 == "Basil")
check("omitted sensors not in entities", "soil_temperature" not in ent2 and "battery" not in ent2)

# Custom profile stores the multiplier.
_, _, ent3 = pc.split_record({pc.CONF_NAME: "C", pc.CONF_MOISTURE: "sensor.m", pc.CONF_PROFILE: "custom", pc.CONF_CUSTOM_MULTIPLIER: 0.25})
check("custom profile stores multiplier as float", ent3["custom_multiplier"] == 0.25)


print("== unique_plant_id: slug + collision ==")

check("slug basic", pc.unique_plant_id(set(), "My Fern") == "my_fern")
check("collision appends suffix", pc.unique_plant_id({"my_fern"}, "My Fern") == "my_fern_2")
check("double collision", pc.unique_plant_id({"my_fern", "my_fern_2"}, "My Fern") == "my_fern_3")
check("empty name -> plant", pc.unique_plant_id(set(), "") == "plant")
check("punctuation stripped", pc.unique_plant_id(set(), "Fern (kitchen)!") == "fern_kitchen")

print("\nALL CONFIG-FLOW LOGIC TESTS PASSED")


def test_options_flow_uses_home_assistant_config_entry_property():
    """OptionsFlow must use the HA-provided config_entry property on 2025.12+."""
    import ast
    from pathlib import Path

    path = Path(__file__).parents[1] / "options.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    options = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PlantHelperOptionsFlow"
    )
    init = next(
        node for node in options.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__init__"
    )
    assert [arg.arg for arg in init.args.args] == ["self"]
    text = path.read_text(encoding="utf-8")
    assert "self._entry" not in text
    assert "self.config_entry" in text


def test_remove_plant_cleans_entity_and_device_registries():
    """Deleting a plant must not leave disabled or orphaned entity entries."""
    from pathlib import Path

    source = (Path(__file__).parents[1] / "options.py").read_text(encoding="utf-8")
    assert "entity_registry.entities.values()" in source
    assert "entity_registry.async_remove(entity.entity_id)" in source
    assert "entity.config_entry_id == self.config_entry.entry_id" in source
    assert 'unique_prefix = f"{self.config_entry.entry_id}_{plant_id}_"' in source
    assert "device_registry.async_remove_device(device.id)" in source


def _load_global_suggested_values():
    """Return the shared pure Global settings normalizer."""
    return pc.normalize_global_options

def test_global_suggested_values_accept_empty_persisted_values() -> None:
    """Empty legacy options must produce selector-safe fallbacks."""
    sanitize = _load_global_suggested_values()
    values = sanitize({"perenual_access_level": "", "update_interval": None})
    assert values["perenual_access_level"] == "free"
    assert values["update_interval"] == 300
    assert "latitude" not in values
    assert "longitude" not in values
    assert "ozone_entity" not in values


def test_global_suggested_values_sanitize_all_legacy_types() -> None:
    """Malformed saved options must never reach selector serialization."""
    sanitize = _load_global_suggested_values()
    invalid_cases = (
        None,
        [],
        {
            "latitude": "not-a-number",
            "longitude": float("inf"),
            "ozone_entity": ["sensor.ozone"],
            "perenual_api_key": 123,
            "perenual_access_level": {"value": "paid"},
            "trefle_api_key": False,
            "update_interval": float("nan"),
        },
        {
            "latitude": 91,
            "longitude": -181,
            "ozone_entity": "binary_sensor.ozone",
            "perenual_access_level": "enterprise",
            "update_interval": True,
        },
    )
    for case in invalid_cases:
        values = sanitize(case)
        assert values == {
            "perenual_access_level": "free",
            "update_interval": 300,
        }


def test_global_suggested_values_preserve_valid_values() -> None:
    """Valid settings must remain available when Global settings opens."""
    sanitize = _load_global_suggested_values()
    values = sanitize(
        {
            "latitude": "57.721035",
            "longitude": 12.939819,
            "ozone_entity": "sensor.outdoor_ozone",
            "perenual_api_key": "perenual-secret",
            "perenual_access_level": "paid",
            "trefle_api_key": "trefle-secret",
            "update_interval": "450",
        }
    )
    assert values == {
        "latitude": 57.721035,
        "longitude": 12.939819,
        "ozone_entity": "sensor.outdoor_ozone",
        "perenual_api_key": "perenual-secret",
        "perenual_access_level": "paid",
        "trefle_api_key": "trefle-secret",
        "update_interval": 450,
    }


def test_global_suggested_values_clamp_finite_interval() -> None:
    """Finite old intervals are clamped to the supported selector range."""
    sanitize = _load_global_suggested_values()
    assert sanitize({"update_interval": 0})["update_interval"] == 60
    assert sanitize({"update_interval": 99999})["update_interval"] == 3600



def test_replace_global_options_clears_omitted_optional_values() -> None:
    """Cleared optional fields must not be restored from old options."""
    existing = {
        "latitude": 57.7,
        "longitude": 12.9,
        "ozone_entity": "sensor.old_ozone",
        "perenual_api_key": "old-perenual",
        "trefle_api_key": "old-trefle",
        "perenual_access_level": "paid",
        "update_interval": 600,
        "_rev": 4,
        "unrelated_internal": "keep",
    }
    updated = pc.replace_global_options(existing, {})
    assert updated == {
        "perenual_access_level": "free",
        "update_interval": 300,
        "_rev": 5,
        "unrelated_internal": "keep",
    }


def test_next_revision_handles_malformed_legacy_values() -> None:
    """Every options operation must survive an invalid revision nonce."""
    for value in (None, "", True, False, {}, [], object(), float("inf")):
        assert pc.next_revision(value) == 1
    assert pc.next_revision(-4) == 1
    assert pc.next_revision("7") == 8
    assert pc.next_revision(11) == 12


def test_setup_and_options_share_global_normalization() -> None:
    """Initial setup and later Global settings must use the same normalizer."""
    import ast
    from pathlib import Path

    root = Path(__file__).parents[1]
    config = ast.parse((root / "config_flow.py").read_text(encoding="utf-8"))
    options = ast.parse((root / "options.py").read_text(encoding="utf-8"))
    config_calls = [
        node for node in ast.walk(config)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "normalize_global_options"
    ]
    options_calls = [
        node for node in ast.walk(options)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "normalize_global_options"
    ]
    assert config_calls
    assert options_calls


def test_storage_mutations_are_checked_before_flow_completion() -> None:
    """Add, edit, and remove must not report success after failed storage writes."""
    from pathlib import Path

    source = (Path(__file__).parents[1] / "options.py").read_text(encoding="utf-8")
    assert "stored = await storage.async_add_user_plant" in source
    assert "stored = await storage.async_update_user_plant" in source
    assert "if not await storage.async_remove_user_plant(plant_id):" in source
    assert source.count('errors["base"] = "storage_error"') == 5


def test_edit_replacement_clears_omitted_optional_entity_fields() -> None:
    """Editing a plant must remove optional selectors cleared in the form."""
    previous = {
        pc.CONF_MOISTURE: "sensor.soil",
        pc.CONF_SOIL_TEMP: "sensor.old_temperature",
        pc.CONF_HUMIDITY: "sensor.old_humidity",
        pc.CONF_LUX: "sensor.old_light",
        pc.CONF_BATTERY: "sensor.old_battery",
        pc.CONF_PLACEMENT: "indoor",
        pc.CONF_PROFILE: "balanced",
        pc.CONF_RAIN_LIMIT_MM: 1.0,
        "future_internal": "preserve",
    }
    submitted = {
        pc.CONF_NAME: "Fern",
        pc.CONF_MOISTURE: "sensor.soil",
        pc.CONF_PLACEMENT: "outdoor",
        pc.CONF_PROFILE: "balanced",
        pc.CONF_RAIN_LIMIT_MM: 2.0,
    }
    _, _, entities = pc.split_record(submitted)
    merged = {
        key: value
        for key, value in previous.items()
        if key not in pc.CONFIGURABLE_ENTITY_KEYS
    }
    merged.update(entities)
    assert merged == {
        pc.CONF_MOISTURE: "sensor.soil",
        pc.CONF_PLACEMENT: "outdoor",
        pc.CONF_PROFILE: "balanced",
        pc.CONF_RAIN_LIMIT_MM: 2.0,
        "future_internal": "preserve",
    }
