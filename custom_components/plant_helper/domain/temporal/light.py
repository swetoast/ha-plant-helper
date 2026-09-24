"""Light adequacy for a plant, judged on the recent average illuminance.

Pure. A plant cares about sustained light, not a single lux spike, so the verdict
comes from the rolling mean over a day-long window. Thresholds are coarse
starting values to tune against fixtures; species-aware thresholds arrive with
learned baselines (F3). High-light flagging is deliberately conservative: without
species data, calling a plant over-lit is easy to get wrong, so the ceiling is
set where only sustained direct sun trips it.
"""
from __future__ import annotations

LIGHT_WINDOW_HOURS = 24.0
LIGHT_MIN_SAMPLES = 3
LIGHT_LOW = 400.0  # mean lux below this is under-lit for most houseplants
LIGHT_HIGH = 100000.0  # mean lux above this is sustained direct sun


def light_context(mean_lux: float | None) -> str | None:
    """Return 'low' / 'adequate' / 'high', or None when data is insufficient."""
    if mean_lux is None:
        return None
    if mean_lux < LIGHT_LOW:
        return "low"
    if mean_lux > LIGHT_HIGH:
        return "high"
    return "adequate"
