"""Status, health and attention vocabulary, and the combined precedence.

Pure. Every signal engine (moisture, temperature, light, sensor health) reports
one candidate status; the combined engine picks the one a user needs to see with
worst_of(), using the deterministic precedence from roadmap Phase 5. Health is
the longer-term verdict and uses the roadmap's four states only.
"""
from __future__ import annotations

from typing import Iterable

# Status strings written to sensor.<plant>_status (the care_status entity).
WAITING_FOR_DATA = "waiting_for_data"
NORMAL = "normal"
RECENTLY_WATERED = "recently_watered"
PARTIAL_WATERING = "partial_watering"
WET = "wet"
STAYING_WET = "staying_wet"
TOO_WET = "too_wet"
DRYING = "drying"
APPROACHING_DRY = "approaching_dry"
NEEDS_WATER = "needs_water"
TOO_DRY = "too_dry"
WATERING_PAUSED = "watering_paused"
TOO_COLD = "too_cold"
TOO_HOT = "too_hot"
INSUFFICIENT_LIGHT = "insufficient_light"
SENSOR_PROBLEM = "sensor_problem"

# Health strings written to sensor.<plant>_health (roadmap section 13).
HEALTH_UNKNOWN = "unknown"
HEALTH_GOOD = "good"
HEALTH_WATCH = "watch"
HEALTH_STRESSED = "stressed"

# Deterministic precedence, most urgent first (roadmap Phase 5). The moisture
# statuses are mutually exclusive with each other, so their relative order only
# matters against the temperature, light and sensor statuses.
STATUS_PRECEDENCE = (
    SENSOR_PROBLEM,
    NEEDS_WATER,
    TOO_DRY,
    WATERING_PAUSED,
    TOO_WET,
    STAYING_WET,
    RECENTLY_WATERED,
    PARTIAL_WATERING,
    DRYING,
    APPROACHING_DRY,
    TOO_COLD,
    TOO_HOT,
    INSUFFICIENT_LIGHT,
    WET,
    NORMAL,
    WAITING_FOR_DATA,
)
_RANK = {status: index for index, status in enumerate(STATUS_PRECEDENCE)}

_HEALTH_RANK = {
    HEALTH_GOOD: 0,
    HEALTH_WATCH: 1,
    HEALTH_STRESSED: 2,
}

# Reasons that turn binary_sensor.<plant>_needs_attention on (roadmap Phase 5).
# Only sustained, actionable conditions belong here.
ATTENTION_REASONS = frozenset(
    {
        "soil_dry",
        "persistently_dry",
        "persistently_wet",
        "prolonged_temperature_stress",
        "several_days_insufficient_light",
        "sensor_problem",
    }
)


def worst_of(statuses: Iterable[str | None]) -> str:
    """Return the most urgent known status; unknown strings rank last."""
    ordered = [status for status in statuses if status in _RANK]
    if not ordered:
        return NORMAL
    return min(ordered, key=lambda status: _RANK[status])


def worst_health(values: Iterable[str | None]) -> str:
    """Combine health verdicts; unknown only wins when nothing else is known."""
    known = [value for value in values if value in _HEALTH_RANK]
    if not known:
        return HEALTH_UNKNOWN
    return max(known, key=lambda value: _HEALTH_RANK[value])
