from __future__ import annotations
from dataclasses import dataclass, replace
import math
import uuid
from typing import Any, Mapping

class ValidationError(ValueError):
    def __init__(self, key: str):
        super().__init__(key)
        self.key = key

def _finite_float(value: Any, key: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool): raise ValidationError(key)
    try: result=float(value)
    except (TypeError, ValueError): raise ValidationError(key) from None
    if not math.isfinite(result) or not minimum <= result <= maximum: raise ValidationError(key)
    return result

def _optional_secret(value: Any, key: str) -> str | None:
    if value is None: return None
    if not isinstance(value,str): raise ValidationError(key)
    result=value.strip()
    return result or None

def _optional_entity(value: Any, key: str, domain: str="sensor") -> str | None:
    if value in (None,""): return None
    if not isinstance(value,str) or not value.startswith(f"{domain}.") or value.count(".") != 1: raise ValidationError(key)
    return value

@dataclass(frozen=True, slots=True)
class GlobalSettings:
    perenual_access_level: str = "free"
    update_interval: int = 300
    latitude: float | None = None
    longitude: float | None = None
    perenual_api_key: str | None = None
    trefle_api_key: str | None = None

    @classmethod
    def normalize(cls, raw: Mapping[str, Any]) -> "GlobalSettings":
        access=raw.get("perenual_access_level","free")
        if access not in {"free","paid"}: raise ValidationError("perenual_access_level")
        interval=raw.get("update_interval",300)
        if isinstance(interval,bool): raise ValidationError("update_interval")
        try: interval=int(interval)
        except (TypeError,ValueError): raise ValidationError("update_interval") from None
        if not 60 <= interval <= 3600: raise ValidationError("update_interval")
        lat=None if raw.get("latitude") in (None,"") else _finite_float(raw["latitude"],"latitude",-90,90)
        lon=None if raw.get("longitude") in (None,"") else _finite_float(raw["longitude"],"longitude",-180,180)
        return cls(access, interval, lat, lon, _optional_secret(raw.get("perenual_api_key"),"perenual_api_key"), _optional_secret(raw.get("trefle_api_key"),"trefle_api_key"))

    def to_options(self) -> dict[str, Any]:
        result={"perenual_access_level":self.perenual_access_level,"update_interval":self.update_interval}
        for key in ("latitude","longitude","perenual_api_key","trefle_api_key"):
            value=getattr(self,key)
            if value is not None: result[key]=value
        return result

@dataclass(frozen=True, slots=True)
class PlantConfig:
    plant_uuid: str
    revision: int
    display_name: str
    soil_moisture: str
    placement: str
    profile: str
    species: str | None = None
    soil_temperature: str | None = None
    humidity_sensor: str | None = None
    lux: str | None = None
    battery: str | None = None
    custom_multiplier: float | None = None
    rain_limit_mm: float | None = None

    @classmethod
    def normalize(cls, raw: Mapping[str, Any], *, plant_uuid: str, revision: int=1) -> "PlantConfig":
        name=str(raw.get("display_name","")).strip()
        if not name: raise ValidationError("name_required")
        moisture=_optional_entity(raw.get("soil_moisture"),"moisture_required")
        if moisture is None: raise ValidationError("moisture_required")
        placement=raw.get("placement")
        if placement not in {"indoor","outdoor"}: raise ValidationError("placement")
        profile=raw.get("profile","balanced")
        if profile not in {"dry","balanced","moist","custom"}: raise ValidationError("profile")
        multiplier=None
        if profile=="custom": multiplier=_finite_float(raw.get("custom_multiplier"),"custom_multiplier_range",0.25,4.0)
        rain=None
        if placement=="outdoor": rain=_finite_float(raw.get("rain_limit_mm"),"rain_limit_mm",0,1000)
        species=raw.get("species")
        if species is not None:
            if not isinstance(species,str): raise ValidationError("species")
            species=species.strip() or None
        return cls(plant_uuid,revision,name,moisture,placement,profile,species,
            _optional_entity(raw.get("soil_temperature"),"soil_temperature"),
            _optional_entity(raw.get("humidity_sensor"),"humidity_sensor"),
            _optional_entity(raw.get("lux"),"lux"),
            _optional_entity(raw.get("battery"),"battery"),multiplier,rain)

def new_plant_uuid() -> str:
    return uuid.uuid4().hex

def replace_editable(current: PlantConfig, raw: Mapping[str, Any]) -> PlantConfig:
    return PlantConfig.normalize(raw, plant_uuid=current.plant_uuid, revision=current.revision+1)
