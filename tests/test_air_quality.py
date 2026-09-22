import asyncio
from datetime import datetime,timedelta,timezone
import pytest
from plant_helper_domain.air_quality import *
NOW=datetime(2026,1,1,tzinfo=timezone.utc)
def data(status=200):return {'status':status,'current':{'ozone':55},'hourly':{'time':[(NOW+timedelta(hours=i)).isoformat() for i in range(3)],'ozone':[50,51,52]}}
def run(c):return asyncio.run(c)
def test_outdoor_only_and_coordinates():
 assert request_for(1,2,False) is None;assert request_for(57.72149,12.94051,True)==AirQualityRequest(57.721,12.941)
def test_current_hourly_override_refresh_generation():
 c=AirQualityCollector(lambda _:asyncio.sleep(0,result=data()));r=request_for(1,2,True);s=run(c.refresh(r,NOW,physical_ozone=77));assert s.source=='physical' and s.current_ozone==77 and len(s.hourly_ozone)==3 and s.generation==1
 assert run(c.refresh(r,NOW+timedelta(minutes=30))).generation==1
def test_separate_lock_serializes_requests():
 active=0;peak=0
 async def fetch(_):
  nonlocal active,peak;active+=1;peak=max(peak,active);await asyncio.sleep(.02);active-=1;return data()
 async def scenario():
  c=AirQualityCollector(fetch);await asyncio.gather(c.refresh(AirQualityRequest(1,2),NOW),c.refresh(AirQualityRequest(3,4),NOW));assert peak==1
 run(scenario())
@pytest.mark.parametrize('status',[400,429,500,503])
def test_http_backoff(status):
 c=AirQualityCollector(lambda _:asyncio.sleep(0,result=data(status)))
 with pytest.raises(AirQualityError,match=str(status)):run(c.refresh(AirQualityRequest(1,2),NOW))
def test_timeout_stale_cache():
 state={'bad':False}
 async def f(_):
  if state['bad']:raise TimeoutError
  return data()
 c=AirQualityCollector(f);r=AirQualityRequest(1,2);old=run(c.refresh(r,NOW));state['bad']=True;s=run(c.refresh(r,NOW+timedelta(minutes=61)));assert s.stale and s.generation==old.generation
def test_failure_isolation_and_immutable_combined_snapshot():
 forecast=type('F',(),{'generation':9,'data':{'ok':True}})();snap=combine_environment(forecast,None);assert snap.forecast_generation==9 and snap.air_quality_generation is None
 with pytest.raises(TypeError):snap.values['x']=1
 air=AirQualitySnapshot(2,NOW,False,55,tuple(),'provider');snap2=combine_environment(None,air);assert snap2.forecast is None and snap2.air_quality_generation==2
def test_malformed_does_not_replace_cache():
 c=AirQualityCollector(lambda _:asyncio.sleep(0,result=data()));r=AirQualityRequest(1,2);old=run(c.refresh(r,NOW))
 c.fetch=lambda _:asyncio.sleep(0,result={'hourly':{'time':['bad'],'ozone':[1]}})
 with pytest.raises(AirQualityError):run(c.refresh(r,NOW+timedelta(minutes=61)))
 assert c.cache[(1,2)]==old
