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
