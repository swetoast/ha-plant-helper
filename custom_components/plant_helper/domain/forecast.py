from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from typing import Any,Awaitable,Callable,Mapping
import math
from .environment import canonical_location,normalize_weather_payload,derive_weather_windows
from .config import ValidationError
REFRESH=timedelta(minutes=30)
BACKOFF={429:timedelta(minutes=15),500:timedelta(minutes=5),502:timedelta(minutes=5),503:timedelta(minutes=5),504:timedelta(minutes=5)}
REQUIRED=("temperature","humidity","precipitation","radiation","et0")
@dataclass(frozen=True,slots=True)
class ForecastRequest:
 latitude:float;longitude:float;profile:str;sections:tuple[str,...]
@dataclass(frozen=True,slots=True)
class ForecastSnapshot:
 generation:int;fetched_at:datetime;stale:bool;data:dict[str,Any]
class ForecastError(RuntimeError):pass
def request_for(lat:Any,lon:Any,outdoor:bool)->ForecastRequest:
 l=canonical_location(lat,lon);return ForecastRequest(l.latitude,l.longitude,"outdoor" if outdoor else "indoor",("current","history_24h","forecast_48h","daily_7d") if outdoor else ("current",))
def derived(series,now):
 d=derive_weather_windows(series,now=now);vals=series.values
 future=[(t,i) for i,t in enumerate(series.times) if now<t<=now+timedelta(hours=48)]
 def a(k):return [vals[k][i] for _,i in future if vals[k][i] is not None]
 temp=a('temperature');hum=a('humidity')
 d.update({"radiation_24h":sum(v for t,i in future if t<=now+timedelta(hours=24) and (v:=vals['radiation'][i]) is not None),"et0_24h":sum(v for t,i in future if t<=now+timedelta(hours=24) and (v:=vals['et0'][i]) is not None),"vpd_max_48h":max((0.6108*math.exp(17.27*x/(x+237.3))*(1-h/100) for x,h in zip(temp,hum)),default=0),"frost_hours_48h":sum(1 for x in temp if x<=0),"wet_hours_48h":sum(1 for h in hum if h>=90),"hazard":bool(any(x<=0 for x in temp) or d['forecast_precipitation_24h']>=20)})
 return d
class ForecastCollector:
 def __init__(self,fetch:Callable[[ForecastRequest],Awaitable[Mapping[str,Any]]]):self.fetch=fetch;self.cache={};self.generation=0;self.retry_after={}
 async def refresh(self,req:ForecastRequest,now:datetime)->ForecastSnapshot:
  key=(req.latitude,req.longitude,req.profile);old=self.cache.get(key)
  if old and now-old.fetched_at<REFRESH:return old
  if now<self.retry_after.get(key,datetime.min.replace(tzinfo=timezone.utc)) and old:return ForecastSnapshot(old.generation,old.fetched_at,True,old.data)
  try:raw=await self.fetch(req)
  except TimeoutError:
   self.retry_after[key]=now+timedelta(minutes=5)
   if old:return ForecastSnapshot(old.generation,old.fetched_at,True,old.data)
   raise ForecastError('timeout')
  status=int(raw.get('status',200))
  if status>=400:
   self.retry_after[key]=now+BACKOFF.get(status,timedelta(minutes=10))
   if old:return ForecastSnapshot(old.generation,old.fetched_at,True,old.data)
   raise ForecastError(str(status))
  hourly=raw.get('hourly');daily=raw.get('daily')
  if not isinstance(hourly,Mapping):raise ForecastError('malformed')
  try:series=normalize_weather_payload(hourly,REQUIRED)
  except ValidationError as e:raise ForecastError(str(e)) from None
  units=series.units
  expected={'temperature':'\u00b0C','humidity':'%','precipitation':'mm','radiation':'W/m\u00b2','et0':'mm'}
  if any(units.get(k)!=v for k,v in expected.items()):raise ForecastError('units')
  if req.profile=='outdoor' and not isinstance(daily,Mapping):raise ForecastError('partial')
  data={'profile':req.profile,'sections':req.sections,'hourly':series,'daily':daily,'derived':derived(series,now)};self.generation+=1
  snap=ForecastSnapshot(self.generation,now,False,data);self.cache[key]=snap;return snap
