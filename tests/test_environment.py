from datetime import datetime,timezone,timedelta
import pytest
from plant_helper_domain.config import ValidationError
from plant_helper_domain.environment import canonical_location,normalize_physical_state,normalize_weather_payload,derive_weather_windows

def test_canonical_location():
    loc=canonical_location(57.7210347,12.9398188,timezone_name="Europe/Stockholm",profile_version=2)
    assert loc.cache_key==(57.721,12.94,"Europe/Stockholm",2)

@pytest.mark.parametrize("value,status,result", [(0,"valid",0.0),("100","valid",100.0),("unknown","unavailable",None),("x","invalid",None),(101,"out_of_range",None),(float("inf"),"invalid",None)])
def test_physical(value,status,result):
    normalized=normalize_physical_state(value,minimum=0,maximum=100)
    assert (normalized.status,normalized.value)==(status,result)

def make_payload(times,values): return {"time":[t.isoformat() for t in times],"precipitation":values,"units":{"precipitation":"mm"}}

def test_weather_and_windows():
    now=datetime(2026,9,22,12,tzinfo=timezone.utc)
    times=[now+timedelta(hours=i) for i in range(-24,25)]
    series=normalize_weather_payload(make_payload(times,[1]*len(times)),["precipitation"])
    windows=derive_weather_windows(series,now=now)
    assert windows=={"precipitation_6h":6,"precipitation_24h":24,"forecast_precipitation_6h":6,"forecast_precipitation_12h":12,"forecast_precipitation_24h":24}

@pytest.mark.parametrize("payload", [
    {"time":[],"precipitation":[],"units":{}},
    {"time":["bad"],"precipitation":[1],"units":{}},
    {"time":["2026-01-01T00:00:00+00:00"],"precipitation":[],"units":{}},
    {"time":["2026-01-01T00:00:00+00:00"],"precipitation":[float("nan")],"units":{}},
])
def test_bad_weather(payload):
    with pytest.raises(ValidationError): normalize_weather_payload(payload,["precipitation"])
