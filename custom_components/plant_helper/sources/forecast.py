"""Forecast source adapter (design.md forward-looking layer).

`weather.get_forecasts` returns an hourly array; `parse_forecast` turns it into
the engine's `ForecastHour` list (pure, tested). `async_fetch_forecast` is the
thin Home Assistant wrapper — HA is imported lazily inside it so this module can
be imported and unit-tested without Home Assistant present.

Design failover: an empty / errored forecast is treated as *no imminent
precipitation* and the engine simply falls back to reactive tracking. We never
fabricate rain that would wrongly suppress a watering alert.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Sequence

from ..engine.thermal_model import ForecastHour
from ..engine.util import to_float, parse_iso

# Tolerant key lookup — real integrations vary in naming.
_CONDITION_KEYS = ("condition", "weather", "state")
_GUST_KEYS = ("wind_gust_speed", "wind_gust", "gust_speed", "wind_gust_kmh")
_PRECIP_KEYS = ("precipitation", "precip", "rain")
_PRECIP_PROBABILITY_KEYS = ("precipitation_probability", "precipitation_probability_percent", "rain_probability")
_TIME_KEYS = ("datetime", "time", "timestamp")


def _first(d: dict[str, Any], keys: Sequence[str]) -> Any:
    for k in keys:
        if k in d and d[k] is not None:
            return d[k]
    return None


def _parse_entries(entries: Any, now: datetime) -> list[ForecastHour]:
    """Parse a raw forecast entry list into ForecastHour items."""
    if not isinstance(entries, list):
        return []
    out: list[ForecastHour] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        ts = parse_iso(_first(entry, _TIME_KEYS))
        if ts is None:
            continue
        if ts.tzinfo is not None and now.tzinfo is not None:
            hours_ahead = (ts - now).total_seconds() / 3600.0
        else:
            hours_ahead = (
                ts.replace(tzinfo=None) - now.replace(tzinfo=None)
            ).total_seconds() / 3600.0
        if hours_ahead < -1.0:
            continue
        condition = _first(entry, _CONDITION_KEYS)
        gust = _first(entry, _GUST_KEYS)
        precip = _first(entry, _PRECIP_KEYS)
        precip_probability = _first(entry, _PRECIP_PROBABILITY_KEYS)
        out.append(
            ForecastHour(
                hours_ahead=round(hours_ahead, 3),
                condition=str(condition).lower() if condition is not None else "",
                wind_gust_kmh=to_float(gust),
                precipitation_mm=to_float(precip),
                precipitation_probability=to_float(precip_probability),
            )
        )
    out.sort(key=lambda f: f.hours_ahead)
    return out


def parse_forecast(
    response: Any,
    entity_id: str,
    now: datetime,
) -> list[ForecastHour]:
    """Parse a `weather.get_forecasts` service response.

    `response` is {entity_id: {"forecast": [ ... ]}}. Any structural surprise
    yields an empty list (reactive-tracking fallback), never an exception.
    """
    if not isinstance(response, dict):
        return []
    block = response.get(entity_id) or {}
    entries = block.get("forecast") if isinstance(block, dict) else None
    return _parse_entries(entries, now)


def parse_forecast_from_attributes(
    attributes: Any,
    now: datetime,
) -> list[ForecastHour]:
    """Parse a forecast carried on an entity's `forecast` attribute.

    Some setups expose the hourly array on a `sensor.*` entity attribute rather
    than via `weather.get_forecasts` (e.g. a combined weather sensor).
    """
    if not isinstance(attributes, Mapping):
        return []
    return _parse_entries(attributes.get("forecast"), now)


async def async_fetch_forecast(
    hass: Any,
    entity_id: str,
    now: datetime,
    *,
    forecast_type: str = "hourly",
) -> list[ForecastHour]:
    """Fetch and parse a forecast. Returns [] on any failure.

    For a `weather.*` entity, calls `weather.get_forecasts`. For any other
    domain (e.g. a `sensor.*` combined-weather entity), reads the `forecast`
    attribute directly.
    """
    import logging

    logger = logging.getLogger(__name__)
    domain = entity_id.split(".", 1)[0]

    if domain == "weather":
        try:
            response = await hass.services.async_call(
                "weather",
                "get_forecasts",
                {"type": forecast_type, "entity_id": entity_id},
                blocking=True,
                return_response=True,
            )
        except Exception:  # noqa: BLE001 - forecast is best-effort
            logger.debug("weather.get_forecasts failed for %s", entity_id, exc_info=True)
            return []
        return parse_forecast(response, entity_id, now)

    # Attribute-based forecast (sensor.* combined weather entity).
    state = hass.states.get(entity_id)
    if state is None:
        return []
    return parse_forecast_from_attributes(getattr(state, "attributes", {}) or {}, now)
