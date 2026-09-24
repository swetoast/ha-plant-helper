"""Ambient humidity adequacy for a plant, from the recent rolling mean.

Pure. Humidity moves faster than light, so the window is shorter. Thresholds are
starting values to tune against fixtures; most foliage plants sit comfortably in
the 40-60% range, so below 30% reads dry and above 70% reads damp.
"""
from __future__ import annotations

HUMIDITY_WINDOW_HOURS = 6.0
HUMIDITY_MIN_SAMPLES = 3
HUMIDITY_LOW = 30.0
HUMIDITY_HIGH = 70.0


def humidity_context(mean_humidity: float | None) -> str | None:
    """Return 'low' / 'adequate' / 'high', or None when data is insufficient."""
    if mean_humidity is None:
        return None
    if mean_humidity < HUMIDITY_LOW:
        return "low"
    if mean_humidity > HUMIDITY_HIGH:
        return "high"
    return "adequate"
