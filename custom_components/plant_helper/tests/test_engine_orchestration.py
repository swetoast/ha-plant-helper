"""Tests for health, precedence, and the engine orchestrator.

Pure logic, no Home Assistant. Run: python3 tests/test_engine_orchestration.py
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


from plant_helper.engine import health as hp  # noqa: E402
from plant_helper.engine import precedence as prec  # noqa: E402
from plant_helper.engine import moisture_model as mm  # noqa: E402
from plant_helper.engine import light_model as lm  # noqa: E402
from plant_helper.engine import thermal_model as th  # noqa: E402
from plant_helper.engine import engine as eng  # noqa: E402
from plant_helper.engine.validation import RawReading  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


print("== health: weighting, freeze, dormancy floor, missing pillars ==")

h = hp.evaluate_health(moisture_score=100, light_score=100, thermal_score=100)
check("all-ideal -> excellent 100", h.score == 100.0 and h.state == hp.EXCELLENT)

# Weighted blend: moisture 0.45, light 0.30, thermal 0.25.
h2 = hp.evaluate_health(moisture_score=40, light_score=100, thermal_score=100)
expected = (40 * 0.45 + 100 * 0.30 + 100 * 0.25) / 1.0
check("weighted blend correct", abs(h2.score - round(expected, 1)) < 0.1)

# Missing light pillar -> weights renormalise over moisture+thermal only.
h3 = hp.evaluate_health(moisture_score=80, light_score=None, thermal_score=60)
exp3 = (80 * 0.45 + 60 * 0.25) / (0.45 + 0.25)
check("missing pillar renormalises", abs(h3.score - round(exp3, 1)) < 0.1)
check("missing pillar excluded from components", "light" not in h3.components)

# Calibrating -> frozen (no score, no false penalty).
h4 = hp.evaluate_health(moisture_score=10, light_score=10, thermal_score=10, calibrating=True)
check("calibrating -> frozen score", h4.score is None and h4.state == hp.CALIBRATING)

# Dormant floor: a low measured score is lifted to the dormancy floor.
h5 = hp.evaluate_health(moisture_score=20, light_score=20, thermal_score=20, dormant=True)
check("dormancy floor applied", h5.score >= hp.DORMANCY_FLOOR)


print("== precedence: priority ladder (#4) ==")

# Sensor fault outranks everything.
p = prec.resolve_precedence(
    care_ok=False, care_reason="battery_critical",
    moisture_state=mm.DRY_TOO_LONG, light_state=lm.LOWER_DAILY_LIGHT,
    light_obstruction=True, thermal_state=th.WEATHER_HAZARD_IMMINENT, dormant=False,
)
check("sensor fault outranks all", p.primary_issue == "sensor_fault" and p.care_action == prec.CHECK_SENSOR)

# Hazard outranks dry soil.
p2 = prec.resolve_precedence(
    care_ok=True, care_reason="ok",
    moisture_state=mm.DRY_TOO_LONG, light_state=lm.NORMAL,
    light_obstruction=False, thermal_state=th.WEATHER_HAZARD_IMMINENT, dormant=False,
)
check("weather hazard outranks dry soil", p2.primary_issue == "weather_hazard")

# Dry soil outranks low light.
p3 = prec.resolve_precedence(
    care_ok=True, care_reason="ok",
    moisture_state=mm.DRY_TOO_LONG, light_state=lm.LOWER_DAILY_LIGHT,
    light_obstruction=False, thermal_state=th.STABLE, dormant=False,
)
check("dry soil outranks low light", p3.primary_issue == "underwatered" and p3.care_action == prec.WATER_NOW)

# Obstruction surfaces as its own action when nothing worse is wrong.
p4 = prec.resolve_precedence(
    care_ok=True, care_reason="ok",
    moisture_state=mm.NORMAL, light_state=lm.LOWER_DAILY_LIGHT,
    light_obstruction=True, thermal_state=th.STABLE, dormant=False,
)
check("obstruction -> clear_obstruction", p4.primary_issue == "light_obstruction" and p4.care_action == prec.CLEAR_OBSTRUCTION)

# Rain-suppressed dry reads as informational, not underwatered.
p5 = prec.resolve_precedence(
    care_ok=True, care_reason="ok",
    moisture_state=mm.SUPPRESSED_BY_RAIN, light_state=lm.NORMAL,
    light_obstruction=False, thermal_state=th.STABLE, dormant=False,
)
check("rain suppression is informational", p5.primary_issue == "rain_expected" and p5.severity < 30)

# All clear.
p6 = prec.resolve_precedence(
    care_ok=True, care_reason="ok",
    moisture_state=mm.NORMAL, light_state=lm.NORMAL,
    light_obstruction=False, thermal_state=th.STABLE, dormant=False,
)
check("all clear -> none", p6.primary_issue == "none" and p6.severity == 0)


print("== engine: end-to-end cycles ==")


def series(spec_minutes, value_fn):
    return [RawReading(T0 + timedelta(minutes=m), value_fn(m)) for m in spec_minutes]


mins_24h = list(range(0, 24 * 60, 10))
now = T0 + timedelta(hours=24)

# Scenario A: healthy indoor plant, freshly watered, good window light.
# Moisture drifts down realistically over the day (constant readings would be
# flagged as a flatlined/stuck sensor), then steps up on watering.
healthy = eng.EngineInputs(
    now=now, placement="indoor", profile="balanced",
    m_max=80, m_dry=40, drying_rate=6,
    k_by_band={"low": 0.1, "mid": 0.2, "high": 0.3}, k_scalar=0.2,
    thermal_mean=21.0, diurnal_swing=4.0,
    moisture_raw=[RawReading(T0 + timedelta(minutes=m), 70.0 - 8.0 * (m / 1440.0))
                  for m in mins_24h[:-3]]
    + [RawReading(now - timedelta(minutes=20), 78.0),
       RawReading(now - timedelta(minutes=10), 77.0),
       RawReading(now, 76.0)],
    soil_temp_raw=series(mins_24h, lambda m: 21.0 + 0.5 * (m % 3 - 1)),
    indoor_light_obs=[
        lm.IndoorLightObservation(T0 + timedelta(hours=h), 45.0, 0.30 * 5000, 5000)
        for h in range(8, 16)
    ],
    battery_pct=90.0,
)
ra = eng.compute(healthy)
check("healthy plant: care runs", ra.care_ok)
check("healthy plant: recently watered", ra.moisture.state == mm.RECENTLY_WATERED)
check("healthy plant: light normal", ra.light.state == lm.NORMAL)
check("healthy plant: good health", ra.health.score is not None and ra.health.score >= 75)
check("healthy plant: nothing urgent", ra.precedence.severity < 30)

# Scenario B: outdoor plant, bone dry for days, storm incoming -> hazard wins,
# but the moisture state is still computed underneath.
storm = eng.EngineInputs(
    now=now, placement="outdoor", profile="dry_tolerant",
    m_max=80, m_dry=40, drying_rate=8, dli_target=15.0,
    thermal_mean=18.0, diurnal_swing=6.0,
    moisture_raw=[RawReading(T0 - timedelta(hours=48) + timedelta(hours=h), 29.0 + (h % 2))
                  for h in range(0, 72, 2)],
    soil_temp_raw=series(mins_24h, lambda m: 18.0 + 0.5 * (m % 3 - 1)),
    par_raw=[RawReading(T0 + timedelta(hours=h), 300.0) for h in range(0, 25)],
    forecast=[th.ForecastHour(3.0, "lightning-rainy", wind_gust_kmh=50.0, precipitation_mm=8.0)],
    battery_pct=80.0,
)
rb = eng.compute(storm)
check("storm: hazard is the primary issue", rb.precedence.primary_issue == "weather_hazard")
check("storm: seek shelter action", rb.precedence.care_action == prec.SEEK_SHELTER)
check("storm: thermal reports hazard", rb.thermal.hazard is True)

# Scenario C: battery critical -> care halted, fault described, no plant status.
faulted = eng.EngineInputs(
    now=now, placement="indoor",
    moisture_raw=series(mins_24h, lambda m: 20.0),
    soil_temp_raw=series(mins_24h, lambda m: 21.0),
    battery_pct=8.0,
)
rc = eng.compute(faulted)
check("battery critical: care halted", rc.care_ok is False)
check("battery critical: fault described", rc.precedence.primary_issue == "sensor_fault")
check("battery critical: no health score", rc.health.score is None)
check("battery critical: health state unavailable (not calibrating)", rc.health.state == "unavailable")
check("battery critical: no moisture status emitted", rc.moisture is None)

# Scenario D: still calibrating -> neutral states, frozen health, no false alarms.
calibrating = eng.EngineInputs(
    now=now, placement="indoor", calibrating=True,
    moisture_raw=series(mins_24h, lambda m: 22.0),
    soil_temp_raw=series(mins_24h, lambda m: 21.0),
    battery_pct=90.0,
)
rd = eng.compute(calibrating)
check("calibrating: care runs but health frozen", rd.care_ok and rd.health.score is None)
check("calibrating: no false underwater alarm", rd.precedence.primary_issue in ("none", "dormant"))

# Scenario E: dormancy engaged relaxes a wet plant that would otherwise alarm.
dormant_in = eng.EngineInputs(
    now=now, placement="indoor", profile="moisture_loving",
    m_max=80, m_dry=40, drying_rate=4, thermal_mean=16.0, diurnal_swing=3.0,
    k_scalar=0.2,
    moisture_raw=[RawReading(T0 - timedelta(hours=60) + timedelta(hours=h), 77.0 + (h % 2))
                  for h in range(0, 84, 2)],
    soil_temp_raw=series(mins_24h, lambda m: 16.0 + 0.5 * (m % 3 - 1)),
    battery_pct=90.0,
    currently_dormant=True, days_in_dormancy_state=30,
    par_slope_30d=-1.0, soil_temp_slope_30d=-0.05,  # stays dormant (dead zone)
)
re = eng.compute(dormant_in)
check("dormant plant stays dormant", re.dormant is True)
check("dormant wet plant not flagged wet_too_long", re.moisture.state != mm.WET_TOO_LONG)

print("== engine: outdoor DLI uses the most recent COMPLETE STRÅNG day ==")

from plant_helper.engine.engine import th_daily_dli  # noqa: E402
from plant_helper.engine.accumulator import PAR_WH_TO_DLI, complete_day_dli, daily_dli_by_date  # noqa: E402
from plant_helper.engine.validation import validate_series, PAR_SPEC  # noqa: E402
from datetime import date  # noqa: E402

# STRÅNG day D: a full 24 hourly PAR samples at 400 W/m2 (a complete day).
day_d = datetime(2026, 6, 10, 0, 0, tzinfo=UTC)
complete_par = [RawReading(day_d + timedelta(hours=h), 400.0) for h in range(24)]
# Then just 2 samples of the NEXT day (D+1) — a partial day just after midnight.
partial_next = [RawReading(day_d + timedelta(days=1, hours=h), 800.0) for h in range(2)]
par_s = validate_series(complete_par + partial_next, PAR_SPEC)

now_after_midnight = day_d + timedelta(days=1, hours=1)
dli = th_daily_dli(par_s, now_after_midnight, timedelta(minutes=90))
expected_complete_day = 400.0 * 23.0 * PAR_WH_TO_DLI   # 23 hourly intervals in day D
check("DLI reports the complete day D, ignoring the partial next day",
      dli is not None and abs(dli - expected_complete_day) / expected_complete_day < 0.02)

# Per-date map has both days; the partial day exists but isn't chosen as "today".
by_date = daily_dli_by_date(par_s, timedelta(minutes=90))
check("per-date DLI map keys by calendar date", date(2026, 6, 10) in by_date and date(2026, 6, 11) in by_date)
check("complete-day picker skips the 2-sample partial day",
      abs(complete_day_dli(par_s, timedelta(minutes=90)) - expected_complete_day) / expected_complete_day < 0.02)

# Integration never bridges midnight (day D's DLI excludes day D+1's samples).
check("day D DLI independent of next-day samples",
      abs(by_date[date(2026, 6, 10)] - expected_complete_day) / expected_complete_day < 0.02)

print("\nALL ORCHESTRATION TESTS PASSED (with audit fixes)")
