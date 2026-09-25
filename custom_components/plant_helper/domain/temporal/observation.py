"""Immutable observation record the temporal engine reasons over.

One PlantObservation is a snapshot of every configured physical signal at a
point in time, plus the daylight classification in force when it was taken.
``soil_temperature`` is the plant's temperature sensor (the roadmap's local
temperature); the field keeps its stored name for restore compatibility.

``is_daylight`` has three states: True, False, and None (unknown). Unknown must
never be treated as nighttime.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

DAYLIGHT_UNKNOWN_SOURCE = "unknown"


@dataclass(frozen=True, slots=True)
class PlantObservation:
    observed_at: datetime
    moisture: float | None
    soil_temperature: float | None
    moisture_valid: bool
    soil_temperature_valid: bool
    light: float | None = None
    humidity: float | None = None
    light_valid: bool = False
    humidity_valid: bool = False
    is_daylight: bool | None = None
    daylight_source: str = DAYLIGHT_UNKNOWN_SOURCE
