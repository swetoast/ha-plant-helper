from datetime import datetime,timezone,timedelta
import pytest
from domain.config import ValidationError
from domain.environment import canonical_location,normalize_physical_state,normalize_weather_payload,derive_weather_windows
import asyncio
from datetime import datetime,timedelta,timezone
from domain.forecast import *
from domain.air_quality import AirQualityCollector, AirQualityError, AirQualityRequest, AirQualitySnapshot, combine_environment, request_for as aq_request_for
from types import SimpleNamespace
from domain.interpretation import *
import json
from datetime import datetime, timezone
from pathlib import Path
from domain.open_meteo import air_quality_url_params, forecast_url_params, map_air_quality_response, map_forecast_response
from domain.forecast import ForecastCollector, request_for as forecast_request
from domain.air_quality import AirQualityCollector, request_for as air_request

# ---- from test_environment.py ----
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


# ---- from test_forecast.py ----
NOW=datetime(2026,1,1,tzinfo=timezone.utc)
def payload(status=200,daily=True):
 times=[(NOW+timedelta(hours=i)).isoformat() for i in range(-24,49)];n=len(times)
 return {'status':status,'hourly':{'time':times,'units':{'temperature':'°C','humidity':'%','precipitation':'mm','radiation':'W/m²','et0':'mm'},'temperature':[5]*n,'humidity':[95]*n,'precipitation':[1]*n,'radiation':[10]*n,'et0':[.1]*n},**({'daily':{'time':[(NOW+timedelta(days=i)).date().isoformat() for i in range(7)]}} if daily else {})}
def forecast_run(c):return asyncio.run(c)
def test_profiles_coordinates_and_normal():
 assert request_for(57.72149,12.94051,False).sections==('current',);r=request_for(57.72149,12.94051,True);assert (r.latitude,r.longitude)==(57.721,12.941)
 c=ForecastCollector(lambda _:asyncio.sleep(0,result=payload()));s=forecast_run(c.refresh(r,NOW));assert s.generation==1 and s.data['derived']['forecast_precipitation_24h']==24 and s.data['derived']['wet_hours_48h']==48
def test_partial_indoor_allowed_outdoor_rejected():
 c=ForecastCollector(lambda _:asyncio.sleep(0,result=payload(daily=False)));forecast_run(c.refresh(request_for(1,2,False),NOW))
 with pytest.raises(ForecastError,match='partial'):forecast_run(c.refresh(request_for(1,2,True),NOW))
@pytest.mark.parametrize('kind',[400,429,500,503])
def test_http_errors(kind):
 c=ForecastCollector(lambda _:asyncio.sleep(0,result={'status':kind}))
 with pytest.raises(ForecastError,match=str(kind)):forecast_run(c.refresh(request_for(1,2,True),NOW))
def test_timeout_and_stale_while_refresh_backoff():
 state={'fail':False}
 async def f(_):
  if state['fail']:raise TimeoutError
  return payload()
 c=ForecastCollector(f);r=request_for(1,2,True);first=forecast_run(c.refresh(r,NOW));state['fail']=True;stale=forecast_run(c.refresh(r,NOW+timedelta(minutes=31)));assert stale.stale and stale.generation==first.generation
 assert forecast_run(c.refresh(r,NOW+timedelta(minutes=32))).stale
def test_malformed_units_and_timestamp():
 async def bad(_):
  p=payload();p['hourly']['units']['temperature']='F';return p
 with pytest.raises(ForecastError,match='units'):forecast_run(ForecastCollector(bad).refresh(request_for(1,2,True),NOW))
 async def malformed(_):
  p=payload();p['hourly']['time'][0]='bad';return p
 with pytest.raises(ForecastError):forecast_run(ForecastCollector(malformed).refresh(request_for(1,2,True),NOW))


# ---- from test_air_quality.py ----
NOW=datetime(2026,1,1,tzinfo=timezone.utc)
def data(status=200):return {'status':status,'current':{'ozone':55},'hourly':{'time':[(NOW+timedelta(hours=i)).isoformat() for i in range(3)],'ozone':[50,51,52]}}
def air_quality_run(c):return asyncio.run(c)
def test_outdoor_only_and_coordinates():
 assert aq_request_for(1,2,False) is None;assert aq_request_for(57.72149,12.94051,True)==AirQualityRequest(57.721,12.941)
def test_current_hourly_override_refresh_generation():
 c=AirQualityCollector(lambda _:asyncio.sleep(0,result=data()));r=aq_request_for(1,2,True);s=air_quality_run(c.refresh(r,NOW));assert s.source=='open_meteo' and s.current_ozone==55 and len(s.hourly_ozone)==3 and s.generation==1
 assert air_quality_run(c.refresh(r,NOW+timedelta(minutes=30))).generation==1
def test_separate_lock_serializes_requests():
 active=0;peak=0
 async def fetch(_):
  nonlocal active,peak;active+=1;peak=max(peak,active);await asyncio.sleep(.02);active-=1;return data()
 async def scenario():
  c=AirQualityCollector(fetch);await asyncio.gather(c.refresh(AirQualityRequest(1,2),NOW),c.refresh(AirQualityRequest(3,4),NOW));assert peak==1
 air_quality_run(scenario())
@pytest.mark.parametrize('status',[400,429,500,503])
def test_http_backoff(status):
 c=AirQualityCollector(lambda _:asyncio.sleep(0,result=data(status)))
 with pytest.raises(AirQualityError,match=str(status)):air_quality_run(c.refresh(AirQualityRequest(1,2),NOW))
def test_timeout_stale_cache():
 state={'bad':False}
 async def f(_):
  if state['bad']:raise TimeoutError
  return data()
 c=AirQualityCollector(f);r=AirQualityRequest(1,2);old=air_quality_run(c.refresh(r,NOW));state['bad']=True;s=air_quality_run(c.refresh(r,NOW+timedelta(minutes=61)));assert s.stale and s.generation==old.generation
def test_failure_isolation_and_immutable_combined_snapshot():
 forecast=type('F',(),{'generation':9,'data':{'ok':True}})();snap=combine_environment(forecast,None);assert snap.forecast_generation==9 and snap.air_quality_generation is None
 with pytest.raises(TypeError):snap.values['x']=1
 air=AirQualitySnapshot(2,NOW,False,55,tuple(),'provider');snap2=combine_environment(None,air);assert snap2.forecast is None and snap2.air_quality_generation==2
def test_malformed_does_not_replace_cache():
 c=AirQualityCollector(lambda _:asyncio.sleep(0,result=data()));r=AirQualityRequest(1,2);old=air_quality_run(c.refresh(r,NOW))
 c.fetch=lambda _:asyncio.sleep(0,result={'hourly':{'time':['bad'],'ozone':[1]}})
 with pytest.raises(AirQualityError):air_quality_run(c.refresh(r,NOW+timedelta(minutes=61)))
 assert c.cache[(1,2)]==old


# ---- from test_interpretation.py ----
FORECAST={'season':'autumn','day_length':10.5,'solar_phase':'day','current_temperature':8,'derived':{'forecast_precipitation_6h':4,'radiation_24h':120,'et0_24h':5,'vpd_max_48h':1.8,'frost_hours_48h':2,'wet_hours_48h':14,'hazard':True}}
def test_indoor_uses_only_daylight_and_seasonal_context():
 r=interpret('indoor',physical={'soil_temperature':22},forecast=FORECAST,air=SimpleNamespace(current_ozone=150))
 assert r.placement=='indoor' and set(r.conditions)<=INDOOR_ALLOWED
 assert r.conditions=={'external_daylight':120.0,'season':'autumn','day_length':10.5,'solar_phase':'day'}
 for forbidden in ('rain_suppression','drying_context','frost','wetness','modelled_shallow_soil','ozone','exposure'):assert forbidden not in r.conditions
def test_indoor_has_no_cross_contamination_when_outdoor_inputs_change():
 a=interpret_indoor(physical={},forecast=FORECAST,air=SimpleNamespace(current_ozone=150))
 changed={**FORECAST,'derived':{**FORECAST['derived'],'forecast_precipitation_6h':100,'et0_24h':30,'vpd_max_48h':5,'frost_hours_48h':30,'wet_hours_48h':40}}
 b=interpret_indoor(physical={},forecast=changed,air=SimpleNamespace(current_ozone=500))
 assert a.conditions==b.conditions
def test_outdoor_complete_context():
 r=interpret('outdoor',physical={'soil_temperature':8},forecast=FORECAST,air=SimpleNamespace(current_ozone=150),rain_limit_mm=3)
 assert set(r.conditions)==OUTDOOR_KEYS and r.conditions['rain_suppression'] and r.conditions['drying_context']=='high'
 assert r.conditions['outdoor_radiation']==120 and r.conditions['frost']==2 and r.conditions['wetness']==14
 assert not r.conditions['growth_season'] and 0<=r.conditions['modelled_shallow_soil']<=100 and r.conditions['ozone']==150
 assert set(r.conditions['exposure'])=={'frost','prolonged_wetness','high_ozone','weather_hazard'}
def test_outdoor_missing_collectors_degrades_locally():
 r=interpret_outdoor(physical={'soil_temperature':12},forecast=None,air=None)
 assert not r.conditions['rain_suppression'] and r.conditions['drying_context']=='low' and r.conditions['growth_season'] and r.conditions['ozone'] is None
def test_snapshots_are_immutable():
 r=interpret_indoor(physical={},forecast=FORECAST)
 with pytest.raises(TypeError):r.conditions['x']=1
def test_invalid_placement():
 with pytest.raises(ValueError,match='placement'):interpret('greenhouse',physical={},forecast={})


# ---- from test_open_meteo.py ----

FIXTURES = Path(__file__).parents[1] / "fixtures"


def open_meteo_load(path):
    return json.loads((FIXTURES / path).read_text())


def open_meteo_run(awaitable):
    return asyncio.run(awaitable)


def test_forecast_params_indoor_omits_daily_outdoor_includes_it():
    url, indoor = forecast_url_params(forecast_request(57.72, 12.94, False))
    assert url == "https://api.open-meteo.com/v1/forecast"
    assert indoor["timezone"] == "UTC" and indoor["temperature_unit"] == "celsius"
    assert "temperature_2m" in indoor["hourly"] and "daily" not in indoor
    _, outdoor = forecast_url_params(forecast_request(57.72, 12.94, True))
    assert "daily" in outdoor and outdoor["forecast_days"] == 7


def test_real_open_meteo_forecast_is_accepted_by_the_collector():
    raw = open_meteo_load("open_meteo/boras_three_day_forecast.json")
    collector = ForecastCollector(
        lambda _req: asyncio.sleep(0, result=map_forecast_response(raw, 200))
    )
    snapshot = open_meteo_run(
        collector.refresh(
            forecast_request(57.721, 12.94, False),
            datetime(2026, 9, 23, 23, tzinfo=timezone.utc),
        )
    )
    assert snapshot.stale is False and snapshot.generation == 1
    assert snapshot.data["derived"]["forecast_precipitation_24h"] == pytest.approx(15.3)
    assert snapshot.data["derived"]["frost_hours_48h"] == 0


def test_forecast_mapping_reports_error_status_without_a_body():
    assert map_forecast_response({}, 429) == {"status": 429}
    assert map_forecast_response(None, 200) == {"status": 200}


def test_air_quality_mapping_feeds_the_collector():
    _, params = air_quality_url_params(air_request(57.72, 12.94, True))
    assert params["current"] == "ozone" and params["hourly"] == "ozone"
    raw = {
        "current": {"ozone": 61.0},
        "hourly": {
            "time": ["2026-09-23T00:00", "2026-09-23T01:00"],
            "ozone": [60.0, 62.0],
        },
    }
    collector = AirQualityCollector(
        lambda _req: asyncio.sleep(0, result=map_air_quality_response(raw, 200))
    )
    snapshot = open_meteo_run(
        collector.refresh(
            air_request(57.721, 12.94, True),
            datetime(2026, 9, 23, tzinfo=timezone.utc),
        )
    )
    assert snapshot.current_ozone == 61.0 and len(snapshot.hourly_ozone) == 2
    assert snapshot.source == "open_meteo"
