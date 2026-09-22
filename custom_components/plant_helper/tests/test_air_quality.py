"""Tests for the optional ground-level ozone advisory.

No Home Assistant. Run: python3 tests/test_air_quality.py
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

from plant_helper.engine import air_quality as aq  # noqa: E402
from plant_helper.engine import engine as eng  # noqa: E402
from plant_helper.engine.validation import RawReading  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


print("== ozone advisory model ==")

# Toast's real reading (44 ug/m3) outdoors -> no concern.
low = aq.assess_air_quality(ozone_ugm3=44.0, placement="outdoor")
check("real 44 ug/m3 outdoor -> none", low.advisory == aq.NONE and not low.active)

check("80 ug/m3 -> elevated", aq.assess_air_quality(ozone_ugm3=90.0, placement="outdoor").advisory == aq.ELEVATED)
check("170 ug/m3 -> high", aq.assess_air_quality(ozone_ugm3=170.0, placement="outdoor").advisory == aq.HIGH)
check("elevated is active", aq.assess_air_quality(ozone_ugm3=90.0, placement="outdoor").active is True)
check("elevated carries a message", aq.assess_air_quality(ozone_ugm3=90.0, placement="outdoor").message is not None)

# Indoor plants are shielded -> not_applicable regardless of value.
indoor = aq.assess_air_quality(ozone_ugm3=200.0, placement="indoor")
check("indoor -> not_applicable, not active", indoor.advisory == aq.NOT_APPLICABLE and not indoor.active)

# Missing reading (feature off / sensor down) -> none, never a false alarm.
check("missing ozone -> none", aq.assess_air_quality(ozone_ugm3=None, placement="outdoor").advisory == aq.NONE)


print("== ozone is advisory only (does not change care) ==")

UTC = timezone.utc
T0 = datetime(2026, 6, 1, tzinfo=UTC)
mins = list(range(0, 6 * 60, 10))
now = T0 + timedelta(hours=6)
moist = [RawReading(T0 + timedelta(minutes=m), 60.0 - m / 120.0) for m in mins]
soil = [RawReading(T0 + timedelta(minutes=m), 21.0 + (m // 10) % 2) for m in mins]

base = dict(
    now=now, placement="outdoor", profile="balanced",
    m_max=80, m_dry=40, drying_rate=6, dli_target=15.0, thermal_mean=21.0,
    diurnal_swing=4.0, moisture_raw=moist, soil_temp_raw=soil, battery_pct=90.0,
)
clean = eng.compute(eng.EngineInputs(**base, ozone_ugm3=44.0))
hazy = eng.compute(eng.EngineInputs(**base, ozone_ugm3=170.0))

check("high ozone surfaces on result", hazy.air_quality.advisory == aq.HIGH)
check("ozone does NOT change the care action",
      clean.precedence.care_action == hazy.precedence.care_action)
check("ozone does NOT change the health score",
      clean.health.score == hazy.health.score)
check("advisory appears in summary when active",
      "ozone_advisory" in hazy.summary() and "ozone_advisory" not in clean.summary())

# Available even under a sensor-fault care halt.
faulted = eng.compute(eng.EngineInputs(
    now=now, placement="outdoor", moisture_raw=moist, soil_temp_raw=soil,
    battery_pct="low", ozone_ugm3=170.0,
))
check("advisory computed even during care halt",
      faulted.care_ok is False and faulted.air_quality.advisory == aq.HIGH)

print("\nALL AIR-QUALITY TESTS PASSED")
