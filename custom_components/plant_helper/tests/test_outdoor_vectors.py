"""Regression vectors proving outdoor plants share indoor core logic.

Outdoor placement may only add weather-aware behavior such as rain suppression,
ET0 drying adjustment, severe-weather hazards, and outdoor ozone advice.
"""
from datetime import datetime, timedelta, timezone

from plant_helper.engine import engine as eng
from plant_helper.engine.thermal_model import ForecastHour
from plant_helper.engine.validation import RawReading

NOW = datetime(2026, 9, 21, 12, tzinfo=timezone.utc)
LOCK = dict(m_max=95.0, m_dry=30.0, drying_rate=8.0, thermal_mean=21.0, diurnal_swing=3.0)


def series(value: float, *, hours: int = 1, step_minutes: int = 10) -> list[RawReading]:
    count = hours * 60 // step_minutes + 1
    return [RawReading(NOW - timedelta(minutes=step_minutes * (count - 1 - i)), value) for i in range(count)]


def inputs(placement: str, moisture: list[RawReading], **extra):
    return eng.EngineInputs(
        now=NOW,
        placement=placement,
        calibrating=False,
        moisture_raw=moisture,
        soil_temp_raw=[RawReading(sample.ts, 22.4) for sample in moisture],
        lux_raw=series(12000.0),
        **LOCK,
        **extra,
    )


def test_neutral_outdoor_matches_indoor_core_vectors():
    """Without outdoor weather modifiers, core care results must match."""
    for moisture in (series(96.0), series(46.0), [RawReading(sample.ts, 24.0 + (index % 3) * 0.1) for index, sample in enumerate(series(24.0, hours=72))]):
        indoor = eng.compute(inputs("indoor", moisture))
        outdoor = eng.compute(inputs("outdoor", moisture))
        assert outdoor.moisture.state == indoor.moisture.state
        assert outdoor.moisture.urgency == indoor.moisture.urgency
        assert outdoor.thermal.state == indoor.thermal.state
        assert outdoor.thermal.hazard == indoor.thermal.hazard
        assert outdoor.health.state == indoor.health.state
        assert outdoor.health.score == indoor.health.score


def test_outdoor_rain_suppresses_dry_alert_but_indoor_does_not():
    dry = [RawReading(sample.ts, 24.0 + (index % 3) * 0.1) for index, sample in enumerate(series(24.0, hours=72))]
    rain = [ForecastHour(hours_ahead=6, condition="rainy", precipitation_mm=5.0, precipitation_probability=90.0)]
    indoor = eng.compute(inputs("indoor", dry, forecast=rain, dry_run_minutes=72 * 60))
    outdoor = eng.compute(inputs("outdoor", dry, forecast=rain, dry_run_minutes=72 * 60))
    assert indoor.moisture.state == "dry_too_long"
    assert indoor.moisture.suppressed is False
    assert outdoor.moisture.state == "suppressed_by_rain"
    assert outdoor.moisture.suppressed is True
    assert 0 < outdoor.moisture.urgency < indoor.moisture.urgency


def test_outdoor_rain_suppression_is_revoked_when_forecast_clears():
    dry = [RawReading(sample.ts, 24.0 + (index % 3) * 0.1) for index, sample in enumerate(series(24.0, hours=72))]
    clear = [ForecastHour(hours_ahead=6, condition="clear", precipitation_mm=0.0, precipitation_probability=0.0)]
    outdoor = eng.compute(inputs("outdoor", dry, forecast=clear, dry_run_minutes=72 * 60))
    assert outdoor.moisture.state == "dry_too_long"
    assert outdoor.moisture.suppressed is False


def test_weather_hazard_only_applies_to_outdoor_plant():
    storm = [ForecastHour(hours_ahead=3, condition="thunderstorm", wind_gust_kmh=75.0)]
    indoor = eng.compute(inputs("indoor", series(46.0), forecast=storm))
    outdoor = eng.compute(inputs("outdoor", series(46.0), forecast=storm))
    assert indoor.thermal.hazard is False
    assert outdoor.thermal.hazard is True


def test_et0_changes_outdoor_drying_only():
    indoor = eng.compute(inputs("indoor", series(46.0), et0_next_24h_mm=6.0))
    outdoor = eng.compute(inputs("outdoor", series(46.0), et0_next_24h_mm=6.0))
    assert indoor.et0_drying_modifier == 1.0
    assert outdoor.et0_drying_modifier > 1.0
    assert outdoor.effective_drying_rate > indoor.effective_drying_rate


def test_ozone_advisory_is_outdoor_only():
    indoor = eng.compute(inputs("indoor", series(46.0), ozone_ugm3=180.0))
    outdoor = eng.compute(inputs("outdoor", series(46.0), ozone_ugm3=180.0))
    assert indoor.air_quality.advisory == "not_applicable"
    assert outdoor.air_quality.advisory not in ("none", "not_applicable")
