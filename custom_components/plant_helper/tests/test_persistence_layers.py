"""Tests for the sample store (Tier 1) and daily-history trends (Tier 2).

No Home Assistant. Run: python3 tests/test_persistence_layers.py
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

from plant_helper import sample_store as ss  # noqa: E402
from plant_helper import learned_store as ls  # noqa: E402
from plant_helper import runtime as rt  # noqa: E402

UTC = timezone.utc
T0 = datetime(2026, 6, 1, 0, 0, tzinfo=UTC)


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


print("== sample store: append / prune / reconstruct ==")

data = ss.empty_data()
now = T0 + timedelta(hours=1)
for m in range(0, 60, 10):
    ss.append_reading(data, "plant:p1:moisture", T0 + timedelta(minutes=m), 50.0 + m, now)
readings = ss.raw_readings(data, "plant:p1:moisture")
check("readings reconstructed as RawReading", len(readings) == 6 and readings[0].value == 50.0)
check("latest value", ss.latest(data, "plant:p1:moisture") == 100.0)

# Retention: readings older than 3 days are pruned on append.
future = T0 + timedelta(days=5)
ss.append_reading(data, "plant:p1:moisture", future, 42.0, future)
kept = ss.raw_readings(data, "plant:p1:moisture")
check("old readings pruned by retention", len(kept) == 1 and kept[0].value == 42.0)

# Dedupe: same timestamp not appended twice (lagged-source repeat).
d2 = ss.empty_data()
ts = T0 + timedelta(hours=2)
ss.append_reading(d2, "global:par", ts, 72.6, ts)
ss.append_reading(d2, "global:par", ts, 72.6, ts)  # repeat of same selected hour
check("dedupe skips repeated timestamp", len(ss.raw_readings(d2, "global:par")) == 1)

# Count cap.
d3 = ss.empty_data()
base = T0
for i in range(50):
    ss.append_reading(d3, "k", base + timedelta(minutes=i), float(i), base + timedelta(minutes=i),
                      max_per_series=10)
check("count cap enforced", len(ss.raw_readings(d3, "k")) == 10)

# Clear-by-prefix (plant removal).
ss.append_reading(data, "plant:p1:lux", now, 1000.0, now)
ss.append_reading(data, "plant:p2:lux", now, 2000.0, now)
ss.clear_key_prefix(data, "plant:p1:")
check("clear prefix drops only that plant",
      not ss.raw_readings(data, "plant:p1:lux") and ss.raw_readings(data, "plant:p2:lux"))


print("== daily history: append / retention / trends ==")

d = ls.empty_data()
# 30 days: PAR declining, soil temp declining (autumn -> dormancy signal).
for i in range(30):
    ls.append_daily(d, "monstera", {
        "date": f"2026-09-{i+1:02d}",
        "daily_dli": 14.0 - i * 0.2,
        "par_mean": 200.0 - i * 3.0,       # clear decline
        "soil_temp_mean": 22.0 - i * 0.15,  # clear decline
    })
hist = ls.get_daily(d, "monstera")
check("daily history stored", len(hist) == 30)

par_slope = rt.daily_field_slope(hist, "par_mean", days=30)
temp_slope = rt.daily_field_slope(hist, "soil_temp_mean", days=30)
check("par slope negative (declining)", par_slope is not None and par_slope < 0)
check("soil temp slope negative (cooling)", temp_slope is not None and temp_slope < 0)

# These slopes should drive dormancy entry via the runtime advancement.
res = rt.advance_dormancy(d, "monstera", par_slope_30d=par_slope,
                          soil_temp_slope_30d=temp_slope, now_iso="2026-09-30T00:00:00")
check("declining 30-day trends -> dormancy entered", res.dormant and res.changed)

# DLI means.
m3, m7 = rt.recent_dli_means(hist)
check("3-day and 7-day DLI means computed", m3 is not None and m7 is not None and m3 < m7)

# Retention: re-appending same date replaces; cap holds.
ls.append_daily(d, "monstera", {"date": "2026-09-30", "daily_dli": 99.0}, retention_days=90)
same_date = [h for h in ls.get_daily(d, "monstera") if h["date"] == "2026-09-30"]
check("same-date re-append replaces, not duplicates", len(same_date) == 1)

# Retention cap.
d4 = ls.empty_data()
for i in range(100):
    ls.append_daily(d4, "x", {"date": f"day-{i:03d}", "daily_dli": float(i)}, retention_days=90)
check("daily history capped at retention", len(ls.get_daily(d4, "x")) == 90)
check("oldest days dropped first", ls.get_daily(d4, "x")[0]["date"] == "day-010")

print("\nALL PERSISTENCE-LAYER TESTS PASSED")
