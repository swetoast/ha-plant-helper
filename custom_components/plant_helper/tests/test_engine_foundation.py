"""Foundation tests: gap-aware accumulator + calibration synthesis.

Pure logic, no Home Assistant. Run: python3 tests/test_engine_foundation.py
Each block targets a specific review shortcoming and prints a PASS line.
"""

from datetime import datetime, timedelta, timezone

import sys
import types
from pathlib import Path

# Bootstrap: expose the integration dir as package `plant_helper` so that
# intra-package relative imports (`from ..engine`) resolve in the harness.
_ROOT = Path(__file__).resolve().parents[1]
if "plant_helper" not in sys.modules:
    _pkg = types.ModuleType("plant_helper")
    _pkg.__path__ = [str(_ROOT)]
    sys.modules["plant_helper"] = _pkg
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))


from plant_helper.engine.accumulator import (  # noqa: E402
    PAR_WH_TO_DLI,
    Sample,
    accumulate_minutes,
    coverage_ratio,
    daily_dli,
    integrate,
    robust_median,
    rolling_max_average,
    time_weighted_mean,
    valid_intervals,
    window,
)
from plant_helper.engine import calibration_math as cal  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)
GAP = timedelta(minutes=20)


def at(minutes, value, valid=True):
    return Sample(T0 + timedelta(minutes=minutes), value, valid)


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


print("== accumulator: gap invalidation ==")

# 10 samples every 10 min at 8000 lux -> 9 intervals * 10 min sufficient light.
even = [at(i * 10, 8000.0) for i in range(10)]
mins = accumulate_minutes(even, GAP, lambda lux: lux >= 1200)
check("even stream credits 90 min sufficient", abs(mins - 90.0) < 1e-9)

# A 6-hour hole in the middle must be clamped to <= GAP, not credited whole.
holed = [at(0, 8000.0), at(360, 8000.0), at(370, 8000.0)]
mins = accumulate_minutes(holed, GAP, lambda lux: lux >= 1200)
check("6h hole clamped to gap cap + step", mins <= 20.0 + 10.0 and mins < 360)

# An invalid endpoint produces no interval across it (hole, not extrapolation).
with_invalid = [at(0, 8000.0), at(10, None, valid=False), at(20, 8000.0)]
ivs = list(valid_intervals(with_invalid, GAP))
check("invalid sample severs both its intervals", len(ivs) == 0)

# Battery-dead style: valid, valid, INVALID(dead), ... , valid resumes.
dead = [at(0, 8000.0), at(10, 8000.0), at(20, 5000.0, valid=False),
        at(200, 6000.0, valid=False), at(210, 8000.0), at(220, 8000.0)]
mins = accumulate_minutes(dead, GAP, lambda lux: lux >= 1200)
# Only the two healthy 10-min spans count (0->10, 210->220); the dead span and
# the long jump back are not credited.
check("dead-sensor span not credited", abs(mins - 20.0) < 1e-9)


print("== accumulator: DLI integral correctness ==")

# Constant 400 W/m^2 PAR for exactly 12h -> DLI = 400 * 12 * PAR_WH_TO_DLI.
par_flat = [Sample(T0 + timedelta(hours=h), 400.0) for h in range(13)]
expected = 400.0 * 12.0 * PAR_WH_TO_DLI
got = daily_dli(par_flat, timedelta(minutes=90))
check("flat-PAR DLI matches analytic", abs(got - expected) < 1e-6)

# Irregular cadence must integrate the SAME area (trapezoid over real ts),
# not depend on sample count. Ramp 0->600 W/m^2 over 10h, sampled unevenly.
def ramp(minutes):
    return 600.0 * (minutes / 600.0)  # 0 at t0, 600 at +10h

uneven_ts = [0, 37, 90, 152, 210, 305, 410, 511, 600]
ramp_samples = [at(m, ramp(m)) for m in uneven_ts]
# Analytic area of a linear ramp 0->600 over 10h = mean(300) * 10h.
analytic_area = 300.0 * 10.0  # W/m^2 * hour
got_area = integrate(ramp_samples, timedelta(minutes=180))
check("uneven trapezoid integral within 1% of analytic",
      abs(got_area - analytic_area) / analytic_area < 0.01)


print("== accumulator: means / peaks / coverage ==")

twm = time_weighted_mean(even, GAP)
check("time-weighted mean of constant series", abs(twm - 8000.0) < 1e-9)

# M_max smooths a single capacitive spike: a lone 99 among a dense ~60 baseline
# (10-min cadence over 3h) must not win the peak.
spiky = [at(i * 10, 60.0) for i in range(18)]
spiky[9] = at(90, 99.0)  # one instantaneous spike
peak = rolling_max_average(spiky, timedelta(hours=3))
check("rolling-3h peak rejects lone spike", peak is not None and peak < 65)

# Coverage: only 30 of the last 60 minutes carry usable data -> ~0.5.
now = T0 + timedelta(minutes=60)
partial = [at(30, 50.0), at(40, 50.0), at(50, 50.0), at(60, 50.0)]  # covers 30..60
cov = coverage_ratio(partial, now, timedelta(minutes=60), timedelta(minutes=15))
check("coverage ratio ~0.5 on half-covered window", 0.45 <= cov <= 0.55)

check("window() trims to span",
      len(window([at(0, 1), at(100, 1), at(200, 1)], T0 + timedelta(minutes=200),
                 timedelta(minutes=150))) == 2)


print("== accumulator: robust median short-list handling ==")

# Full 14 with two wild outliers on each end -> outliers trimmed.
series14 = [1, 1, 10, 10, 10, 10, 10, 10, 10, 10, 10, 10, 99, 99]
check("14-day median trims 2 high + 2 low", robust_median(series14) == 10)
check("short 3-value list still returns (no empty core)",
      robust_median([4, 5, 6]) == 5)
check("empty -> None", robust_median([None, None]) is None)


print("== calibration: profiles & drift ==")

check("dry_tolerant multiplier", cal.dry_threshold(80, cal.PROFILE_DRY_TOLERANT) == 20)
check("balanced multiplier", cal.dry_threshold(80, cal.PROFILE_BALANCED) == 40)
check("moisture_loving multiplier", abs(cal.dry_threshold(80, cal.PROFILE_MOISTURE_LOVING) - 56) < 1e-9)
check("custom multiplier honoured",
      cal.dry_threshold(80, cal.PROFILE_CUSTOM, custom_multiplier=0.4) == 32)
check("M_max EWMA drifts toward observed slowly",
      abs(cal.nudge_peak(75.0, 55.0) - 74.0) < 1e-9)


print("== calibration: K_window floor + seasonality bands ==")

obs = (
    # dawn: outdoor PAR below the 10 W/m^2 floor -> excluded from ratio
    [cal.WindowSample(5.0, 50.0, 5.0)]
    # low band, valid (outdoor PAR 100 W/m^2)
    + [cal.WindowSample(10.0, 10.0, 100.0) for _ in range(4)]   # ratio 0.10
    # high band, valid, different transmission
    + [cal.WindowSample(50.0, 30.0, 100.0) for _ in range(4)]   # ratio 0.30
)
bands = cal.window_factor_by_elevation(obs)
check("dawn sample excluded, low band ~0.10",
      "low" in bands and abs(bands["low"] - 0.10) < 1e-9)
check("high band learned separately ~0.30",
      "high" in bands and abs(bands["high"] - 0.30) < 1e-9)
scalar = cal.window_factor_scalar(obs)
check("scalar K blends valid ratios only", 0.10 < scalar < 0.30)


print("== calibration: 14-day synthesis + partial handling ==")


def full_day(i, *, water_day=False):
    """A well-covered indoor calibration day."""
    base = T0 + timedelta(days=i)
    moisture = [Sample(base + timedelta(hours=h), 70.0 - h) for h in range(12)]
    win = [cal.WindowSample(30.0, 60.0, 100.0) for _ in range(6)]  # PAR outdoor; ratio 0.60
    return cal.DailyRecord(
        day_index=i,
        coverage=0.9,
        moisture_samples=moisture,
        moisture_delta=None if water_day else 8.0,
        daily_dli=12.0 + (i % 3),
        window_observations=win,
        daily_temp_mean=21.0 + (i % 2),
        daily_temp_min_max=(18.0, 25.0),
    )


# A complete indoor calibration: 14 valid days, plenty of drying/light/thermal.
records = [full_day(i, water_day=(i % 5 == 0)) for i in range(14)]
res = cal.synthesize_calibration(records, cal.PROFILE_BALANCED, placement="indoor")
check("full calibration -> complete", res.status == "complete")
check("M_max learned near saturation peak",
      res.constants["m_max"] is not None and res.constants["m_max"] > 60)
check("M_dry = 0.5 * M_max for balanced",
      abs(res.constants["m_dry"] - 0.5 * res.constants["m_max"]) < 1e-9)
check("K_window bands populated", bool(res.constants["k_window_by_band"]))

# Partial: user never watered (no drying deltas isolated) and only 2 valid days.
sparse = []
for i in range(14):
    r = full_day(i)
    if i >= 2:
        r.coverage = 0.2          # below MIN_DAY_COVERAGE -> excluded
    r.moisture_delta = None       # no clean drying day ever validated
    sparse.append(r)
res2 = cal.synthesize_calibration(sparse, cal.PROFILE_BALANCED, placement="indoor")
check("sparse/partial calibration -> incomplete", res2.status == "incomplete")
check("incomplete names the missing drying_rate",
      any("drying_rate" in m for m in res2.missing))
check("incomplete still reports days_elapsed", res2.days_elapsed == 14)

# Outdoor placement gates on DLI, not K_window.
outdoor = [full_day(i, water_day=(i % 6 == 0)) for i in range(14)]
res3 = cal.synthesize_calibration(outdoor, cal.PROFILE_DRY_TOLERANT, placement="outdoor")
check("outdoor complete uses DLI gate", res3.status == "complete")

print("\nALL FOUNDATION TESTS PASSED")


print("== accumulator: strict complete-day selection ==")
from plant_helper.engine.accumulator import complete_day_dli, complete_day_light_hours  # noqa: E402
_partial_day = [Sample(T0 + timedelta(hours=h), 300.0) for h in range(19)]
check("19-sample day is not treated as complete DLI", complete_day_dli(_partial_day, timedelta(minutes=90)) is None)
check("19-sample day is not treated as complete light hours", complete_day_light_hours(_partial_day, 10.0, timedelta(minutes=90)) is None)
_two_hour_day = [Sample(T0 + timedelta(hours=h), 300.0) for h in range(2)]
check("two-hour day is never returned as complete", complete_day_dli(_two_hour_day, timedelta(minutes=90)) is None)
_complete_day_start = T0.replace(hour=0)
_complete_previous = [Sample(_complete_day_start + timedelta(hours=h), 300.0) for h in range(24)]
_partial_next = [Sample(_complete_day_start + timedelta(days=1, hours=h), 900.0) for h in range(3)]
_expected_previous = daily_dli(_complete_previous, timedelta(minutes=90))
check(
    "complete previous day wins over partial current day",
    abs(complete_day_dli(_complete_previous + _partial_next, timedelta(minutes=90)) - _expected_previous) < 1e-9,
)
