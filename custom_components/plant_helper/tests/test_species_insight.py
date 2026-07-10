"""Tests for the species-insight layer (pure). Run: python3 tests/test_species_insight.py"""

import sys, types
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if "plant_helper" not in sys.modules:
    _pkg = types.ModuleType("plant_helper"); _pkg.__path__ = [str(_ROOT)]
    sys.modules["plant_helper"] = _pkg
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from plant_helper import enrichment as en  # noqa: E402


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


rich = {
    "watering": "Minimum", "sunlight": ["full_sun"], "care_level": "Easy",
    "drought_tolerant": True, "soil_moisture_pref_0_10": 3, "light_requirement_0_10": 8,
    "reference_watering_days": 14.0, "min_temperature_c": 10, "description": "x",
    "suggested_profile": "dry_tolerant", "source": "perenual, inaturalist, trefle",
}

print("== data quality ==")
check("rich multi-provider -> high", en.species_data_quality(rich) == "high")
check("empty -> none", en.species_data_quality({}) == "none")
check("thin single field -> low", en.species_data_quality({"watering": "Average", "source": "inaturalist"}) == "low")
check("mid -> medium", en.species_data_quality({"watering": "Average", "care_level": "Easy", "sunlight": ["x"], "source": "perenual, inaturalist"}) == "medium")

print("== light preference ==")
check("trefle 8 -> full_sun", en.light_preference({"light_requirement_0_10": 8}) == "full_sun")
check("trefle 5 -> bright_indirect", en.light_preference({"light_requirement_0_10": 5}) == "bright_indirect")
check("trefle 2 -> low_light", en.light_preference({"light_requirement_0_10": 2}) == "low_light")
check("perenual part shade -> bright_indirect", en.light_preference({"sunlight": ["part shade"]}) == "bright_indirect")
check("no light data -> None", en.light_preference({}) is None)

print("== calibrating: everything pending, hint explains (not suppresses) ==")
ins = en.species_insight(rich, calibrating=True)
check("comparison calibrating", ins["watering_interval_comparison"] == "calibrating")
check("fit pending", ins["baseline_species_fit"] == "pending")
check("learned interval None during calibration", ins["learned_watering_interval_days"] is None)
check("reference passed through", ins["provider_reference_watering_days"] == 14.0)
check("dry-tolerant hint present + explanatory", "drought-tolerant" in ins["calibration_hint"] and "still fire" in ins["calibration_hint"])
check("data quality high", ins["species_data_quality"] == "high")

print("== no species data: honest hint ==")
ins_none = en.species_insight({}, calibrating=True)
check("none-quality hint says relying on calibration", "entirely on this plant" in ins_none["calibration_hint"])
check("no reference -> comparison calibrating", ins_none["watering_interval_comparison"] == "calibrating")

print("== after calibration: comparison + lenient fit ==")
faster = en.species_insight(rich, calibrating=False, learned_interval_days=9.0)
check("9 vs 14 -> dries_faster", faster["watering_interval_comparison"] == "dries_faster_than_reference")
check("9 vs 14 -> plausible (lenient)", faster["baseline_species_fit"] == "plausible")
check("no calibration hint after lock", "calibration_hint" not in faster)

matches = en.species_insight(rich, calibrating=False, learned_interval_days=13.0)
check("13 vs 14 -> matches", matches["watering_interval_comparison"] == "matches_reference")

slower = en.species_insight(rich, calibrating=False, learned_interval_days=30.0)
check("30 vs 14 -> dries_slower", slower["watering_interval_comparison"] == "dries_slower_than_reference")

wild = en.species_insight(rich, calibrating=False, learned_interval_days=60.0)
check("60 vs 14 (4.3x) -> outside_expected", wild["baseline_species_fit"] == "outside_expected")

noref = en.species_insight({"source": "inaturalist"}, calibrating=False, learned_interval_days=9.0)
check("no reference after cal -> no_reference comparison", noref["watering_interval_comparison"] == "no_reference")
check("no reference -> fit unknown", noref["baseline_species_fit"] == "unknown")

print("\nALL SPECIES-INSIGHT TESTS PASSED")
