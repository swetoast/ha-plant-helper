"""Audit of temp/moisture/battery vectors against real device values.
Run: python3 tests/test_sensor_vectors.py"""
import sys, types
from datetime import datetime, timedelta, timezone
from pathlib import Path
_ROOT=Path(__file__).resolve().parents[1]
if "plant_helper" not in sys.modules:
    pkg=types.ModuleType("plant_helper"); pkg.__path__=[str(_ROOT)]; sys.modules["plant_helper"]=pkg
if str(_ROOT.parent) not in sys.path: sys.path.insert(0,str(_ROOT.parent))
from plant_helper.engine import engine as eng  # noqa: E402
from plant_helper.engine.validation import RawReading  # noqa: E402
UTC=timezone.utc; NOW=datetime(2026,9,5,18,tzinfo=UTC)
def check(n,c): assert c, f"FAILED: {n}"; print(f"  PASS  {n}")
def s(v,n=6): return [RawReading(NOW-timedelta(minutes=10*i),v) for i in range(n)]
LOCK=dict(m_max=95.0,m_dry=30.0,drying_rate=8.0,thermal_mean=21.0,diurnal_swing=3.0)

print("== moisture (real 96%, 46%) ==")
check("96% near m_max -> normal, not overwatered",
      eng.compute(eng.EngineInputs(now=NOW,placement="indoor",calibrating=False,moisture_raw=s(96.0),**LOCK)).moisture.state=="normal")
check("46% -> drying_normally",
      eng.compute(eng.EngineInputs(now=NOW,placement="indoor",calibrating=False,moisture_raw=s(46.0),**LOCK)).moisture.state=="drying_normally")

print("== thermal (real 23.7, 22.4) ==")
for t in (23.7,22.4):
    r=eng.compute(eng.EngineInputs(now=NOW,placement="indoor",calibrating=False,moisture_raw=s(50.0),soil_temp_raw=s(t),**LOCK))
    check(f"{t}C stable, no false hazard", r.thermal.state=="stable" and r.thermal.hazard is False)
check("thermal reason ok when working",
      eng.compute(eng.EngineInputs(now=NOW,placement="indoor",calibrating=False,moisture_raw=s(50.0),soil_temp_raw=s(23.7),**LOCK)).thermal.reason=="ok")
check("thermal reason no_temp_data with no sensor",
      eng.compute(eng.EngineInputs(now=NOW,placement="indoor",calibrating=False,moisture_raw=s(50.0),soil_temp_raw=[],**LOCK)).thermal.reason=="no_temp_data")
check("thermal reason calibrating before lock",
      eng.compute(eng.EngineInputs(now=NOW,placement="indoor",calibrating=True,moisture_raw=s(50.0),soil_temp_raw=s(22.4))).thermal.reason=="calibrating")

print("== battery (real middle, 100) ==")
for b,ok in (("middle",True),("100",True),("low",False),("5",False),(None,True)):
    r=eng.compute(eng.EngineInputs(now=NOW,placement="indoor",calibrating=False,moisture_raw=s(50.0),battery_pct=b,**LOCK))
    check(f"battery {b!r} care_ok={ok}", r.care_ok is ok)

print("== graceful degradation (optional sensors absent) ==")
r=eng.compute(eng.EngineInputs(now=NOW,placement="indoor",calibrating=False,moisture_raw=s(50.0),soil_temp_raw=[],battery_pct=None,**LOCK))
check("no soil_temp/battery -> still care_ok, health present", r.care_ok is True and r.health.score is not None)

print("== calibrating stays silent (no nag) ==")
r=eng.compute(eng.EngineInputs(now=NOW,placement="indoor",calibrating=True,moisture_raw=s(46.0),soil_temp_raw=s(23.7)))
check("calibrating -> care none", r.precedence.care_action=="none")

print("\nALL SENSOR-VECTOR TESTS PASSED")


def test_real_moisture_vectors_do_not_regress():
    wet = eng.compute(eng.EngineInputs(now=NOW, placement="indoor", calibrating=False, moisture_raw=s(96.0), **LOCK))
    normal = eng.compute(eng.EngineInputs(now=NOW, placement="indoor", calibrating=False, moisture_raw=s(46.0), **LOCK))
    assert wet.moisture.state == "normal"
    assert normal.moisture.state == "drying_normally"


def test_real_thermal_vectors_do_not_regress():
    for temperature in (23.7, 22.4):
        result = eng.compute(eng.EngineInputs(now=NOW, placement="indoor", calibrating=False, moisture_raw=s(50.0), soil_temp_raw=s(temperature), **LOCK))
        assert result.thermal.state == "stable"
        assert result.thermal.hazard is False
        assert result.thermal.reason == "ok"
