"""Tests for the STRÅNG open-data API core (pure). No aiohttp, no HA.
Run: python3 tests/test_strang_api.py"""

import sys, types
from datetime import datetime, timezone, timedelta
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if "plant_helper" not in sys.modules:
    _pkg = types.ModuleType("plant_helper"); _pkg.__path__ = [str(_ROOT)]
    sys.modules["plant_helper"] = _pkg
if str(_ROOT.parent) not in sys.path:
    sys.path.insert(0, str(_ROOT.parent))

from plant_helper.sources import strang_api as sa  # noqa: E402

UTC = timezone.utc


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


# Exact sample point response from the SMHI STRÅNG docs (parameter 118, Feb 2020).
SAMPLE = [
    {"date_time": "2020-02-01 00:00:00", "value": 0},
    {"date_time": "2020-02-01 08:00:00", "value": 0},
    {"date_time": "2020-02-01 09:00:00", "value": 15.985372},
    {"date_time": "2020-02-01 10:00:00", "value": 31.193396},
    {"date_time": "2020-02-01 11:00:00", "value": 88.49596},
    {"date_time": "2020-02-01 12:00:00", "value": 93.47249},
    {"date_time": "2020-02-01 13:00:00", "value": 3.827431},
    {"date_time": "2020-02-01 15:00:00", "value": 29.610641},
    {"date_time": "2020-02-01 23:00:00", "value": 0},
    {"date_time": "2020-02-02 00:00:00", "value": 0},
]

print("== parse (real doc sample) ==")
series = sa.parse_strang_series(SAMPLE)
check("all rows parsed", len(series) == 10)
check("timestamps are UTC", series[0][0] == datetime(2020, 2, 1, 0, 0, tzinfo=UTC))
check("sorted ascending", series[0][0] < series[-1][0])
check("float values preserved", abs(series[4][1] - 88.49596) < 1e-6)
check("last point is 2020-02-02 00:00", series[-1][0] == datetime(2020, 2, 2, 0, 0, tzinfo=UTC))

print("== parse robustness ==")
check("non-list -> []", sa.parse_strang_series({"x": 1}) == [])
check("empty -> []", sa.parse_strang_series([]) == [])
check("skips bad rows", len(sa.parse_strang_series(
    [{"date_time": "bad", "value": 1}, {"date_time": "2020-02-01 00:00:00", "value": None},
     {"date_time": "2020-02-01 01:00:00", "value": 5.0}])) == 1)
check("RFC3339 T/Z form parses", sa.parse_strang_series(
    [{"date_time": "2020-02-01T05:00:00Z", "value": 2.0}])[0][0] == datetime(2020, 2, 1, 5, tzinfo=UTC))

print("== nordic coverage ==")
check("Uppsala in coverage", sa.in_nordic_coverage(59.86, 17.64) is True)
check("Boras in coverage", sa.in_nordic_coverage(57.72, 12.94) is True)
check("Norrkoping (SMHI) in coverage", sa.in_nordic_coverage(58.5812, 16.158) is True)
check("Madrid outside", sa.in_nordic_coverage(40.4, -3.7) is False)
check("Reykjavik outside (neg lon)", sa.in_nordic_coverage(64.1, -21.9) is False)
check("None -> False", sa.in_nordic_coverage(None, 17.0) is False)

print("== has_usable_data (fuzzy-edge runtime gate) ==")
check("all-zero par+global -> not usable",
      sa.has_usable_data({"par": [(datetime(2020,2,1,tzinfo=UTC), 0.0)], "global": []}) is False)
check("some non-zero -> usable",
      sa.has_usable_data({"par": [(datetime(2020,2,1,tzinfo=UTC), 12.0)]}) is True)
check("empty -> not usable", sa.has_usable_data({}) is False)

print("== macro assembly ==")
# A fresh (non-stale) day: newest PAR point 3h before now.
now = datetime(2020, 2, 1, 15, 0, tzinfo=UTC)
sbp = {
    "par": [(datetime(2020, 2, 1, 12, tzinfo=UTC), 90.0)],
    "global": [(datetime(2020, 2, 1, 12, tzinfo=UTC), 200.0)],
    "diffuse": [(datetime(2020, 2, 1, 12, tzinfo=UTC), 80.0)],
}
m = sa.macro_from_series(sbp, now)
check("par latest", m.par == 90.0)
check("global latest", m.global_irradiance == 200.0)
check("diffuse latest", m.diffuse_irradiance == 80.0)
check("outdoor_lux derived (200 * 120)", m.outdoor_lux == 24000.0)
check("selected_data_time = par ts", m.selected_data_time == datetime(2020, 2, 1, 12, tzinfo=UTC))
check("age ~3h", abs(m.age_hours - 3.0) < 1e-6)
check("not genuinely stale (3h < 36h)", m.stale is False)

# Genuinely stale: newest point 40h old.
old_now = datetime(2020, 2, 3, 4, tzinfo=UTC)
m2 = sa.macro_from_series(sbp, old_now)
check("stale when age > expected lag", m2.stale is True)

# Missing PAR -> stale.
m3 = sa.macro_from_series({"global": sbp["global"]}, now)
check("no PAR -> par None + stale", m3.par is None and m3.stale is True)

# API issue flag forces stale even if fresh.
m4 = sa.macro_from_series(sbp, now, api_issue=True)
check("api_issue forces stale", m4.stale is True)

print("\nALL STRANG API TESTS PASSED")

print("== source decision ==")
check("api -> always use api", sa.use_strang_api("api", 40.0, -3.0) is True)
check("sensors -> never", sa.use_strang_api("sensors", 59.0, 17.0) is False)
check("auto in coverage -> api", sa.use_strang_api("auto", 59.86, 17.64) is True)
check("auto outside coverage -> sensors", sa.use_strang_api("auto", 40.4, -3.7) is False)
check("auto no location -> sensors", sa.use_strang_api("auto", None, None) is False)

print("\nALL STRANG API + DECISION TESTS PASSED")
