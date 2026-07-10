"""Tests for validation, timeseries, and the moisture model.

Pure logic, no Home Assistant. Run: python3 tests/test_models.py
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


from plant_helper.engine.accumulator import Sample  # noqa: E402
from plant_helper.engine import validation as val  # noqa: E402
from plant_helper.engine import timeseries as ts  # noqa: E402
from plant_helper.engine import moisture_model as mm  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)
GAP = timedelta(minutes=20)


def at(minutes, value, valid=True):
    return Sample(T0 + timedelta(minutes=minutes), value, valid)


def raw(minutes, value):
    return val.RawReading(T0 + timedelta(minutes=minutes), value)


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


print("== validation: range / spike / flatline ==")

# Out-of-range moisture (150%) -> invalid; in-range stays valid.
series = val.validate_series(
    [raw(0, 50), raw(10, 150), raw(20, 55)], val.MOISTURE_SPEC
)
check("out-of-range reading invalidated",
      series[1].valid is False and series[0].valid and series[2].valid)

# A lone reverting spike is a glitch; a sustained step (watering) is preserved.
spike = val.validate_series(
    [raw(0, 40), raw(10, 41), raw(20, 90), raw(30, 41), raw(40, 42)],
    val.MOISTURE_SPEC,
)
check("lone reverting spike invalidated", spike[2].valid is False)

step = val.validate_series(
    [raw(0, 40), raw(10, 41), raw(20, 80), raw(30, 79), raw(40, 78)],
    val.MOISTURE_SPEC,
)
check("sustained watering step preserved", all(s.valid for s in step))

# Flatline: identical moisture for >12h at a mid value = stuck sensor.
flat = val.validate_series(
    [raw(h * 60, 44.0) for h in range(14)], val.MOISTURE_SPEC
)
check("mid-value flatline over 12h invalidated", all(s.valid is False for s in flat))

# Lux legitimately flatlines at 0 overnight -> NOT invalidated (spec disables it).
lux_flat = val.validate_series(
    [raw(h * 60, 0.0) for h in range(14)], val.LUX_SPEC
)
check("lux flatline at 0 tolerated", all(s.valid for s in lux_flat))


print("== validation: staleness & battery care-halt ==")

now = T0 + timedelta(hours=5)
check("fresh reading not stale",
      val.current_reading_stale(T0 + timedelta(hours=4, minutes=30), now, val.MOISTURE_SPEC) is False)
check("old reading stale",
      val.current_reading_stale(T0 + timedelta(hours=1), now, val.MOISTURE_SPEC) is True)

bat = val.battery_status(9.0)
check("low battery flagged critical", bat.critical is True)
gate = val.care_gate(battery=bat, have_any_valid_sensor=True)
check("critical battery halts care", gate.care_ok is False and gate.reason == "battery_critical")
gate2 = val.care_gate(battery=val.battery_status(80.0), have_any_valid_sensor=False)
check("no valid sensors halts care", gate2.care_ok is False and gate2.reason == "no_valid_sensors")
gate3 = val.care_gate(battery=val.battery_status(80.0), have_any_valid_sensor=True)
check("healthy -> care runs", gate3.care_ok is True)

# Categorical batteries (high/middle/low) as reported by BLE soil sensors.
check("categorical 'low' -> critical", val.battery_status("low").critical is True)
check("categorical 'middle' -> ok + valid", val.battery_status("middle").critical is False and val.battery_status("middle").valid)
check("categorical 'high' -> ok", val.battery_status("high").critical is False and val.battery_status("high").valid)
check("categorical level preserved", val.battery_status("middle").level == "middle")
check("categorical 'low' halts care",
      val.care_gate(battery=val.battery_status("low"), have_any_valid_sensor=True).care_ok is False)
# Unknown/garbage battery must NOT falsely halt care.
u = val.battery_status("potato")
check("unknown battery -> not critical, not valid", u.critical is False and u.valid is False)
check("unknown battery does not halt care",
      val.care_gate(battery=u, have_any_valid_sensor=True).care_ok is True)
check("None battery -> not critical", val.battery_status(None).critical is False)
# Numeric string still parses as percentage.
check("numeric string battery parses", val.battery_status("12").critical is True)


print("== timeseries: trend / run / step ==")

# Falling moisture over 24h at hourly cadence -> max_gap must track cadence.
falling = [at(h * 60, 70.0 - h) for h in range(24)]
HOURLY_GAP = timedelta(minutes=90)
tr = ts.trend(falling, T0 + timedelta(hours=23), timedelta(hours=24), HOURLY_GAP, flat_slope_per_day=1.0)
check("falling series -> FALLING", tr.direction == ts.FALLING and tr.slope_per_day < 0)
check("trend reports coverage", tr.coverage > 0.9)

# current_run: how long has it been below 30 (last 3h below)?
runseries = [at(0, 50), at(60, 45), at(120, 40), at(180, 28), at(240, 26), at(300, 25)]
run = ts.current_run_minutes(runseries, timedelta(minutes=90), lambda v: v < 30)
check("current dry-run measured from newest", abs(run - 120.0) < 1e-9)
# If newest is above threshold, run is 0.
run0 = ts.current_run_minutes(runseries + [at(360, 35)], timedelta(minutes=90), lambda v: v < 30)
check("run resets when condition clears", run0 == 0.0)

# Sustained step detection.
watered = [at(0, 40), at(10, 40), at(20, 75), at(30, 74), at(40, 73), at(50, 72)]
steps = ts.detect_sustained_step(
    watered, GAP, sharp_delta=12, creep_delta=10,
    creep_window=timedelta(hours=6), persistence=timedelta(hours=2),
)
check("sharp watering step detected", any(e.kind == "sharp" for e in steps))


print("== moisture: temperature compensation (#8) ==")

# Constant TRUE moisture 50, but soil temp ramps 20->30 -> raw reads high.
coeff = mm.DEFAULT_TEMP_COEFF
temps = [at(i * 10, 20.0 + i) for i in range(11)]          # 20..30 C
raw_moist = [at(i * 10, 50.0 + coeff * (10.0 + i - 10.0)) for i in range(11)]
# i.e. raw = 50 + coeff*(temp-20); compensation should recover ~50 flat.
comp = mm.temperature_compensate(raw_moist, temps, coeff=coeff, ref_temp=20.0)
comp_vals = [s.value for s in comp if s.usable]
check("compensation flattens temp-driven drift",
      max(comp_vals) - min(comp_vals) < 0.5)
# Without compensation the raw signal would look like it's *gaining* moisture.
check("raw signal was actually drifting up",
      raw_moist[-1].value - raw_moist[0].value > 1.5)


print("== moisture: states & revocable rain suppression (#10) ==")

# Learned constants for a balanced plant.
M_MAX, M_DRY, DRY_RATE = 80.0, 40.0, 8.0

# A plant sitting at 30 (below M_dry) for 3 days -> dry_too_long.
dry_long = [Sample(T0 + timedelta(hours=h), 30.0) for h in range(0, 72, 2)]
a = mm.evaluate_moisture(
    now=T0 + timedelta(hours=72), compensated=dry_long, max_gap=timedelta(hours=3),
    m_dry=M_DRY, m_max=M_MAX, drying_rate=DRY_RATE, placement="indoor",
    forecast_precip_mm=None, profile_rain_limit_mm=1.0,
)
check("indoor sustained-low -> dry_too_long", a.state == mm.DRY_TOO_LONG and a.urgency >= 80)

# Same plant OUTDOORS with 5mm rain forecast -> suppressed (downgraded), revocable.
b = mm.evaluate_moisture(
    now=T0 + timedelta(hours=72), compensated=dry_long, max_gap=timedelta(hours=3),
    m_dry=M_DRY, m_max=M_MAX, drying_rate=DRY_RATE, placement="outdoor",
    forecast_precip_mm=5.0, profile_rain_limit_mm=1.0,
)
check("outdoor + rain -> suppressed_by_rain", b.state == mm.SUPPRESSED_BY_RAIN)
check("suppression is a downgrade, not a mute", 0 < b.urgency < a.urgency)
check("suppression records the state it stands in for", b.rain_would_alert == mm.DRY_TOO_LONG)

# Forecast revised down to 0mm -> suppression revokes, alert returns.
c = mm.evaluate_moisture(
    now=T0 + timedelta(hours=72), compensated=dry_long, max_gap=timedelta(hours=3),
    m_dry=M_DRY, m_max=M_MAX, drying_rate=DRY_RATE, placement="outdoor",
    forecast_precip_mm=0.0, profile_rain_limit_mm=1.0,
)
check("suppression revokes when rain leaves forecast", c.state == mm.DRY_TOO_LONG)

# A freshly watered plant reads recently_watered regardless of level.
fresh = [at(0, 40), at(10, 40), at(20, 78), at(30, 77), at(40, 76)]
d = mm.evaluate_moisture(
    now=T0 + timedelta(minutes=45), compensated=fresh, max_gap=GAP,
    m_dry=M_DRY, m_max=M_MAX, drying_rate=DRY_RATE, placement="indoor",
    forecast_precip_mm=None, profile_rain_limit_mm=1.0,
)
check("recent watering -> recently_watered", d.state == mm.RECENTLY_WATERED)

# Dormancy relaxes the wet_too_long timer (no false alarm in dark winter).
wet = [Sample(T0 + timedelta(hours=h), 76.0) for h in range(0, 84, 2)]
awake = mm.evaluate_moisture(
    now=T0 + timedelta(hours=84), compensated=wet, max_gap=timedelta(hours=3),
    m_dry=M_DRY, m_max=M_MAX, drying_rate=DRY_RATE, placement="indoor",
    forecast_precip_mm=None, profile_rain_limit_mm=1.0, dormant=False,
)
dormant = mm.evaluate_moisture(
    now=T0 + timedelta(hours=84), compensated=wet, max_gap=timedelta(hours=3),
    m_dry=M_DRY, m_max=M_MAX, drying_rate=DRY_RATE, placement="indoor",
    forecast_precip_mm=None, profile_rain_limit_mm=1.0, dormant=True,
)
check("awake plant flags wet_too_long", awake.state == mm.WET_TOO_LONG)
check("dormant plant does not (relaxed timer)", dormant.state != mm.WET_TOO_LONG)

# Still-calibrating plant (no learned constants) stays neutral.
e = mm.evaluate_moisture(
    now=T0 + timedelta(hours=1), compensated=[at(0, 20)], max_gap=GAP,
    m_dry=None, m_max=None, drying_rate=None, placement="indoor",
    forecast_precip_mm=None, profile_rain_limit_mm=1.0,
)
check("no learned constants -> NORMAL, no false alarm", e.state == mm.NORMAL and e.urgency == 0)

print("\nALL MODEL TESTS PASSED")
