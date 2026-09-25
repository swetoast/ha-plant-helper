"""Duration tracking for a banded signal (roadmap Phase 3 duration rules).

Pure. Given one signal from the observation history and a band classifier, this
measures what the roadmap asks to track: continuous time outside the comfort
range, total exposure over the previous 24 hours, recovery time since the last
excursion, rate of change, and measurement gaps. Readings are time-weighted with
sample-and-hold, so a steady sensor that reports rarely still counts correctly,
while a hold longer than MAX_HOLD_HOURS is treated as missing data, not as a
continuation.

A band classifier maps a value to (direction, severity): direction is None
(comfortable), "low" or "high"; severity is 1 (mild) or 2 (extreme).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable

from .history import ObservationHistory

MAX_HOLD_HOURS = 2.0
WINDOW_HOURS = 24.0
RATE_MIN_MINUTES = 45.0
RATE_MAX_MINUTES = 120.0

Band = tuple[str | None, int]


@dataclass(frozen=True, slots=True)
class ExposureReport:
    value: float | None
    direction: str | None
    severity: int
    run_since: datetime | None
    continuous_hours: float
    low_hours_24h: float
    high_hours_24h: float
    in_range_hours: float
    rate_per_hour: float | None
    gap_hours_24h: float

    @property
    def has_data(self) -> bool:
        return self.value is not None


def track_exposure(
    history: ObservationHistory,
    attr: str,
    valid_attr: str,
    now: datetime,
    classify: Callable[[float], Band],
) -> ExposureReport:
    start = now - timedelta(hours=history_span_hours(history, now))
    pieces = history.segments(
        attr, valid_attr, start, now, max_hold_hours=MAX_HOLD_HOURS
    )
    window_start = now - timedelta(hours=WINDOW_HOURS)
    low_h = high_h = covered_h = 0.0
    for a, b, value, _daylight in pieces:
        if value is None:
            continue
        a2 = max(a, window_start)
        if b <= a2:
            continue
        hours = (b - a2).total_seconds() / 3600.0
        covered_h += hours
        direction, _severity = classify(value)
        if direction == "low":
            low_h += hours
        elif direction == "high":
            high_h += hours

    points = history.points(attr, valid_attr)
    if not points or not pieces or pieces[-1][2] is None or pieces[-1][1] < now:
        # No current valid reading (none at all, invalid now, or held too long).
        return ExposureReport(
            None, None, 0, None, 0.0, low_h, high_h, 0.0, None,
            max(0.0, WINDOW_HOURS - covered_h),
        )

    value = pieces[-1][2]
    direction, severity = classify(value)
    run_start = _run_start(pieces, classify, direction)
    run_hours = (now - run_start).total_seconds() / 3600.0
    return ExposureReport(
        value=value,
        direction=direction,
        severity=severity if direction else 0,
        run_since=run_start if direction else None,
        continuous_hours=run_hours if direction else 0.0,
        low_hours_24h=low_h,
        high_hours_24h=high_h,
        in_range_hours=0.0 if direction else run_hours,
        rate_per_hour=_rate(points, now),
        gap_hours_24h=max(0.0, WINDOW_HOURS - covered_h),
    )


def history_span_hours(history: ObservationHistory, now: datetime) -> float:
    observations = history.observations
    if not observations:
        return 0.0
    return max(0.0, (now - observations[0].observed_at).total_seconds() / 3600.0)


def _run_start(pieces, classify, direction) -> datetime:
    """Start of the newest contiguous run with the same direction."""
    start = pieces[-1][0]
    for index in range(len(pieces) - 1, -1, -1):
        a, b, value, _daylight = pieces[index]
        if value is None or classify(value)[0] != direction:
            break
        if index < len(pieces) - 1 and b < pieces[index + 1][0]:
            break  # uncovered gap between readings ends the run
        start = a
    return start


def _rate(points: list[tuple[datetime, float]], now: datetime) -> float | None:
    """Change per hour between the latest reading and one ~1 hour earlier."""
    latest_t, latest_v = points[-1]
    for t, v in reversed(points[:-1]):
        age = (latest_t - t).total_seconds() / 60.0
        if age < RATE_MIN_MINUTES:
            continue
        if age > RATE_MAX_MINUTES:
            return None
        return (latest_v - v) / (age / 60.0)
    return None
