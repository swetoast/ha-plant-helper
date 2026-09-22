from __future__ import annotations
import asyncio,math
from dataclasses import dataclass
from datetime import datetime,timedelta,timezone
from types import MappingProxyType
from typing import Any,Awaitable,Callable,Mapping
from .environment import canonical_location
REFRESH=timedelta(minutes=60)
BACKOFF={400:timedelta(minutes=30),429:timedelta(minutes=20),500:timedelta(minutes=5),502:timedelta(minutes=5),503:timedelta(minutes=5),504:timedelta(minutes=5)}
class AirQualityError(RuntimeError):pass
@dataclass(frozen=True,slots=True)
class AirQualityRequest:latitude:float;longitude:float
@dataclass(frozen=True,slots=True)
class AirQualitySnapshot:generation:int;fetched_at:datetime;stale:bool;current_ozone:float|None;hourly_ozone:tuple[tuple[datetime,float|None],...];source:str
@dataclass(frozen=True,slots=True)
class EnvironmentalSnapshot:forecast_generation:int|None;air_quality_generation:int|None;forecast:Any;air_quality:AirQualitySnapshot|None;values:Mapping[str,Any]
def request_for(lat:Any,lon:Any,outdoor:bool)->AirQualityRequest|None:
 if not outdoor:return None
 l=canonical_location(lat,lon);return AirQualityRequest(l.latitude,l.longitude)
def _value(v):
 if v is None:return None
 if isinstance(v,bool):raise AirQualityError('ozone')
 try:n=float(v)
 except (TypeError,ValueError):raise AirQualityError('ozone') from None
 if not math.isfinite(n) or n<0:raise AirQualityError('ozone')
 return n
def normalize(raw:Mapping[str,Any],physical:Any=None):
 current=raw.get('current',{});hourly=raw.get('hourly',{});times=hourly.get('time');values=hourly.get('ozone')
 if not isinstance(times,list) or not isinstance(values,list) or len(times)!=len(values):raise AirQualityError('hourly')
 parsed=[]
 for t,v in zip(times,values):
  try:d=datetime.fromisoformat(str(t).replace('Z','+00:00'))
  except ValueError:raise AirQualityError('time') from None
  if d.tzinfo is None:d=d.replace(tzinfo=timezone.utc)
  parsed.append((d,_value(v)))
 if tuple(sorted(t for t,_ in parsed))!=tuple(t for t,_ in parsed):raise AirQualityError('time')
 override=_value(physical) if physical not in (None,'unknown','unavailable') else None
 return (override if override is not None else _value(current.get('ozone'))),tuple(parsed),'physical' if override is not None else 'provider'
class AirQualityCollector:
 def __init__(self,fetch:Callable[[AirQualityRequest],Awaitable[Mapping[str,Any]]]):self.fetch=fetch;self.lock=asyncio.Lock();self.cache={};self.retry_after={};self.generation=0
 async def refresh(self,req:AirQualityRequest,now:datetime,physical_ozone:Any=None)->AirQualitySnapshot:
  key=(req.latitude,req.longitude);old=self.cache.get(key)
  if old and now-old.fetched_at<REFRESH:
   if physical_ozone not in (None,'unknown','unavailable'):
    ozone=_value(physical_ozone);return AirQualitySnapshot(old.generation,old.fetched_at,old.stale,ozone,old.hourly_ozone,'physical')
   return old
  if now<self.retry_after.get(key,datetime.min.replace(tzinfo=timezone.utc)) and old:return AirQualitySnapshot(old.generation,old.fetched_at,True,old.current_ozone,old.hourly_ozone,old.source)
  async with self.lock:
   try:raw=await self.fetch(req)
   except TimeoutError:
    self.retry_after[key]=now+timedelta(minutes=5)
    if old:return AirQualitySnapshot(old.generation,old.fetched_at,True,old.current_ozone,old.hourly_ozone,old.source)
    raise AirQualityError('timeout')
   status=int(raw.get('status',200))
   if status>=400:
    self.retry_after[key]=now+BACKOFF.get(status,timedelta(minutes=10))
    if old:return AirQualitySnapshot(old.generation,old.fetched_at,True,old.current_ozone,old.hourly_ozone,old.source)
    raise AirQualityError(str(status))
   current,hourly,source=normalize(raw,physical_ozone);self.generation+=1;s=AirQualitySnapshot(self.generation,now,False,current,hourly,source);self.cache[key]=s;return s
def combine_environment(forecast:Any,air:AirQualitySnapshot|None)->EnvironmentalSnapshot:
 values={'forecast':getattr(forecast,'data',None),'current_ozone':None if air is None else air.current_ozone}
 return EnvironmentalSnapshot(getattr(forecast,'generation',None),None if air is None else air.generation,forecast,air,MappingProxyType(values))
