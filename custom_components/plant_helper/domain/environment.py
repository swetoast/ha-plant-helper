from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
import math
from typing import Any, Iterable, Mapping
from .config import ValidationError

@dataclass(frozen=True, slots=True)
class CanonicalLocation:
    latitude: float
    longitude: float
    timezone: str
    profile_version: int

    @property
    def cache_key(self) -> tuple[float,float,str,int]: return (self.latitude,self.longitude,self.timezone,self.profile_version)

def canonical_location(latitude: Any, longitude: Any, *, timezone_name: str="auto", profile_version: int=1) -> CanonicalLocation:
    if isinstance(latitude,bool) or isinstance(longitude,bool): raise ValidationError("coordinates")
    try: lat=float(latitude); lon=float(longitude)
    except (TypeError,ValueError): raise ValidationError("coordinates") from None
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90<=lat<=90 or not -180<=lon<=180: raise ValidationError("coordinates")
    if not isinstance(timezone_name,str) or not timezone_name: raise ValidationError("timezone")
    return CanonicalLocation(round(lat,3),round(lon,3),timezone_name,int(profile_version))

@dataclass(frozen=True, slots=True)
class PhysicalValue:
    status: str
    value: float | None

def normalize_physical_state(value: Any, *, minimum: float, maximum: float) -> PhysicalValue:
    if value is None or value in {"unknown","unavailable"}: return PhysicalValue("unavailable",None)
    if isinstance(value,bool): return PhysicalValue("invalid",None)
    try: number=float(value)
    except (TypeError,ValueError): return PhysicalValue("invalid",None)
    if not math.isfinite(number): return PhysicalValue("invalid",None)
    if not minimum<=number<=maximum: return PhysicalValue("out_of_range",None)
    return PhysicalValue("valid",number)

@dataclass(frozen=True, slots=True)
class WeatherSeries:
    times: tuple[datetime,...]
    values: dict[str,tuple[float | int | None,...]]
    units: dict[str,str]

def _parse_time(value: str) -> datetime:
    try: parsed=datetime.fromisoformat(value.replace("Z","+00:00"))
    except (TypeError,ValueError): raise ValidationError("weather_time") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

def normalize_weather_payload(raw: Mapping[str,Any], required: Iterable[str]) -> WeatherSeries:
    times_raw=raw.get("time")
    if not isinstance(times_raw,list) or not times_raw: raise ValidationError("weather_time")
    times=tuple(_parse_time(v) for v in times_raw)
    if tuple(sorted(times)) != times or len(set(times)) != len(times): raise ValidationError("weather_time")
    units=raw.get("units",{})
    if not isinstance(units,dict): raise ValidationError("weather_units")
    values={}
    for key in required:
        array=raw.get(key)
        if not isinstance(array,list) or len(array)!=len(times): raise ValidationError(f"weather_{key}")
        normalized=[]
        for item in array:
            if item is None: normalized.append(None); continue
            if isinstance(item,bool): raise ValidationError(f"weather_{key}")
            try: number=float(item)
            except (TypeError,ValueError): raise ValidationError(f"weather_{key}") from None
            if not math.isfinite(number): raise ValidationError(f"weather_{key}")
            normalized.append(number)
        values[key]=tuple(normalized)
    return WeatherSeries(times,values,{str(k):str(v) for k,v in units.items()})

def derive_weather_windows(series: WeatherSeries, *, now: datetime) -> dict[str,float]:
    now=now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    precipitation=series.values.get("precipitation",())
    def total(start: datetime,end: datetime) -> float:
        return sum(float(v) for t,v in zip(series.times,precipitation) if v is not None and start < t <= end)
    return {
        "precipitation_6h": total(now-timedelta(hours=6),now),
        "precipitation_24h": total(now-timedelta(hours=24),now),
        "forecast_precipitation_6h": total(now,now+timedelta(hours=6)),
        "forecast_precipitation_12h": total(now,now+timedelta(hours=12)),
        "forecast_precipitation_24h": total(now,now+timedelta(hours=24)),
    }
