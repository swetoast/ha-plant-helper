from __future__ import annotations
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any,Mapping

INDOOR_ALLOWED=frozenset({'external_daylight','season','day_length','solar_phase'})
OUTDOOR_KEYS=frozenset({'rain_suppression','drying_context','outdoor_radiation','frost','wetness','growth_season','modelled_shallow_soil','ozone','exposure'})
@dataclass(frozen=True,slots=True)
class Interpretation:
 placement:str
 conditions:Mapping[str,Any]
 suppressed:tuple[str,...]

def _num(value:Any,default:float=0.0)->float:
 try:return float(value) if value is not None else default
 except (TypeError,ValueError):return default

def interpret_indoor(*,physical:Mapping[str,Any],forecast:Mapping[str,Any]|None,air:Any=None)->Interpretation:
 forecast=forecast or {};derived=forecast.get('derived',{}) or {};conditions={
  'external_daylight':_num(derived.get('radiation_24h')),
  'season':forecast.get('season'),
  'day_length':forecast.get('day_length'),
  'solar_phase':forecast.get('solar_phase'),
 }
 conditions={k:v for k,v in conditions.items() if v is not None}
 suppressed=tuple(sorted(OUTDOOR_KEYS|{'rain','wind_drying','et0','outdoor_vpd','outdoor_hazard'}))
 return Interpretation('indoor',MappingProxyType(conditions),suppressed)

def interpret_outdoor(*,physical:Mapping[str,Any],forecast:Mapping[str,Any]|None,air:Any=None,rain_limit_mm:float=1.0)->Interpretation:
 forecast=forecast or {};derived=forecast.get('derived',{}) or {}
 rain=_num(derived.get('forecast_precipitation_6h'))
 vpd=_num(derived.get('vpd_max_48h'));et0=_num(derived.get('et0_24h'));radiation=_num(derived.get('radiation_24h'))
 frost=_num(derived.get('frost_hours_48h'));wet=_num(derived.get('wet_hours_48h'))
 ozone=getattr(air,'current_ozone',None) if air is not None else None
 temperature=_num(physical.get('soil_temperature'),_num(forecast.get('current_temperature'),10))
 growth=temperature>=5 and frost==0
 modelled=max(0.0,min(100.0,50.0+rain*2.0-et0*4.0-vpd*3.0))
 drying='high' if et0>=4 or vpd>=1.5 else 'moderate' if et0>=2 or vpd>=1 else 'low'
 exposure=[]
 if frost>0:exposure.append('frost')
 if wet>=12:exposure.append('prolonged_wetness')
 if ozone is not None and _num(ozone)>=100:exposure.append('high_ozone')
 if derived.get('hazard'):exposure.append('weather_hazard')
 conditions={
  'rain_suppression':rain>=rain_limit_mm,
  'drying_context':drying,
  'outdoor_radiation':radiation,
  'frost':frost,
  'wetness':wet,
  'growth_season':growth,
  'modelled_shallow_soil':modelled,
  'ozone':ozone,
  'exposure':tuple(exposure),
 }
 return Interpretation('outdoor',MappingProxyType(conditions),tuple())

def interpret(placement:str,**kwargs:Any)->Interpretation:
 if placement=='indoor':return interpret_indoor(**kwargs)
 if placement=='outdoor':return interpret_outdoor(**kwargs)
 raise ValueError('placement')
