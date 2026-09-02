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
