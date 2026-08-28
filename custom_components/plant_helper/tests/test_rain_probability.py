"""Phase 3 precipitation-probability-aware rain suppression."""
from datetime import datetime, timedelta, timezone
from plant_helper.engine import engine as eng
from plant_helper.engine import moisture_model as mm
from plant_helper.engine import thermal_model as th
from plant_helper.engine.accumulator import Sample
from plant_helper.engine.validation import RawReading
from plant_helper.sources import forecast as forecast_src
from plant_helper.sources import open_meteo as om

NOW = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)

def dry_samples():
    return [Sample(NOW - timedelta(hours=72-h), 30.0) for h in range(0, 73, 2)]

def test_probability_gates_suppression_when_available():
    common = dict(now=NOW, compensated=dry_samples(), max_gap=timedelta(hours=3),
                  m_dry=40.0, m_max=80.0, drying_rate=8.0, placement="outdoor",
                  forecast_precip_mm=5.0, profile_rain_limit_mm=1.0,
                  dry_run_minutes=3*24*60)
    low = mm.evaluate_moisture(**common, forecast_precip_probability=40.0)
    high = mm.evaluate_moisture(**common, forecast_precip_probability=80.0)
    assert low.state == mm.DRY_TOO_LONG and not low.suppressed
    assert high.state == mm.SUPPRESSED_BY_RAIN and high.suppressed

def test_missing_probability_preserves_existing_provider_behavior():
    assert mm.rain_expected(5.0, 1.0, None)
    assert not mm.rain_expected(0.5, 1.0, 100.0)
    assert not mm.rain_expected(5.0, 1.0, -1.0)
    assert not mm.rain_expected(5.0, 1.0, 101.0)

def test_probability_aggregation_is_horizon_bound():
    fc = [th.ForecastHour(1, "rainy", precipitation_mm=1, precipitation_probability=35),
          th.ForecastHour(8, "rainy", precipitation_mm=2, precipitation_probability=75),
          th.ForecastHour(60, "rainy", precipitation_mm=5, precipitation_probability=99)]
    assert th.max_forecast_precip_probability(fc, horizon_hours=48) == 75

def test_generic_forecast_parser_reads_probability():
    attrs = {"forecast": [{"datetime": "2026-08-28T13:00:00+00:00", "condition": "rainy",
                            "precipitation": 2.0, "precipitation_probability": 70}]}
    fc = forecast_src.parse_forecast_from_attributes(attrs, NOW)
    assert fc[0].precipitation_probability == 70

def test_open_meteo_probability_reaches_forecast_hours():
    n=24
    payload={"hourly":{"time":[f"2026-08-28T{h:02d}:00" for h in range(n)],
             "weather_code":[61]*n,"wind_gusts_10m":[5]*n,"precipitation":[1]*n,
             "precipitation_probability":[82]*n}}
    ctx=om.parse_response(payload,NOW)
    assert ctx and ctx.forecast and ctx.forecast[0].precipitation_probability == 82

def test_engine_exposes_probability_and_does_not_suppress_low_confidence_rain():
    raw=[RawReading(NOW-timedelta(hours=6)+timedelta(minutes=m), 30+(m//10)%2) for m in range(0,361,10)]
    inp=eng.EngineInputs(now=NOW,placement="outdoor",m_max=80,m_dry=40,drying_rate=8,
        moisture_raw=raw,dry_run_minutes=3*24*60,
        forecast=[th.ForecastHour(2,"rainy",precipitation_mm=5,precipitation_probability=35)])
    result=eng.compute(inp)
    assert result.forecast_precip_48h_mm == 5
    assert result.forecast_precip_probability_max_48h == 35
    assert result.moisture.state == mm.DRY_TOO_LONG
