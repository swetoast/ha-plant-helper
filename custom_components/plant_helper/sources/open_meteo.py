"""Open-Meteo global outdoor-context adapter.

The adapter normalizes Open-Meteo data into the existing ForecastHour contract
and a provider-neutral OutdoorContext. Modelled soil values are exposed only as
regional diagnostics and never replace a plant's local sensors.
"""
from __future__ import annotations
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Mapping
from ..engine.thermal_model import ForecastHour
from ..engine.util import parse_iso, to_float

BASE_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARIABLES = (
    "temperature_2m", "relative_humidity_2m", "precipitation_probability",
    "precipitation", "weather_code", "cloud_cover", "wind_gusts_10m",
    "et0_fao_evapotranspiration", "vapour_pressure_deficit",
    "shortwave_radiation", "diffuse_radiation", "soil_temperature_6cm",
    "soil_moisture_3_to_9cm",
)
WMO_CONDITIONS = {
    0: "sunny", 1: "partlycloudy", 2: "partlycloudy", 3: "cloudy",
    45: "fog", 48: "fog", 51: "rainy", 53: "rainy", 55: "pouring",
    56: "snowy-rainy", 57: "snowy-rainy", 61: "rainy", 63: "rainy",
    65: "pouring", 66: "snowy-rainy", 67: "snowy-rainy", 71: "snowy",
    73: "snowy", 75: "snowy", 77: "snowy", 80: "rainy", 81: "rainy",
    82: "pouring", 85: "snowy", 86: "snowy", 95: "lightning-rainy",
    96: "hail", 99: "hail",
}

@dataclass(frozen=True, slots=True)
class OutdoorContext:
    source: str
    fetched_at: datetime
    forecast: list[ForecastHour]
    et0_next_24h_mm: float | None
    vpd_next_24h_mean_kpa: float | None
    precipitation_probability_max_24h: float | None
    temperature_2m: float | None
    relative_humidity_2m: float | None
    cloud_cover: float | None
    shortwave_radiation: float | None
    diffuse_radiation: float | None
    soil_temperature_6cm: float | None
    regional_soil_moisture_3_to_9cm: float | None
    estimated_par_series: list[tuple[datetime, float]]
    outdoor_lux_series: list[tuple[datetime, float]]


def _series(hourly: Mapping[str, Any], key: str) -> list[Any]:
    value = hourly.get(key)
    return value if isinstance(value, list) else []


def _at(values: list[Any], index: int) -> float | None:
    return to_float(values[index]) if index < len(values) else None


def _aggregate(values: list[Any], start: int, count: int, *, mode: str) -> float | None:
    nums = [to_float(v) for v in values[start:start + count]]
    usable = [v for v in nums if v is not None]
    if not usable:
        return None
    return max(usable) if mode == "max" else sum(usable) if mode == "sum" else sum(usable) / len(usable)




SHORTWAVE_TO_PAR = 0.45
SHORTWAVE_TO_LUX = 120.0


def radiation_series(hourly: Mapping[str, Any]) -> tuple[
    list[tuple[datetime, float]], list[tuple[datetime, float]]
]:
    """Convert Open-Meteo shortwave history to estimated PAR and outdoor lux.

    The 45% PAR share is an approximation and is deliberately identified as
    estimated data. Returning independent timestamped series allows callers to
    keep complete DLI days locked to one provider.
    """
    times = _series(hourly, "time")
    shortwave = _series(hourly, "shortwave_radiation")
    par: list[tuple[datetime, float]] = []
    lux: list[tuple[datetime, float]] = []
    for index, raw_ts in enumerate(times):
        ts = parse_iso(raw_ts)
        value = _at(shortwave, index)
        if ts is None or value is None or value < 0:
            continue
        par.append((ts, value * SHORTWAVE_TO_PAR))
        lux.append((ts, value * SHORTWAVE_TO_LUX))
    return par, lux


def parse_response(payload: Any, now: datetime) -> OutdoorContext | None:
    """Normalize one Open-Meteo response; malformed payloads return None."""
    if not isinstance(payload, Mapping) or payload.get("error"):
        return None
    hourly = payload.get("hourly")
    if not isinstance(hourly, Mapping):
        return None
    times = _series(hourly, "time")
    parsed = [parse_iso(value) for value in times]
    valid = [(i, ts) for i, ts in enumerate(parsed) if ts is not None]
    if not valid:
        return None
    comparable_now = now.replace(tzinfo=None) if now.tzinfo else now
    current_index = min(valid, key=lambda item: abs((item[1].replace(tzinfo=None) - comparable_now).total_seconds()))[0]
    forecast: list[ForecastHour] = []
    codes = _series(hourly, "weather_code")
    gusts = _series(hourly, "wind_gusts_10m")
    precip = _series(hourly, "precipitation")
    precip_probability = _series(hourly, "precipitation_probability")
    for i, ts in valid:
        hours = (ts.replace(tzinfo=None) - comparable_now).total_seconds() / 3600.0
        if hours < -1 or hours > 48:
            continue
        code = _at(codes, i)
        forecast.append(ForecastHour(
            hours_ahead=round(hours, 3),
            condition=WMO_CONDITIONS.get(int(code), "unknown") if code is not None else "unknown",
            wind_gust_kmh=_at(gusts, i), precipitation_mm=_at(precip, i),
            precipitation_probability=_at(precip_probability, i),
        ))
    estimated_par_series, outdoor_lux_series = radiation_series(hourly)
    return OutdoorContext(
        source="open_meteo", fetched_at=now, forecast=forecast,
        et0_next_24h_mm=_aggregate(_series(hourly, "et0_fao_evapotranspiration"), current_index, 24, mode="sum"),
        vpd_next_24h_mean_kpa=_aggregate(_series(hourly, "vapour_pressure_deficit"), current_index, 24, mode="mean"),
        precipitation_probability_max_24h=_aggregate(_series(hourly, "precipitation_probability"), current_index, 24, mode="max"),
        temperature_2m=_at(_series(hourly, "temperature_2m"), current_index),
        relative_humidity_2m=_at(_series(hourly, "relative_humidity_2m"), current_index),
        cloud_cover=_at(_series(hourly, "cloud_cover"), current_index),
        shortwave_radiation=_at(_series(hourly, "shortwave_radiation"), current_index),
        diffuse_radiation=_at(_series(hourly, "diffuse_radiation"), current_index),
        soil_temperature_6cm=_at(_series(hourly, "soil_temperature_6cm"), current_index),
        regional_soil_moisture_3_to_9cm=_at(_series(hourly, "soil_moisture_3_to_9cm"), current_index),
        estimated_par_series=estimated_par_series,
        outdoor_lux_series=outdoor_lux_series,
    )


async def fetch_context(session: Any, latitude: float, longitude: float, now: datetime) -> OutdoorContext | None:
    """Fetch one shared location context. Returns None on transport/API failure."""
    params = {
        "latitude": latitude, "longitude": longitude,
        "hourly": ",".join(HOURLY_VARIABLES), "forecast_days": 3,
        "timezone": "auto", "wind_speed_unit": "kmh", "precipitation_unit": "mm",
    }
    try:
        import aiohttp
        async with session.get(BASE_URL, params=params, timeout=aiohttp.ClientTimeout(total=15)) as response:
            if response.status != 200:
                return None
            return parse_response(await response.json(content_type=None), now)
    except Exception:
        return None
