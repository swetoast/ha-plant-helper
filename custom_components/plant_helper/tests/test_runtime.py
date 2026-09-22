"""Tests for runtime helpers (day reduction, advancement, pairing).

No Home Assistant. Run: python3 tests/test_runtime.py
"""

import sys
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if "plant_helper" not in sys.modules:
    _pkg = types.ModuleType("plant_helper")
    _pkg.__path__ = [str(_ROOT)]
    sys.modules["plant_helper"] = _pkg
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from plant_helper import runtime as rt  # noqa: E402
from plant_helper import learned_store as ls  # noqa: E402
from plant_helper.engine import calibration_math as cal  # noqa: E402
from plant_helper.engine.accumulator import Sample  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)
GAP = timedelta(minutes=90)


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


def hours(series, base_offset_days=0):
    return [
        Sample(T0 + timedelta(days=base_offset_days, hours=h), v) for h, v in series
    ]


print("== runtime: day reduction ==")

now = T0 + timedelta(hours=24)
# Moisture drifts 70 -> 62 over the day (drying); soil temp swings 18-24.
moisture = [Sample(T0 + timedelta(hours=h), 70.0 - h / 3.0) for h in range(0, 24)]
soil = [Sample(T0 + timedelta(hours=h), 21.0 + 3.0 * ((h % 12) / 12.0 - 0.5)) for h in range(0, 24)]
window_obs = [cal.WindowSample(30.0, 600.0, 3000.0) for _ in range(6)]

rec = rt.reduce_day(
    day_index=0, now=now, placement="indoor",
    moisture=moisture, soil_temp=soil, par=[], window_obs=window_obs, max_gap=GAP,
)
check("day peak captured", rec.day_peak is not None and rec.day_peak > 65)
check("drying delta positive (start > end)", rec.moisture_delta is not None and rec.moisture_delta > 0)
check("temp mean computed", rec.daily_temp_mean is not None)
check("min/max computed", rec.daily_temp_min_max is not None)
check("indoor -> band ratios, no DLI", rec.window_band_ratios is not None and rec.daily_dli is None)
check("coverage reported", 0.0 <= rec.coverage <= 1.0)


print("== runtime: day record serialization round-trip ==")

blob = rt.serialize_day_record(rec)
back = rt.deserialize_day_record(blob)
check("round-trip preserves day_peak", abs(back.day_peak - rec.day_peak) < 1e-9)
check("round-trip preserves band ratios (tuple)",
      isinstance(next(iter(back.window_band_ratios.values())), tuple))
check("round-trip preserves min/max (tuple)", isinstance(back.daily_temp_min_max, tuple))


print("== runtime: calibration advancement + locking ==")

data = ls.empty_data()
ls.set_config(data, "monstera", {"profile": "balanced", "placement": "indoor"})


def good_day(i):
    return cal.DailyRecord(
        day_index=i, coverage=0.9, day_peak=76.0 + (i % 3),
        moisture_delta=None if i % 5 == 0 else 7.0,
        window_band_ratios={"high": (0.30 * 4, 4), "mid": (0.20 * 4, 4)},
        daily_temp_mean=21.0, daily_temp_min_max=(18.0, 25.0),
    )


locked_at_day = None
for i in range(14):
    locked, result = rt.advance_calibration(
        data, "monstera", "indoor", good_day(i), "balanced",
        now_iso="2026-06-15T00:00:00",
    )
    if locked and locked_at_day is None:
        locked_at_day = i

check("does not lock before day 14", locked_at_day == 13)
check("baseline locked after 14 valid days", ls.has_baseline(data, "monstera", "indoor"))
b = ls.active_baseline(data, "monstera", "indoor")
check("locked baseline carries M_max", b["m_max"] is not None and b["m_max"] > 75)
check("no longer calibrating once locked", rt.is_calibrating(data, "monstera", "indoor") is False)

# Partial calibration: never a clean drying day -> stays open past day 14.
data2 = ls.empty_data()
ls.set_config(data2, "fern", {"profile": "balanced", "placement": "indoor"})
for i in range(14):
    locked, result = rt.advance_calibration(
        data2, "fern", "indoor",
        cal.DailyRecord(day_index=i, coverage=0.9, day_peak=70.0,
                        moisture_delta=None,  # never a drying day
                        window_band_ratios={"high": (0.30, 1)},
                        daily_temp_mean=21.0, daily_temp_min_max=(18.0, 25.0)),
        "balanced", now_iso="2026-06-15T00:00:00",
    )
check("partial calibration does not lock", ls.has_baseline(data2, "fern", "indoor") is False)
prog = ls.get_calibration(data2, "fern", "indoor")
check("status becomes extending past day 14", prog["status"] == "extending")
check("missing constant reported", any("drying" in m for m in result.missing))


print("== runtime: dormancy advancement (day counting) ==")

data3 = ls.empty_data()
# Day 1: clear decline -> enter dormancy, days reset to 0.
r1 = rt.advance_dormancy(data3, "p", par_slope_30d=-4.0, soil_temp_slope_30d=-0.3, now_iso="2026-01-01T00:00:00")
check("enters dormancy", r1.dormant and r1.changed)
check("days_in_state reset on change", ls.get_dormancy(data3, "p")["days_in_state"] == 0)

# Next days: stays dormant (dwell guard holds even if trend flips), counter climbs.
for _ in range(3):
    rt.advance_dormancy(data3, "p", par_slope_30d=4.0, soil_temp_slope_30d=0.3, now_iso="2026-01-02T00:00:00")
d = ls.get_dormancy(data3, "p")
check("dwell guard holds dormant while counter climbs", d["dormant"] is True and d["days_in_state"] == 3)


print("== runtime: indoor observation pairing across STRÅNG lag ==")

# Local lux spans the last 2 days (real-time). Outdoor STRÅNG is ~18h lagged.
local_lux = [Sample(T0 + timedelta(hours=h), 1500.0) for h in range(0, 48)]
lagged_ts = T0 + timedelta(hours=6)  # a STRÅNG sample from ~1.5 days ago
outdoor = [Sample(lagged_ts, 5000.0)]
elevation = [Sample(T0 + timedelta(hours=h), 40.0) for h in range(0, 48)]

obs = rt.build_indoor_observations(local_lux, outdoor, elevation, timedelta(minutes=90))
check("lagged outdoor paired to concurrent local lux", len(obs) == 1)
check("paired observation carries both indoor and outdoor",
      obs[0].indoor_lux == 1500.0 and obs[0].outdoor_lux == 5000.0)
check("paired at the outdoor (lagged) timestamp", obs[0].ts == lagged_ts)

# No local lux near the lagged outdoor time -> no observation (no false pairing).
sparse_local = [Sample(T0 + timedelta(hours=40), 1500.0)]
obs2 = rt.build_indoor_observations(sparse_local, outdoor, elevation, timedelta(minutes=90))
check("no concurrent local lux -> no pairing", len(obs2) == 0)

print("\nALL RUNTIME TESTS PASSED")
