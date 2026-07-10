"""Tests for the source adapters (pure parsing + failover logic).

No Home Assistant. Run: python3 tests/test_sources.py
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


from plant_helper.sources import forecast as fc  # noqa: E402
from plant_helper.sources import smhi  # noqa: E402
from plant_helper.engine.thermal_model import aggregate_forecast_precip, detect_hazard  # noqa: E402

UTC = timezone.utc
NOW = datetime(2026, 7, 8, 12, 0, tzinfo=UTC)


def check(name, cond):
    assert cond, f"FAILED: {name}"
    print(f"  PASS  {name}")


print("== forecast: parsing ==")

response = {
    "weather.home": {
        "forecast": [
            {"datetime": "2026-07-08T11:00:00+00:00", "condition": "sunny",
             "precipitation": 0.0, "wind_gust_speed": 10.0},   # past -> dropped? within -1h keep
            {"datetime": "2026-07-08T13:00:00+00:00", "condition": "Cloudy",
             "precipitation": 0.4, "wind_gust_speed": 22.0},
            {"datetime": "2026-07-08T15:00:00+00:00", "condition": "rainy",
             "precipitation": 1.2, "wind_gust_speed": 30.0},
            {"datetime": "2026-07-08T18:00:00+00:00", "condition": "lightning-rainy",
             "precipitation": 3.0, "wind_gust_speed": 55.0},
        ]
    }
}
hours = fc.parse_forecast(response, "weather.home", NOW)
check("parses forecast entries", len(hours) >= 3)
check("condition lowercased", all(h.condition == h.condition.lower() for h in hours))
check("hours_ahead computed", any(abs(h.hours_ahead - 1.0) < 0.01 for h in hours))
check("gust and precip parsed",
      any(h.wind_gust_kmh == 55.0 and h.precipitation_mm == 3.0 for h in hours))

# Alternate key names still parse (wind_gust instead of wind_gust_speed).
alt = {"weather.x": {"forecast": [
    {"time": "2026-07-08T14:00:00+00:00", "weather": "hail", "rain": 2.0, "wind_gust": 48.0},
]}}
alt_hours = fc.parse_forecast(alt, "weather.x", NOW)
check("tolerant key fallback (wind_gust/rain/weather)",
      len(alt_hours) == 1 and alt_hours[0].condition == "hail"
      and alt_hours[0].wind_gust_kmh == 48.0 and alt_hours[0].precipitation_mm == 2.0)

# Malformed / empty -> [] (reactive fallback, no exception).
check("empty response -> []", fc.parse_forecast({}, "weather.home", NOW) == [])
check("missing entity -> []", fc.parse_forecast({"other": {}}, "weather.home", NOW) == [])
check("garbage -> []", fc.parse_forecast("nonsense", "weather.home", NOW) == [])

# Parsed forecast feeds the thermal helpers unchanged.
haz, kind = detect_hazard(hours, placement="outdoor")
check("parsed forecast drives hazard detection", haz and kind in ("lightning-rainy", "windy", "wind_gust"))
precip = aggregate_forecast_precip(hours, horizon_hours=48.0)
check("parsed forecast aggregates precip", precip >= 4.0)


print("== smhi: parsing, lag-aware staleness, failover ==")

# Real STRÅNG dump: data_stale True but only ~17h old -> USABLE (routine lag),
# NOT a failover trigger.
real = smhi.parse_macro(
    {"par": 72.6, "global": 166.0, "diffuse": 159.9,
     "direct_horizontal": 6.1, "direct_normal": 12.8, "outdoor_lux": 19920.0},
    {"par": {"data_stale": True, "latest_available_age_hours": 17.08,
             "selected_data_time": "2026-07-07T16:00:00Z"}},
)
check("real dump parsed", real.par == 72.6 and real.global_irradiance == 166.0)
check("routine lag (data_stale + 17h) is NOT failover-stale", real.stale is False)
check("raw data_stale flag still surfaced", real.data_stale is True)
check("selected_data_time parsed for correct time axis",
      real.selected_data_time is not None and real.selected_data_time.hour == 16)
check("cloud inputs available", real.diffuse_irradiance == 159.9)

# Genuinely stale: age beyond the expected-lag threshold.
old = smhi.parse_macro({"par": 72.6}, {"par": {"latest_available_age_hours": 40.0}})
check("age beyond expected lag -> stale", old.stale is True)

# API-issue sensor on -> stale regardless of age.
issue = smhi.parse_macro(
    {"par": 72.6}, {"par": {"latest_available_age_hours": 2.0}}, api_issue=True,
)
check("api_issue on -> stale", issue.stale is True)

# Missing PAR -> stale.
missing = smhi.parse_macro({"par": None}, {})
check("missing PAR -> stale", missing.stale is True)

print("== smhi: sample-level failover on the correct time axis ==")

good = smhi.macro_par_sample(real, NOW)
check("usable lagged reading -> valid PAR sample", good.usable and good.value == 72.6)
check("PAR sample timestamped by selected_data_time, not now",
      good.ts.hour == 16 and good.ts != NOW)
bad = smhi.macro_par_sample(old, NOW)
check("genuinely stale -> invalid sample (hole, not zero)", bad.usable is False)

# Sensor-attribute forecast (real combined-sensor shape: forecast on attributes).
sensor_attrs = {
    "temperature": 21.5, "wind_gust_speed": 35.6, "precipitation": None,
    "forecast": [
        {"datetime": "2026-07-08T13:00:00+00:00", "condition": "partlycloudy",
         "precipitation": 0.0, "wind_gust_speed": 22.0},
        {"datetime": "2026-07-08T18:00:00+00:00", "condition": "lightning",
         "precipitation": 1.9, "wind_gust_speed": 20.0},
    ],
}
attr_hours = fc.parse_forecast_from_attributes(sensor_attrs, NOW)
check("forecast parsed from sensor attribute", len(attr_hours) == 2)
check("attribute forecast drives hazard (lightning)",
      detect_hazard(attr_hours, placement="outdoor")[0] is True)
check("non-forecast attrs ignored, empty forecast -> []",
      fc.parse_forecast_from_attributes({"temperature": 21.5}, NOW) == [])


print("== smhi: DLI baseline failover ==")

# Good coverage -> use measured.
check("good coverage uses measured DLI",
      smhi.effective_today_dli(9.0, coverage=0.8, baseline_dli=12.0) == 9.0)
# Poor coverage (stale left holes) -> fall back to learned baseline, not a low value.
check("poor coverage falls back to baseline",
      smhi.effective_today_dli(2.0, coverage=0.2, baseline_dli=12.0) == 12.0)
# Poor coverage but no baseline yet -> keep measured (best available).
check("no baseline keeps measured",
      smhi.effective_today_dli(2.0, coverage=0.2, baseline_dli=None) == 2.0)

print("\nALL SOURCE TESTS PASSED")
