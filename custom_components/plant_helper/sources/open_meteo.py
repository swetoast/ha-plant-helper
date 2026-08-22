"""Open-Meteo regional plant-environment context source."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any
from aiohttp import ClientError, ClientSession

API_URL = "https://api.open-meteo.com/v1/forecast"
HOURLY_VARIABLES = (
    "temperature_2m", "relative_humidity_2m", "precipitation",
    "precipitation_probability", "et0_fao_evapotranspiration",
    "vapour_pressure_deficit", "shortwave_radiation", "wind_speed_10m",
    "wind_gusts_10m", "soil_temperature_6cm",
    "soil_moisture_3_to_9cm", "soil_moisture_9_to_27cm",
)

@dataclass(frozen=True, slots=True)
class PlantEnvironment:
    """Current regional plant-environment context."""
    observed_at: str | None
    values: dict[str, float | int | None]
    units: dict[str, str]
    source: str = "Open-Meteo"

    def attributes(self) -> dict[str, Any]:
        return {"source": self.source, "observed_at": self.observed_at,
                **self.values, "units": self.units}

async def async_fetch(session: ClientSession, latitude: float, longitude: float) -> PlantEnvironment:
    """Fetch current values for the configured Home Assistant location."""
    params = {"latitude": latitude, "longitude": longitude,
              "current": ",".join(HOURLY_VARIABLES), "timezone": "auto",
              "forecast_days": 1}
    try:
        async with session.get(API_URL, params=params, timeout=30) as response:
            response.raise_for_status()
            payload = await response.json()
    except (ClientError, TimeoutError, ValueError, TypeError) as err:
        raise RuntimeError(f"Open-Meteo plant context failed: {err}") from err
    current = payload.get("current")
    if not isinstance(current, dict):
        raise RuntimeError("Open-Meteo plant context response has no current data")
    units = payload.get("current_units")
    if not isinstance(units, dict):
        units = {}
    return PlantEnvironment(current.get("time"),
        {key: current.get(key) for key in HOURLY_VARIABLES},
        {key: str(value) for key, value in units.items() if key != "time"})
