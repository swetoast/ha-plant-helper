"""Moisture sensor problems (roadmap Phase 2 ``sensor_problem``).

Pure. The moisture sensor is the primary signal, so two failures are reported:
it has been unavailable or invalid for UNAVAILABLE_HOURS, or it looks frozen.
A frozen device repeats its last state forever, so it is only called frozen when
moisture AND every other reported signal (temperature, humidity) stayed exactly
flat across STUCK_DAYS fully covered days. Moisture alone can legitimately sit on
one integer percentage for days while a resting plant dries slowly; real
temperature and humidity never hold perfectly still for that long. Missing
optional sensors are not problems; they only lower confidence elsewhere.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .daily import DailySummary
from .history import ObservationHistory

UNAVAILABLE_HOURS = 6.0
STUCK_DAYS = 5
STUCK_COVERAGE_HOURS = 20.0
STUCK_SPREAD = 0.1


@dataclass(frozen=True, slots=True)
class SensorAssessment:
    problem: bool
    reason: str | None
    summary: str | None
    since: datetime | None


def assess_sensor(
    history: ObservationHistory, days: Sequence[DailySummary], now: datetime
) -> SensorAssessment:
    observations = history.observations
    if observations and not observations[-1].moisture_valid:
        last_valid = history.latest_valid()
        after = [
            o for o in observations
            if last_valid is None or o.observed_at > last_valid.observed_at
        ]
        since = after[0].observed_at
        if now - since >= timedelta(hours=UNAVAILABLE_HOURS):
            return SensorAssessment(
                True, "sensor_unavailable",
                "The soil moisture sensor has not reported a valid reading for hours",
                since,
            )
    recent = list(days)[-STUCK_DAYS:]
    if len(recent) == STUCK_DAYS and all(
        d.moisture_coverage_hours >= STUCK_COVERAGE_HOURS
        and d.moisture_min is not None
        and d.moisture_max is not None
        for d in recent
    ):
        if all(
            _flat(recent, low, high)
            for low, high in (
                ("moisture_min", "moisture_max"),
                ("temperature_min", "temperature_max"),
                ("humidity_min", "humidity_max"),
            )
        ):
            return SensorAssessment(
                True, "stuck_reading",
                "The soil moisture sensor has reported the same value for days",
                None,
            )
    return SensorAssessment(False, None, None, None)


def _flat(days: Sequence[DailySummary], low: str, high: str) -> bool:
    """True when a signal held one value across the days (or was never reported)."""
    values = [
        value
        for d in days
        for value in (getattr(d, low), getattr(d, high))
        if value is not None
    ]
    return not values or max(values) - min(values) <= STUCK_SPREAD
