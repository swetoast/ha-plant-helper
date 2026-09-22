"""Tests for reboot-safe condition timers + engine duration overrides.

The headline test proves a "too-long" counter survives a simulated downtime gap
instead of resetting. No Home Assistant. Run: python3 tests/test_timers.py
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

from plant_helper import learned_store as ls  # noqa: E402
from plant_helper import runtime as rt  # noqa: E402
from plant_helper.engine import moisture_model as mm  # noqa: E402
from plant_helper.engine import engine as eng  # noqa: E402
from plant_helper.engine.accumulator import Sample  # noqa: E402
from plant_helper.engine.validation import RawReading  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


print("== timers: stamp / hold / clear ==")

data = ls.empty_data()
now = T0

# Condition becomes active -> stamp set, duration starts at 0.
rt.update_timer(data, "p", "dry", active=True, now=now)
check("stamp set on activation", ls.get_timer(data, "p", "dry") is not None)
check("duration 0 at activation", rt.timer_duration(data, "p", "dry", now) == 0.0)

# Two hours later, still active -> duration grows, stamp unchanged.
later = now + timedelta(hours=2)
stamp_before = ls.get_timer(data, "p", "dry")
rt.update_timer(data, "p", "dry", active=True, now=later)
check("stamp preserved while active", ls.get_timer(data, "p", "dry") == stamp_before)
check("duration grows to 120 min", abs(rt.timer_duration(data, "p", "dry", later) - 120.0) < 1e-6)

# Condition clears -> stamp removed, duration 0.
rt.update_timer(data, "p", "dry", active=False, now=later)
check("stamp cleared on deactivation", ls.get_timer(data, "p", "dry") is None)
check("duration 0 after clear", rt.timer_duration(data, "p", "dry", later) == 0.0)


print("== timers: survive a downtime gap (the point) ==")

data2 = ls.empty_data()
# Plant went dry 5 days ago; stamp persisted then.
dry_since = T0
rt.update_timer(data2, "p", "dry", active=True, now=dry_since)

# Home Assistant is offline for a while; on the next cycle it's 5 days later.
# No samples were recorded during downtime, yet the persisted stamp gives the
# true duration (a sample-walk would have reset to ~0 at the gap).
five_days_later = T0 + timedelta(days=5)
dur = rt.timer_duration(data2, "p", "dry", five_days_later)
check("dry duration spans the 5-day downtime", abs(dur - 5 * 24 * 60) < 1e-6)

# Simulate persistence: serialize the store dict and reload it (reboot).
import json  # noqa: E402
reloaded = json.loads(json.dumps(data2))
dur_after_reboot = rt.timer_duration(reloaded, "p", "dry", five_days_later)
check("duration intact after store round-trip (reboot)", abs(dur_after_reboot - 5 * 24 * 60) < 1e-6)


print("== engine: persisted duration override drives too_long ==")

# A plant with only a couple of recent below-dry samples: a sample-walk would
# see a short run, but the persisted override says it's been dry for days.
M_MAX, M_DRY = 80.0, 40.0
few = [Sample(T0 + timedelta(minutes=m), 30.0) for m in (0, 10, 20)]

no_override = mm.evaluate_moisture(
    now=T0 + timedelta(minutes=20), compensated=few, max_gap=timedelta(minutes=25),
    m_dry=M_DRY, m_max=M_MAX, drying_rate=8.0, placement="indoor",
    forecast_precip_mm=None, profile_rain_limit_mm=1.0,
)
check("without override: short run -> not dry_too_long", no_override.state != mm.DRY_TOO_LONG)
check("instantaneous below_dry flag set", no_override.below_dry is True)

with_override = mm.evaluate_moisture(
    now=T0 + timedelta(minutes=20), compensated=few, max_gap=timedelta(minutes=25),
    m_dry=M_DRY, m_max=M_MAX, drying_rate=8.0, placement="indoor",
    forecast_precip_mm=None, profile_rain_limit_mm=1.0,
    dry_run_minutes=4 * 24 * 60,   # persisted: dry for 4 days
)
check("with persisted override: dry_too_long fires", with_override.state == mm.DRY_TOO_LONG)


print("== engine: end-to-end honours EngineInputs run overrides ==")

mins = list(range(0, 6 * 60, 10))
now = T0 + timedelta(hours=6)
# Sparse below-dry moisture (varied to avoid flatline invalidation).
moisture_raw = [RawReading(T0 + timedelta(minutes=m), 29.0 + (m // 10) % 2) for m in mins]
soil_raw = [RawReading(T0 + timedelta(minutes=m), 21.0 + (m // 10) % 2) for m in mins]

inp = eng.EngineInputs(
    now=now, placement="indoor", profile="balanced",
    m_max=M_MAX, m_dry=M_DRY, drying_rate=8.0, thermal_mean=21.0, diurnal_swing=4.0,
    moisture_raw=moisture_raw, soil_temp_raw=soil_raw, battery_pct=90.0,
    dry_run_minutes=3 * 24 * 60,   # persisted 3-day dry run
)
res = eng.compute(inp)
check("engine.compute applies persisted dry timer -> underwatered",
      res.precedence.primary_issue == "underwatered")

print("\nALL TIMER TESTS PASSED")
