from __future__ import annotations

from typing import Any, Mapping

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
AIR_QUALITY_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"

# Internal collector field name -> Open-Meteo hourly variable name.
HOURLY_MAP = {
    "temperature": "temperature_2m",
    "humidity": "relative_humidity_2m",
    "precipitation": "precipitation",
    "radiation": "shortwave_radiation",
    "et0": "et0_fao_evapotranspiration",
}
DAILY_VARIABLES = (
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "sunrise",
    "sunset",
)


def forecast_url_params(request: Any) -> tuple[str, dict[str, Any]]:
    """Build the Open-Meteo Forecast API endpoint and query for a request."""
    params: dict[str, Any] = {
        "latitude": request.latitude,
        "longitude": request.longitude,
        "hourly": ",".join(HOURLY_MAP.values()),
        "past_hours": 24,
        "forecast_hours": 48,
        "timezone": "UTC",
        "temperature_unit": "celsius",
        "wind_speed_unit": "kmh",
        "precipitation_unit": "mm",
        "cell_selection": "land",
    }
    if request.profile == "outdoor":
        params["daily"] = ",".join(DAILY_VARIABLES)
        params["forecast_days"] = 7
    return FORECAST_URL, params


def map_forecast_response(body: Any, status: int) -> dict[str, Any]:
    """Convert a raw Open-Meteo forecast response into the collector shape.

    The ForecastCollector expects internal hourly field names and an embedded
    ``units`` map. Open-Meteo publishes ``temperature_2m`` style names with a
    sibling ``hourly_units`` block, so this adapter renames and lifts them.
    """
    if status >= 400 or not isinstance(body, Mapping):
        return {"status": status}
    hourly = body.get("hourly") if isinstance(body.get("hourly"), Mapping) else {}
    units = (
        body.get("hourly_units")
        if isinstance(body.get("hourly_units"), Mapping)
        else {}
    )
    mapped: dict[str, Any] = {
        "time": hourly.get("time"),
        "units": {
            internal: units.get(external)
            for internal, external in HOURLY_MAP.items()
        },
    }
    for internal, external in HOURLY_MAP.items():
        mapped[internal] = hourly.get(external)
    result: dict[str, Any] = {"status": status, "hourly": mapped}
    daily = body.get("daily")
    if isinstance(daily, Mapping):
        result["daily"] = daily
    return result


def air_quality_url_params(request: Any) -> tuple[str, dict[str, Any]]:
    """Build the Open-Meteo Air Quality API endpoint and query for a request."""
    params: dict[str, Any] = {
        "latitude": request.latitude,
        "longitude": request.longitude,
        "current": "ozone",
        "hourly": "ozone",
        "past_hours": 24,
        "forecast_hours": 48,
        "timezone": "UTC",
    }
    return AIR_QUALITY_URL, params


def map_air_quality_response(body: Any, status: int) -> dict[str, Any]:
    """Convert a raw Open-Meteo air-quality response into the collector shape."""
    if status >= 400 or not isinstance(body, Mapping):
        return {"status": status}
    current = body.get("current") if isinstance(body.get("current"), Mapping) else {}
    hourly = body.get("hourly") if isinstance(body.get("hourly"), Mapping) else {}
    return {
        "status": status,
        "current": {"ozone": current.get("ozone")},
        "hourly": {"time": hourly.get("time"), "ozone": hourly.get("ozone")},
    }
