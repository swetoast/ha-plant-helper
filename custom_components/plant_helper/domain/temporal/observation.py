"""Immutable records the temporal engine reasons over.

PlantObservation is one soil reading at a point in time. DailySummary is the
per-local-day rollup used by the multi-day light and temperature slices; the
moisture slice only needs the rolling observation window, but the dataclass
lives here so the later slices share one definition.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class PlantObservation:
    """A single soil reading. moisture is a percentage, temperature Celsius."""

    observed_at: datetime
    moisture: float | None
    soil_temperature: float | None
    moisture_valid: bool
    soil_temperature_valid: bool


@dataclass(frozen=True, slots=True)
class DailySummary:
    """Coarse rollup of one local day's valid moisture observations."""

    day: date
    min_moisture: float | None
    max_moisture: float | None
    mean_moisture: float | None
    observations: int
