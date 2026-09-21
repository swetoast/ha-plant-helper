"""Indoor light now pairs against PAR (reliable) + migration gate for lux-era
baselines. Run: python3 tests/test_light_par_pairing.py"""
import sys, types
from datetime import datetime, timedelta, timezone
from pathlib import Path
_ROOT = Path(__file__).resolve().parents[1]
if "plant_helper" not in sys.modules:
    pkg = types.ModuleType("plant_helper"); pkg.__path__=[str(_ROOT)]; sys.modules["plant_helper"]=pkg
if str(_ROOT.parent) not in sys.path: sys.path.insert(0, str(_ROOT.parent))
from plant_helper import runtime as rt  # noqa: E402
from plant_helper.engine import calibration_math as cal  # noqa: E402
from plant_helper.engine.accumulator import Sample  # noqa: E402

def check(n,c): assert c, f"FAILED: {n}"; print(f"  PASS  {n}")
UTC=timezone.utc; T=datetime(2026,6,1,12,tzinfo=UTC)

print("== PAR pairing produces observations (the fix) ==")
# outdoor PAR series (what _par_series_key holds), local lux, elevation — concurrent
outdoor_par = [Sample(T + timedelta(hours=h), 200.0) for h in range(4)]
local_lux   = [Sample(T + timedelta(hours=h), 1800.0) for h in range(4)]
elevation   = [Sample(T + timedelta(hours=h), 40.0) for h in range(4)]
obs = rt.build_indoor_observations(local_lux, outdoor_par, elevation, timedelta(minutes=90))
check("pairs indoor lux against PAR outdoor", len(obs) == 4)
check("observation carries PAR outdoor + local lux", obs[0].outdoor_lux == 200.0 and obs[0].indoor_lux == 1800.0)
# ratio local/outdoor = 1800/200 = 9.0 (lux per W/m²) — consistent unit, above the 10 W/m² floor
k = cal.window_factor_scalar([cal.WindowSample(o.elevation_deg, o.indoor_lux, o.outdoor_lux) for o in obs])
check("k-window computed from PAR ratio", abs(k - 9.0) < 1e-9)

print("== new baselines are stamped light_ref = par ==")
recs = []
for i in range(14):
    base = datetime(2026,6,1,tzinfo=UTC) + timedelta(days=i)
    recs.append(cal.DailyRecord(
        day_index=i, coverage=0.9,
        moisture_samples=[Sample(base+timedelta(hours=h), 70.0-h) for h in range(12)],
        window_observations=[cal.WindowSample(30.0, 60.0, 100.0) for _ in range(6)],
        daily_temp_mean=21.0, daily_temp_min_max=(18.0,24.0),
    ))
res = cal.synthesize_calibration(recs, "balanced", placement="indoor")
check("locked baseline stamps light_ref=par", res.constants.get("light_ref") == "par")

print("== migration gate: lux-era baseline (no stamp) -> k withheld ==")
# Simulate the coordinator gate
def gated_k(baseline):
    ready = (baseline or {}).get("light_ref") == "par"
    return (baseline.get("k_window_scalar") if ready else None)
lux_era = {"k_window_scalar": 0.10}                       # old, no light_ref
par_new = {"k_window_scalar": 9.0, "light_ref": "par"}    # new
check("lux-era k withheld (avoids false obstruction)", gated_k(lux_era) is None)
check("par-era k applied", gated_k(par_new) == 9.0)

print("\nALL LIGHT PAR-PAIRING TESTS PASSED")

print("== provisional light during calibration (the 'reports at all' fix) ==")
from plant_helper.engine import engine as eng  # noqa: E402
from plant_helper.engine.validation import RawReading  # noqa: E402
from plant_helper.engine.calibration_math import WindowSample, window_factor_scalar  # noqa: E402

def _bell(h, a): return max(0.0, a * (1.0 - abs(h - 12) / 7.0))
_day = datetime(2026, 6, 3, tzinfo=UTC)
_now = datetime(2026, 6, 3, 13, tzinfo=UTC)
_l = [Sample(_day + timedelta(hours=h), _bell(h, 1960)) for h in range(24)]
_p = [Sample(_day + timedelta(hours=h), _bell(h, 200)) for h in range(24)]
_e = [Sample(_day + timedelta(hours=h), max(-5, _bell(h, 60) - 5)) for h in range(24)]
_obs = rt.build_indoor_observations(_l, _p, _e, eng.DEFAULT_MACRO_GAP)
_prov = window_factor_scalar([WindowSample(o.elevation_deg, o.indoor_lux, o.outdoor_lux) for o in _obs])
_moist = [RawReading(_now - timedelta(minutes=m), 55.0) for m in (30, 20, 10, 0)]

# Calibrating plant with a provisional k -> light reports, flagged provisional
_res = eng.compute(eng.EngineInputs(now=_now, placement="indoor", calibrating=True,
    moisture_raw=_moist, indoor_light_obs=_obs, k_scalar=_prov, light_provisional=True))
check("provisional light reports during calibration", _res.light is not None and _res.light.source == "window")
check("flagged provisional on the result", _res.light_provisional is True)

# No/too-few observations -> no provisional, honest none
_res2 = eng.compute(eng.EngineInputs(now=_now, placement="indoor", calibrating=True,
    moisture_raw=_moist, indoor_light_obs=_obs[:2], k_scalar=None, light_provisional=False))
check("too-few-obs stays none (no fabricated light)", _res2.light.source == "none")
check("not flagged provisional when withheld", _res2.light_provisional is False)

# Outdoor never gets a provisional window flag
_res3 = eng.compute(eng.EngineInputs(now=_now, placement="outdoor", calibrating=True,
    moisture_raw=_moist, indoor_light_obs=_obs, k_scalar=_prov, light_provisional=True))
check("outdoor is not flagged provisional-window", _res3.light_provisional is False)

print("\nALL LIGHT PAR-PAIRING + PROVISIONAL TESTS PASSED")

print("== light diagnostic reasons (real-device audit) ==")
from plant_helper.engine import light_model as lm  # noqa: E402
# 506-lx dim indoor sensor still produces a valid window reading
_lx=[Sample(_day+timedelta(hours=h), _bell(h,506)) for h in range(24)]
_pr=[Sample(_day+timedelta(hours=h), _bell(h,250)) for h in range(24)]
_ev=[Sample(_day+timedelta(hours=h), max(-5,_bell(h,50)-5)) for h in range(24)]
_o=rt.build_indoor_observations(_lx,_pr,_ev,eng.DEFAULT_MACRO_GAP)
check("506-lx dim sensor still pairs", len(_o) > 0)
_k=window_factor_scalar([WindowSample(o.elevation_deg,o.indoor_lux,o.outdoor_lux) for o in _o])
check("no observations -> reason no_observations",
      lm.evaluate_light_indoor(observations=[],k_by_band=None,k_scalar=None,max_gap=eng.DEFAULT_MACRO_GAP).reason=="no_observations")
check("obs but no coefficient -> reason calibrating",
      lm.evaluate_light_indoor(observations=_o,k_by_band=None,k_scalar=None,max_gap=eng.DEFAULT_MACRO_GAP).reason=="calibrating")
check("working -> reason ok",
      lm.evaluate_light_indoor(observations=_o,k_by_band=None,k_scalar=_k,max_gap=eng.DEFAULT_MACRO_GAP).reason=="ok")
# coordinator-refined reason survives to the result (Sensor-2 no-lux case)
_r=eng.compute(eng.EngineInputs(now=_now,placement="indoor",calibrating=True,
    moisture_raw=[RawReading(_now-timedelta(minutes=m),46.0) for m in (10,0)],
    indoor_light_obs=[], light_reason="no_light_sensor"))
check("coordinator light_reason surfaces (no_light_sensor)", _r.light_reason=="no_light_sensor")

print("\nALL LIGHT DIAGNOSTIC TESTS PASSED")

print("== obstruction: no false complaint for a no-blinds window ==")
# learned baseline from a normal window
_kk = window_factor_scalar([WindowSample(o.elevation_deg,o.indoor_lux,o.outdoor_lux)
                            for o in rt.build_indoor_observations(
    [Sample(_day+timedelta(hours=h),_bell(h,1800)) for h in range(24)],
    [Sample(_day+timedelta(hours=h),_bell(h,250)) for h in range(24)],
    [Sample(_day+timedelta(hours=h),max(-5,_bell(h,50)-5)) for h in range(24)],
    eng.DEFAULT_MACRO_GAP)])
def _obs(la,pa):
    return rt.build_indoor_observations(
        [Sample(_day+timedelta(hours=h),_bell(h,la)) for h in range(24)],
        [Sample(_day+timedelta(hours=h),_bell(h,pa)) for h in range(24)],
        [Sample(_day+timedelta(hours=h),max(-5,_bell(h,50)-5)) for h in range(24)],
        eng.DEFAULT_MACRO_GAP)
# no-blinds normal day
check("no-blinds normal day -> no obstruction",
      lm.evaluate_light_indoor(observations=_obs(1800,250),k_by_band=None,k_scalar=_kk,max_gap=eng.DEFAULT_MACRO_GAP,settled=True).obstruction is False)
# overcast day (dim outside) -> no obstruction
check("overcast day -> no obstruction",
      lm.evaluate_light_indoor(observations=_obs(300,50),k_by_band=None,k_scalar=_kk,max_gap=eng.DEFAULT_MACRO_GAP,settled=True).obstruction is False)
# provisional (calibrating) never raises obstruction regardless of the pattern
check("provisional baseline -> obstruction suppressed",
      lm.evaluate_light_indoor(observations=_obs(80,300),k_by_band=None,k_scalar=_kk,max_gap=eng.DEFAULT_MACRO_GAP,settled=False).obstruction is False)
# engine wires settled = not provisional
_er = eng.compute(eng.EngineInputs(now=_now,placement="indoor",calibrating=True,
    moisture_raw=[RawReading(_now-timedelta(minutes=m),55.0) for m in (10,0)],
    indoor_light_obs=_obs(80,300),k_scalar=_kk,light_provisional=True))
check("engine suppresses obstruction while provisional", _er.light.obstruction is False)

print("\nALL OBSTRUCTION / NO-BLINDS TESTS PASSED")

print("== obstruction actually FIRES for genuine blocking (regression: was dead post-PAR) ==")
# bright outside in PAR, dark inside, against a settled learned k -> obstruction True.
# This guards against the OUTDOOR_BRIGHT_FLOOR unit drift that silently disabled it.
_bright_dark = _obs(100, 250)  # indoor 100 lx peak, outdoor 250 PAR peak
_r_obstr = lm.evaluate_light_indoor(observations=_bright_dark, k_by_band=None, k_scalar=_kk,
                                    max_gap=eng.DEFAULT_MACRO_GAP, settled=True)
check("bright-out / dark-in -> obstruction fires", _r_obstr.obstruction is True)
check("bright floor is in PAR units (< a daytime PAR value)", lm.OUTDOOR_BRIGHT_FLOOR < 250)

print("\nALL LIGHT + OBSTRUCTION REGRESSION TESTS PASSED")
