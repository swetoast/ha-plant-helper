"""Single source of truth for the temporal engine's status vocabulary.

The moisture engine already returns one status per evaluation; this module
keeps the string constants, the health mapping, the attention set, and the
deterministic precedence ordering in one place so later slices (light,
temperature, multi-signal precedence) never diverge from it.
"""
from __future__ import annotations

from typing import Iterable

# Status strings written to sensor.<plant>_status (the care_status entity).
WAITING_FOR_DATA = "waiting_for_data"
NORMAL = "normal"
RECENTLY_WATERED = "recently_watered"
WET = "wet"
STAYING_WET = "staying_wet"
TOO_WET = "too_wet"
DRYING = "drying"
APPROACHING_DRY = "approaching_dry"
NEEDS_WATER = "needs_water"
TOO_DRY = "too_dry"
WATERING_PAUSED = "watering_paused"
SENSOR_PROBLEM = "sensor_problem"

# Health strings written to sensor.<plant>_health. Coarser than status.
HEALTH_UNKNOWN = "unknown"
HEALTH_GOOD = "good"
HEALTH_WATCH = "watch"
HEALTH_NEEDS_WATER = "needs_water"
HEALTH_TOO_WET = "too_wet"
HEALTH_TOO_DRY = "too_dry"

# Statuses that raise binary_sensor.<plant>_needs_attention.
ATTENTION_STATUSES = frozenset({TOO_WET, NEEDS_WATER, TOO_DRY, SENSOR_PROBLEM})

# Deterministic precedence, most urgent first. When several signals compete in
# later slices, worst_of() picks the status a user needs to see.
STATUS_PRECEDENCE = (
    SENSOR_PROBLEM,
    TOO_DRY,
    NEEDS_WATER,
    TOO_WET,
    STAYING_WET,
    WATERING_PAUSED,
    APPROACHING_DRY,
    DRYING,
    WET,
    RECENTLY_WATERED,
    NORMAL,
    WAITING_FOR_DATA,
)

_RANK = {status: index for index, status in enumerate(STATUS_PRECEDENCE)}


def raises_attention(status: str) -> bool:
    """True when the status should set needs_attention."""
    return status in ATTENTION_STATUSES


def worst_of(statuses: Iterable[str]) -> str:
    """Return the highest-precedence (most urgent) status in the set.

    Unknown statuses rank last so a typo never masks a real signal.
    """
    ordered = [status for status in statuses if status in _RANK]
    if not ordered:
        return NORMAL
    return min(ordered, key=lambda status: _RANK[status])
