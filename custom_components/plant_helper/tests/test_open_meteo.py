"""Open-Meteo normalization and source-policy tests."""
from datetime import datetime, timezone
from pathlib import Path
from plant_helper.sources import open_meteo as om

NOW = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)

def payload():
    hours = [f"2026-08-28T{h:02d}:00" for h in range(24)] + [f"2026-08-29T{h:02d}:00" for h in range(24)]
    n = len(hours)
    return {"hourly": {"time": hours, "weather_code": [0]*n, "wind_gusts_10m": [12]*n,
        "precipitation": [0]*n, "precipitation_probability": [10]*12+[80]+[20]*(n-13),
        "et0_fao_evapotranspiration": [0.1]*n, "vapour_pressure_deficit": [1.2]*n,
        "temperature_2m": [21]*n, "relative_humidity_2m": [55]*n, "cloud_cover": [20]*n,
        "shortwave_radiation": [300]*n, "diffuse_radiation": [80]*n,
        "soil_temperature_6cm": [18]*n, "soil_moisture_3_to_9cm": [0.24]*n}}

def test_normalizes_forecast_and_context():
    c = om.parse_response(payload(), NOW)
    assert c and c.source == "open_meteo"
    assert c.forecast and c.forecast[0].condition == "sunny"
    assert abs(c.et0_next_24h_mm - 2.4) < 1e-9
    assert c.vpd_next_24h_mean_kpa == 1.2
    assert c.precipitation_probability_max_24h == 80
    assert c.regional_soil_moisture_3_to_9cm == 0.24

def test_rejects_error_and_malformed_payloads():
    assert om.parse_response({"error": True}, NOW) is None
    assert om.parse_response({"hourly": {}}, NOW) is None

def test_wmo_hazards_map_to_existing_engine_conditions():
    p = payload(); p["hourly"]["weather_code"][12] = 96
    c = om.parse_response(p, NOW)
    assert any(f.condition == "hail" for f in c.forecast)


def test_timestamps_are_normalized_to_aware_utc():
    p = payload()
    p["hourly"]["time"][0] = "2026-08-28T14:00:00+02:00"
    context = om.parse_response(p, NOW)
    assert context is not None
    first_ts = context.estimated_par_series[0][0]
    assert first_ts.tzinfo is not None
    assert first_ts == NOW
    assert context.fetched_at.tzinfo is not None


def test_naive_open_meteo_timestamps_are_treated_as_utc():
    context = om.parse_response(payload(), NOW)
    assert context is not None
    assert all(ts.tzinfo is not None for ts, _ in context.estimated_par_series)
    assert context.estimated_par_series[12][0] == NOW


def test_request_policy_uses_utc_timezone():
    source = Path(om.__file__).read_text(encoding="utf-8")
    assert '"timezone": "UTC"' in source
    assert '"timezone": "auto"' not in source
