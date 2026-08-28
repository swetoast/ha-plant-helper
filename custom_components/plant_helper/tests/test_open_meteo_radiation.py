"""Phase 4 Open-Meteo radiation fallback and source-lock contracts."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
from plant_helper.engine.accumulator import Sample, complete_day_dli
from plant_helper import sample_store as sample_store
from plant_helper.sources import open_meteo as om
NOW=datetime(2026,8,28,12,tzinfo=timezone.utc)
def payload():
    n=48; times=[f"2026-08-{27+i//24:02d}T{i%24:02d}:00" for i in range(n)]
    return {"hourly":{"time":times,"shortwave_radiation":[400.0]*n,"diffuse_radiation":[100.0]*n,"weather_code":[0]*n,"precipitation":[0]*n,"precipitation_probability":[0]*n}}
def test_shortwave_converts_to_estimated_par_and_lux():
    ctx=om.parse_response(payload(),NOW)
    assert ctx and len(ctx.estimated_par_series)==48
    assert ctx.estimated_par_series[0][1] == 400.0*om.SHORTWAVE_TO_PAR
    assert ctx.outdoor_lux_series[0][1] == 400.0*om.SHORTWAVE_TO_LUX
def test_bad_radiation_values_are_not_in_series():
    p=payload(); p["hourly"]["shortwave_radiation"][0]=-1
    assert len(om.parse_response(p,NOW).estimated_par_series)==47
def test_estimated_series_produces_complete_day_dli():
    ctx=om.parse_response(payload(),NOW)
    assert complete_day_dli([Sample(ts,v) for ts,v in ctx.estimated_par_series],timedelta(minutes=90)) is not None
def test_radiation_histories_cannot_complete_each_other():
    data = sample_store.empty_data()
    day = datetime(2026, 8, 27, tzinfo=timezone.utc)
    for hour in range(12):
        ts = day + timedelta(hours=hour)
        sample_store.append_reading(data, "global:par", ts, 400.0, ts)
    for hour in range(12, 24):
        ts = day + timedelta(hours=hour)
        sample_store.append_reading(data, "global:par:open_meteo", ts, 400.0, ts)

    strang = sample_store.raw_readings(data, "global:par")
    estimated = sample_store.raw_readings(data, "global:par:open_meteo")
    strang_samples = [Sample(r.ts, r.value) for r in strang]
    estimated_samples = [Sample(r.ts, r.value) for r in estimated]
    assert complete_day_dli(strang_samples, timedelta(minutes=90)) is None
    assert complete_day_dli(estimated_samples, timedelta(minutes=90)) is None

    source=(Path(__file__).resolve().parents[1]/"coordinator.py").read_text()
    assert 'self._par_series_key = "global:par:open_meteo"' in source
    assert 'self._par_series_key = "global:par"' in source
def test_explicit_modes_cannot_silently_select_open_meteo():
    source=(Path(__file__).resolve().parents[1]/'coordinator.py').read_text()
    assert 'self._radiation_source == "auto"' in source
