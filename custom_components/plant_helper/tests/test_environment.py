"""Tests for the light, thermal, and dormancy models.

Pure logic, no Home Assistant. Run: python3 tests/test_environment.py
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


from plant_helper.engine import light_model as lm  # noqa: E402
from plant_helper.engine import thermal_model as th  # noqa: E402
from plant_helper.engine import dormancy as dm  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 6, 1, 6, 0, tzinfo=UTC)
GAP = timedelta(minutes=90)


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


print("== light: outdoor DLI states ==")

# Today's DLI meets the learned target -> normal.
a = lm.evaluate_light_outdoor(today_dli=12.0, dli_target=12.5)
check("DLI near target -> normal", a.state == lm.NORMAL and a.source == "dli")

b = lm.evaluate_light_outdoor(today_dli=16.0, dli_target=12.0)
check("DLI well above target -> higher_daily_light", b.state == lm.HIGHER_DAILY_LIGHT)

# Shortfall today, and the 7-day mean is also low -> lower_this_week.
c = lm.evaluate_light_outdoor(today_dli=6.0, dli_target=12.0, dli_mean_3d=6.5, dli_mean_7d=6.0)
check("persistent weekly shortfall -> lower_this_week", c.state == lm.LOWER_THIS_WEEK)

# Still below adequate today, but clearly above the recent 3-day floor -> recovering.
d = lm.evaluate_light_outdoor(today_dli=9.0, dli_target=12.0, dli_mean_3d=7.0, dli_mean_7d=7.0)
check("rebound above recent mean -> recovering", d.state == lm.RECOVERING)

# No external data -> unknown, never a fake "dark".
e = lm.evaluate_light_outdoor(today_dli=None, dli_target=12.0)
check("missing DLI -> unknown (no false dark)", e.state == lm.UNKNOWN and e.score is None)


print("== light: indoor window ratio & obstruction ==")


def obs(hour, elev, indoor, outdoor):
    return lm.IndoorLightObservation(T0 + timedelta(hours=hour), elev, indoor, outdoor)


K = {"low": 0.10, "mid": 0.20, "high": 0.30}

# Clear day, window passing its normal fraction (~0.30 at high sun) -> normal.
clear = [obs(h, 45.0, 0.30 * 5000.0, 5000.0) for h in range(0, 8)]
r_clear = lm.evaluate_light_indoor(
    observations=clear, k_by_band=K, k_scalar=0.2, max_gap=GAP
)
check("indoor clear day -> normal, no obstruction",
      r_clear.state == lm.NORMAL and not r_clear.obstruction)

# Cloudy day: BOTH indoor and outdoor drop proportionally -> still normal.
cloudy = [obs(h, 45.0, 0.30 * 1200.0, 1200.0) for h in range(0, 8)]
r_cloudy = lm.evaluate_light_indoor(
    observations=cloudy, k_by_band=K, k_scalar=0.2, max_gap=GAP
)
check("proportional (cloudy) drop -> normal, no obstruction",
      r_cloudy.state == lm.NORMAL and not r_cloudy.obstruction)

# Obstruction: outdoor bright, but indoor is a fraction of what the window
# should pass (curtains) -> lower_daily_light + obstruction flag.
blocked = [obs(h, 45.0, 0.05 * 5000.0, 5000.0) for h in range(0, 8)]
r_block = lm.evaluate_light_indoor(
    observations=blocked, k_by_band=K, k_scalar=0.2, max_gap=GAP
)
check("disproportionate drop -> obstruction flagged",
      r_block.obstruction and r_block.state == lm.LOWER_DAILY_LIGHT)

# No K learned yet -> unknown.
r_none = lm.evaluate_light_indoor(
    observations=clear, k_by_band=None, k_scalar=None, max_gap=GAP
)
check("indoor without K -> unknown", r_none.state == lm.UNKNOWN)


print("== thermal: cloud/forecast modifiers & states ==")

check("clear sky drying modifier ~1.0", abs(th.drying_modifier_from_cloud(0.0) - 1.0) < 1e-9)
check("overcast slows drying", th.drying_modifier_from_cloud(1.0) < 0.8)
check("wet forecast cuts drying 20%",
      abs(th.drying_modifier_from_forecast(["rainy", "cloudy", "pouring", "rainy"]) - 0.8) < 1e-9)
check("dry forecast leaves drying unchanged",
      th.drying_modifier_from_forecast(["sunny", "sunny", "cloudy"]) == 1.0)

cf = th.cloud_factor(300.0, 400.0)
check("cloud factor = diffuse/global", abs(cf - 0.75) < 1e-9)

# At the learned mean -> stable.
t_stable = th.evaluate_thermal(
    current_temp=21.0, mean_24h=21.0, thermal_mean=21.0,
    swing_today=4.0, learned_swing=4.0,
)
check("temp at learned mean -> stable", t_stable.state == th.STABLE)

# Sustained cold run -> cold_too_long.
t_cold = th.evaluate_thermal(
    current_temp=12.0, mean_24h=13.0, thermal_mean=21.0,
    swing_today=4.0, learned_swing=4.0, cold_run_minutes=240,
)
check("sustained cold -> cold_too_long", t_cold.state == th.COLD_TOO_LONG)

# Abnormal swing -> swingy.
t_swing = th.evaluate_thermal(
    current_temp=21.0, mean_24h=21.0, thermal_mean=21.0,
    swing_today=12.0, learned_swing=4.0,
)
check("large diurnal swing -> swingy", t_swing.state == th.SWINGY)


print("== thermal: severe-weather hazard ==")

fc = [
    th.ForecastHour(2.0, "lightning-rainy", wind_gust_kmh=20.0),
    th.ForecastHour(6.0, "cloudy", wind_gust_kmh=10.0),
]
haz, kind = th.detect_hazard(fc, placement="outdoor")
check("outdoor lightning within horizon -> hazard", haz and kind == "lightning-rainy")

# Same forecast indoors -> no hazard (outdoor-only defense).
haz_in, _ = th.detect_hazard(fc, placement="indoor")
check("indoor plants ignore weather hazard", haz_in is False)

# Extreme wind gust alone triggers.
windy = [th.ForecastHour(3.0, "windy", wind_gust_kmh=55.0)]
haz_w, kind_w = th.detect_hazard(windy, placement="outdoor")
check("extreme gust -> hazard", haz_w and kind_w == "windy")

# Hazard state outranks ordinary thermal classification.
t_haz = th.evaluate_thermal(
    current_temp=21.0, mean_24h=21.0, thermal_mean=21.0,
    swing_today=4.0, learned_swing=4.0, hazard=True, hazard_type="hail",
)
check("hazard outranks thermal state", t_haz.state == th.WEATHER_HAZARD_IMMINENT)

# Precip aggregation for rain suppression.
precip_fc = [
    th.ForecastHour(1.0, "rainy", precipitation_mm=0.5),
    th.ForecastHour(2.0, "rainy", precipitation_mm=0.8),
    th.ForecastHour(60.0, "rainy", precipitation_mm=5.0),  # beyond 48h horizon
]
total = th.aggregate_forecast_precip(precip_fc, horizon_hours=48.0)
check("precip aggregated within horizon only", abs(total - 1.3) < 1e-9)


print("== dormancy: hysteresis (#11) ==")

# Active plant, both signals clearly declining -> enters dormancy.
r1 = dm.evaluate_dormancy(
    currently_dormant=False, days_in_state=30,
    par_slope_30d=-4.0, soil_temp_slope_30d=-0.3,
)
check("declining light+cooling -> enter dormancy", r1.dormant and r1.changed)

# Borderline trend in the dead zone must NOT flip an active plant.
r2 = dm.evaluate_dormancy(
    currently_dormant=False, days_in_state=30,
    par_slope_30d=-1.0, soil_temp_slope_30d=-0.05,
)
check("borderline decline stays active (dead zone)", r2.dormant is False and not r2.changed)

# Dormant plant, only mild warming (not clear recovery) -> stays dormant.
r3 = dm.evaluate_dormancy(
    currently_dormant=True, days_in_state=30,
    par_slope_30d=1.0, soil_temp_slope_30d=0.05,
)
check("weak recovery does not exit dormancy", r3.dormant is True and not r3.changed)

# Dormant plant, clear recovery in BOTH -> exits.
r4 = dm.evaluate_dormancy(
    currently_dormant=True, days_in_state=30,
    par_slope_30d=4.0, soil_temp_slope_30d=0.3,
)
check("clear recovery -> exit dormancy", r4.dormant is False and r4.changed)

# Dwell guard: even a clear recovery is held if the state just changed.
r5 = dm.evaluate_dormancy(
    currently_dormant=True, days_in_state=2,
    par_slope_30d=4.0, soil_temp_slope_30d=0.3,
)
check("dwell guard holds a fresh state", r5.dormant is True and not r5.changed and r5.reason == "dwell_hold")

# Half-signal (missing macro) never flips state.
r6 = dm.evaluate_dormancy(
    currently_dormant=False, days_in_state=30,
    par_slope_30d=None, soil_temp_slope_30d=-0.3,
)
check("missing macro signal holds state", r6.changed is False and r6.reason == "insufficient_data")

print("\nALL ENVIRONMENT TESTS PASSED")


print("== light hours (weather-aware) + daylight length ==")

from datetime import datetime as _dt, timedelta as _td, timezone as _tz  # noqa: E402
from plant_helper.engine.accumulator import complete_day_light_hours, Sample as _S  # noqa: E402
from plant_helper.engine.util import daylight_hours as _daylight  # noqa: E402

_UTC = _tz.utc
_D = _dt(2026, 6, 10, 0, 0, tzinfo=_UTC)
# A complete day: 24 hourly PAR samples. 8 daytime hours above the 10 W/m2 band,
# the rest near zero (night / deep twilight).
_par = []
for h in range(24):
    val = 300.0 if 8 <= h <= 15 else 0.0
    _par.append(_S(_D + _td(hours=h), val))
_hours = complete_day_light_hours(_par, 10.0, _td(minutes=90))
check("effective light hours counts the bright block, not the dark", _hours is not None and 8.0 <= _hours <= 10.0)

# A dark overcast day: same 24 samples but all below threshold -> ~0 usable hours.
_dark = [_S(_D + _td(hours=h), 4.0) for h in range(24)]
check("dark overcast day -> ~0 effective light hours", complete_day_light_hours(_dark, 10.0, _td(minutes=90)) == 0.0)
check("no PAR samples -> None", complete_day_light_hours([], 10.0, _td(minutes=90)) is None)

# Daylight length from sun.sun next rising/setting.
# Before dawn: next setting is after next rising, both today -> setting - rising.
rise = _dt(2026, 6, 10, 4, 0, tzinfo=_UTC)
set_ = _dt(2026, 6, 10, 22, 0, tzinfo=_UTC)
check("pre-dawn daylight = setting - rising (18h)", _daylight(rise, set_) == 18.0)
# Daytime: next rising is tomorrow, next setting tonight -> 24 - night.
set_tonight = _dt(2026, 6, 10, 22, 0, tzinfo=_UTC)
rise_tomorrow = _dt(2026, 6, 11, 4, 0, tzinfo=_UTC)
check("daytime daylight = 24 - night (18h)", _daylight(rise_tomorrow, set_tonight) == 18.0)
check("missing events -> None", _daylight(None, set_) is None)
check("daylight clamped to <= 24", 0.0 <= _daylight(rise, set_) <= 24.0)

print("\nALL ENVIRONMENT TESTS PASSED (with sun/light-hours)")
