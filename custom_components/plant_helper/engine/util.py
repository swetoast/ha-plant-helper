"""Small shared helpers used across the engine and the source adapters.

Consolidates the datetime and float coercion helpers that had been copied into
several modules (validation, sources/forecast, sources/smhi, runtime,
sample_store).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any


def to_float(value: Any) -> float | None:
    """Coerce a value to float, returning None on missing/invalid input."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_iso(value: Any) -> datetime | None:
    """Parse an ISO-8601 timestamp (tolerating a trailing 'Z'), else None."""
    if isinstance(value, datetime):
        return value
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def daylight_hours(next_rising, next_setting) -> float | None:
    """Astronomical daylight length (hours) from sun.sun's next rising/setting.

    Works at any time of day: when the next setting is after the next rising we
    are before dawn (both events lie in today), so daylight = setting - rising.
    When the next rising is after the next setting we are in daytime (the next
    rising is tomorrow), so daylight = 24h - the intervening night. Clamped to
    [0, 24]; None if either event is missing (e.g. polar day/night).
    """
    if next_rising is None or next_setting is None:
        return None
    if next_setting >= next_rising:
        hrs = (next_setting - next_rising).total_seconds() / 3600.0
    else:
        night = (next_rising - next_setting).total_seconds() / 3600.0
        hrs = 24.0 - night
    return round(max(0.0, min(24.0, hrs)), 2)
