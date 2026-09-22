import asyncio
from datetime import datetime,timedelta,timezone
import pytest
from domain.forecast import *
NOW=datetime(2026,1,1,tzinfo=timezone.utc)
def payload(status=200,daily=True):
 times=[(NOW+timedelta(hours=i)).isoformat() for i in range(-24,49)];n=len(times)
 return {'status':status,'hourly':{'time':times,'units':{'temperature':'°C','humidity':'%','precipitation':'mm','radiation':'W/m²','et0':'mm'},'temperature':[5]*n,'humidity':[95]*n,'precipitation':[1]*n,'radiation':[10]*n,'et0':[.1]*n},**({'daily':{'time':[(NOW+timedelta(days=i)).date().isoformat() for i in range(7)]}} if daily else {})}
def run(c):return asyncio.run(c)
def test_profiles_coordinates_and_normal():
 assert request_for(57.72149,12.94051,False).sections==('current',);r=request_for(57.72149,12.94051,True);assert (r.latitude,r.longitude)==(57.721,12.941)
 c=ForecastCollector(lambda _:asyncio.sleep(0,result=payload()));s=run(c.refresh(r,NOW));assert s.generation==1 and s.data['derived']['forecast_precipitation_24h']==24 and s.data['derived']['wet_hours_48h']==48
def test_partial_indoor_allowed_outdoor_rejected():
 c=ForecastCollector(lambda _:asyncio.sleep(0,result=payload(daily=False)));run(c.refresh(request_for(1,2,False),NOW))
 with pytest.raises(ForecastError,match='partial'):run(c.refresh(request_for(1,2,True),NOW))
@pytest.mark.parametrize('kind',[400,429,500,503])
def test_http_errors(kind):
 c=ForecastCollector(lambda _:asyncio.sleep(0,result={'status':kind}))
 with pytest.raises(ForecastError,match=str(kind)):run(c.refresh(request_for(1,2,True),NOW))
def test_timeout_and_stale_while_refresh_backoff():
 state={'fail':False}
 async def f(_):
  if state['fail']:raise TimeoutError
  return payload()
 c=ForecastCollector(f);r=request_for(1,2,True);first=run(c.refresh(r,NOW));state['fail']=True;stale=run(c.refresh(r,NOW+timedelta(minutes=31)));assert stale.stale and stale.generation==first.generation
 assert run(c.refresh(r,NOW+timedelta(minutes=32))).stale
def test_malformed_units_and_timestamp():
 async def bad(_):
  p=payload();p['hourly']['units']['temperature']='F';return p
 with pytest.raises(ForecastError,match='units'):run(ForecastCollector(bad).refresh(request_for(1,2,True),NOW))
 async def malformed(_):
  p=payload();p['hourly']['time'][0]='bad';return p
 with pytest.raises(ForecastError):run(ForecastCollector(malformed).refresh(request_for(1,2,True),NOW))
