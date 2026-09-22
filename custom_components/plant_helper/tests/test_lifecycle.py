"""Add/remove lifecycle at the data layer: prove a removed plant leaves NO residue.

Mirrors what the options flow's _purge_plant does to the learned + sample stores
(the storage/device parts are HA-coupled). No Home Assistant.
Run: python3 tests/test_lifecycle.py
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
from plant_helper import sample_store as ss  # noqa: E402
from plant_helper import runtime as rt  # noqa: E402
from plant_helper.engine import calibration_math as cal  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 6, 1, tzinfo=UTC)


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


PID = "snake_plant"
OTHER = "fern"

# --- build up a fully-populated plant across both stores ------------------
ld = ls.empty_data()
ls.set_config(ld, PID, {"placement": "indoor", "profile": "balanced"})
ls.set_baseline(ld, PID, "indoor", {"m_max": 80, "m_dry": 40}, status="complete")
ls.set_calibration(ld, PID, "indoor", {"status": "complete", "day_records": [{"d": 1}]})
ls.set_dormancy(ld, PID, dormant=True, days_in_state=5, changed_at="2026-01-01T00:00:00")
ls.set_timer(ld, PID, "dry", "2026-06-01T00:00:00")
ls.set_last_reduced(ld, PID, "2026-06-01")
ls.append_daily(ld, PID, {"date": "2026-06-01", "daily_dli": 12.0})
# a second plant that must be untouched
ls.set_baseline(ld, OTHER, "indoor", {"m_max": 70}, status="complete")
ls.set_timer(ld, OTHER, "dry", "2026-06-01T00:00:00")

sd = ss.empty_data()
for sig in ("moisture", "soil_temp", "lux"):
    ss.append_reading(sd, f"plant:{PID}:{sig}", T0, 50.0, T0)
    ss.append_reading(sd, f"plant:{OTHER}:{sig}", T0, 60.0, T0)
ss.append_reading(sd, "global:par", T0, 200.0, T0)

check("plant present in learned before purge", PID in ld["plants"])
check("plant has sample keys before purge", any(k.startswith(f"plant:{PID}:") for k in sd["series"]))

# --- purge (exactly what _purge_plant does to these two stores) -----------
ls.remove_plant(ld, PID)
ss.clear_key_prefix(sd, f"plant:{PID}:")

# --- assert NO residue anywhere -------------------------------------------
check("learned record gone", PID not in ld["plants"])
check("no baseline", ls.active_baseline(ld, PID, "indoor") is None)
check("no calibration", ls.get_calibration(ld, PID, "indoor") is None)
check("dormancy back to default", ls.get_dormancy(ld, PID)["dormant"] is False)
check("timer gone", ls.get_timer(ld, PID, "dry") is None)
check("last_reduced gone", ls.get_last_reduced(ld, PID) is None)
check("daily history gone", ls.get_daily(ld, PID) == [])
check("no sample keys for plant", not any(k.startswith(f"plant:{PID}:") for k in sd["series"]))
check("timer_duration reads 0 after purge", rt.timer_duration(ld, PID, "dry", T0 + timedelta(days=1)) == 0.0)

# --- the OTHER plant is completely untouched ------------------------------
check("other plant baseline intact", ls.active_baseline(ld, OTHER, "indoor")["m_max"] == 70)
check("other plant timer intact", ls.get_timer(ld, OTHER, "dry") is not None)
check("other plant samples intact", any(k.startswith(f"plant:{OTHER}:") for k in sd["series"]))
check("global samples untouched", "global:par" in sd["series"])

# --- re-adding the same id starts clean (no ghost state) ------------------
ls.set_config(ld, PID, {"placement": "indoor", "profile": "balanced"})
check("re-added plant has no baseline (fresh calibration)", ls.active_baseline(ld, PID, "indoor") is None)
check("re-added plant is_calibrating", rt.is_calibrating(ld, PID, "indoor") is True)

print("\nALL LIFECYCLE TESTS PASSED")
