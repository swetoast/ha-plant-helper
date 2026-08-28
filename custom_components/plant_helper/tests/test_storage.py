"""Tests for the learned store (pure schema) + compact-scalar calibration.

No Home Assistant. Run: python3 tests/test_storage.py
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

from plant_helper import learned_store as ls  # noqa: E402
from plant_helper.engine import calibration_math as cal  # noqa: E402


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


print("== store: schema & migration (#13) ==")

check("empty_data has version + plants", ls.empty_data()["version"] == ls.SCHEMA_VERSION)
check("garbage migrates to fresh", ls.migrate("nonsense") == ls.empty_data())
check("None migrates to fresh", ls.migrate(None)["plants"] == {})

current = {"version": ls.SCHEMA_VERSION, "plants": {"p1": {"config": {}}}}
check("current version passes through", ls.migrate(current) is current)

old = {"version": 3, "plants": {"p1": {}}}
migrated = ls.migrate(old)
check("old version bumped, plants carried", migrated["version"] == ls.SCHEMA_VERSION and "p1" in migrated["plants"])


print("== store: config & placement ==")

data = ls.empty_data()
ls.set_config(data, "monstera", {"profile": "balanced", "placement": "indoor",
                                 "sensors": {"moisture": "sensor.m"}})
check("config stored", ls.get_config(data, "monstera")["profile"] == "balanced")
check("placement read", ls.get_placement(data, "monstera") == "indoor")


print("== store: dual indoor/outdoor baselines (#12) ==")

ls.set_baseline(data, "monstera", "indoor",
                {"m_max": 80, "m_dry": 40, "k_window_scalar": 0.2},
                status="complete", locked_at="2026-06-01T00:00:00")
# The plant summers outside -> a separate outdoor baseline is learned later.
ls.set_baseline(data, "monstera", "outdoor",
                {"m_max": 85, "m_dry": 42, "dli_target": 18.0},
                status="complete", locked_at="2026-07-01T00:00:00")

ind = ls.active_baseline(data, "monstera", "indoor")
out = ls.active_baseline(data, "monstera", "outdoor")
check("indoor baseline stored", ind["m_max"] == 80 and ind["k_window_scalar"] == 0.2)
check("outdoor baseline stored separately", out["m_max"] == 85 and out["dli_target"] == 18.0)
check("both baselines coexist", ind is not out)
check("has_baseline true for complete", ls.has_baseline(data, "monstera", "outdoor"))

# Move the plant outside: baseline already exists -> no recalibration needed.
needs_cal = ls.swap_placement(data, "monstera", "outdoor")
check("swap to placement with baseline needs no recalibration", needs_cal is False)
check("swap updated active placement", ls.get_placement(data, "monstera") == "outdoor")
check("active baseline follows placement after swap",
      ls.active_baseline(data, "monstera")["m_max"] == 85)
check("indoor baseline preserved across the move",
      ls.active_baseline(data, "monstera", "indoor")["m_max"] == 80)

# Move to a placement never calibrated -> caller must recalibrate, others kept.
ls.remove_plant(data, "fern")
ls.set_config(data, "fern", {"placement": "indoor"})
ls.set_baseline(data, "fern", "indoor", {"m_max": 70}, status="complete")
needs = ls.swap_placement(data, "fern", "outdoor")
check("swap to uncalibrated placement needs recalibration", needs is True)
check("existing baseline kept when swapping to uncalibrated",
      ls.active_baseline(data, "fern", "indoor")["m_max"] == 70)


print("== store: calibration progress & dormancy ==")

ls.set_calibration(data, "monstera", "indoor",
                   {"status": "incomplete", "day_records": [{"day": 1}, {"day": 2}]})
prog = ls.get_calibration(data, "monstera", "indoor")
check("calibration progress round-trips", len(prog["day_records"]) == 2)

ls.set_dormancy(data, "monstera", dormant=True, days_in_state=9, changed_at="2026-01-15T00:00:00")
d = ls.get_dormancy(data, "monstera")
check("dormancy persisted", d["dormant"] is True and d["days_in_state"] == 9)
check("dormancy default for unknown plant", ls.get_dormancy(data, "ghost")["dormant"] is False)

ls.remove_plant(data, "monstera")
check("remove_plant drops record", "monstera" not in data["plants"])


print("== calibration: synthesis from compact scalars (no raw samples) ==")

# Days carry only reduced scalars: day_peak + per-band ratio sums + deltas.
records = []
for i in range(14):
    records.append(cal.DailyRecord(
        day_index=i, coverage=0.9,
        day_peak=75.0 + (i % 3),                       # M_max source
        moisture_delta=None if i % 5 == 0 else 7.0,     # drying days
        daily_dli=None,                                  # indoor: no DLI
        window_band_ratios={"mid": (0.20 * 4, 4), "high": (0.30 * 4, 4)},
        daily_temp_mean=21.0 + (i % 2),
        daily_temp_min_max=(18.0, 25.0),
    ))
res = cal.synthesize_calibration(records, cal.PROFILE_BALANCED, placement="indoor")
check("compact records synthesize -> complete", res.status == "complete")
check("M_max from day_peaks (max)", res.constants["m_max"] == 77.0)
check("M_dry = 0.5 * M_max", abs(res.constants["m_dry"] - 38.5) < 1e-9)
check("K bands aggregated from ratio sums",
      abs(res.constants["k_window_by_band"]["mid"] - 0.20) < 1e-9
      and abs(res.constants["k_window_by_band"]["high"] - 0.30) < 1e-9)
check("K scalar aggregated across bands",
      0.20 < res.constants["k_window_scalar"] < 0.30)

print("\nALL STORAGE TESTS PASSED")
