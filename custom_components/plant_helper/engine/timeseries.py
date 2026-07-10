"""Rolling windows, trends, and duration tracking (design.md section 3).

All built on the gap-aware accumulator, so windows and trends are computed only
over valid data and never span a hole. Consumed by the moisture / light /
thermal / dormancy models.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Callable, Sequence

from .accumulator import (
    Sample,
    coverage_ratio,
    extent,
    time_weighted_mean,
    valid_intervals,
    window,
)

RISING = "rising"
FALLING = "falling"
FLAT = "flat"


def windowed_mean(
    samples: Sequence[Sample],
    now: datetime,
    span: timedelta,
    max_gap: timedelta,
) -> float | None:
    """Duration-weighted mean over the trailing window."""
    return time_weighted_mean(window(samples, now, span), max_gap)


@dataclass(frozen=True, slots=True)
class TrendResult:
    mean: float | None
    slope_per_day: float | None   # least-squares slope of value vs time
    direction: str                # RISING | FALLING | FLAT
    coverage: float               # fraction of window covered by valid data
    n: int                        # usable sample count


def trend(
    samples: Sequence[Sample],
    now: datetime,
    span: timedelta,
    max_gap: timedelta,
    *,
    flat_slope_per_day: float = 0.0,
) -> TrendResult:
    """Least-squares trend of a quantity over a trailing window.

    `flat_slope_per_day` is the magnitude below which a slope is reported as
    FLAT (per-quantity noise floor). Returns coverage so callers can discount a
    trend built on sparse data.
    """
    win = [s for s in window(samples, now, span) if s.usable]
    cov = coverage_ratio(samples, now, span, max_gap)
    n = len(win)
    if n == 0:
        return TrendResult(None, None, FLAT, cov, 0)

    mean_v = sum(s.value for s in win) / n
    if n == 1:
        return TrendResult(mean_v, 0.0, FLAT, cov, 1)

    # x in days relative to window start; least-squares slope.
    t0 = win[0].ts
    xs = [(s.ts - t0).total_seconds() / 86400.0 for s in win]
    ys = [s.value for s in win]
    mx = sum(xs) / n
    my = sum(ys) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return TrendResult(mean_v, 0.0, FLAT, cov, n)
    slope = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / denom

    if slope > flat_slope_per_day:
        direction = RISING
    elif slope < -flat_slope_per_day:
        direction = FALLING
    else:
        direction = FLAT
    return TrendResult(mean_v, slope, direction, cov, n)


def min_max(
    samples: Sequence[Sample],
    now: datetime,
    span: timedelta,
) -> tuple[float | None, float | None]:
    """(min, max) of usable values over the trailing window."""
    return extent(window(samples, now, span))


def duration_where(
    samples: Sequence[Sample],
    max_gap: timedelta,
    predicate: Callable[[float], bool],
) -> float:
    """Total minutes (over valid intervals) whose start value matches predicate."""
    return sum(
        iv.minutes for iv in valid_intervals(samples, max_gap) if predicate(iv.start.value)
    )


def current_run_minutes(
    samples: Sequence[Sample],
    max_gap: timedelta,
    predicate: Callable[[float], bool],
) -> float:
    """Length (minutes) of the newest contiguous run satisfying `predicate`.

    Walks intervals backward from the most recent; stops at the first interval
    whose end value fails the predicate. Used for "dry_too_long",
    "cold_too_long" style state timers. A hole ends the run (we cannot claim the
    condition held across unobserved time).
    """
    ivs = list(valid_intervals(samples, max_gap))
    if not ivs:
        return 0.0
    # The most recent reading must itself satisfy the predicate.
    if not predicate(ivs[-1].end.value):
        return 0.0
    total = 0.0
    for iv in reversed(ivs):
        if predicate(iv.end.value) and predicate(iv.start.value):
            total += iv.minutes
        else:
            break
    return total


@dataclass(frozen=True, slots=True)
class StepEvent:
    ts: datetime
    magnitude: float          # net rise across the step
    kind: str                 # "sharp" | "creep"


def detect_sustained_step(
    samples: Sequence[Sample],
    max_gap: timedelta,
    *,
    sharp_delta: float,
    creep_delta: float,
    creep_window: timedelta,
    persistence: timedelta,
) -> list[StepEvent]:
    """Detect upward steps that persist (watering-style events).

    A *sharp* step: a single interval rises by >= `sharp_delta` and the level
    does not fall back below the pre-step value within `persistence`.
    A *creep*: cumulative rise over `creep_window` reaches >= `creep_delta`
    while staying monotonic-ish (used for slow bottom-watering wicking).

    Generic here; the moisture model supplies the thresholds and consumes the
    events. Returns events oldest-first.
    """
    usable = [s for s in sorted(samples, key=lambda s: s.ts) if s.usable]
    events: list[StepEvent] = []
    if len(usable) < 2:
        return events

    # Sharp steps -----------------------------------------------------------
    for i in range(1, len(usable)):
        prev, cur = usable[i - 1], usable[i]
        if (cur.ts - prev.ts) > max_gap:
            continue
        rise = cur.value - prev.value
        if rise < sharp_delta:
            continue
        # Persistence: no reading within `persistence` after `cur` drops back
        # below the pre-step baseline.
        horizon = cur.ts + persistence
        reverted = any(
            s.ts <= horizon and s.value < prev.value
            for s in usable[i + 1 :]
        )
        if not reverted:
            events.append(StepEvent(cur.ts, rise, "sharp"))

    # Creeps ----------------------------------------------------------------
    for i in range(len(usable)):
        anchor = usable[i]
        lo = anchor.ts - creep_window
        segment = [s for s in usable[: i + 1] if s.ts >= lo]
        if len(segment) < 3:
            continue
        net = segment[-1].value - segment[0].value
        if net < creep_delta:
            continue
        # Monotonic-ish: at least 70% of steps non-decreasing.
        ups = sum(
            1 for a, b in zip(segment, segment[1:]) if b.value >= a.value - 1e-9
        )
        if ups / (len(segment) - 1) >= 0.7:
            # Avoid double-counting overlapping windows: only record if the last
            # recorded creep is older than the creep window.
            if not events or events[-1].kind != "creep" or (
                anchor.ts - events[-1].ts
            ) > creep_window:
                events.append(StepEvent(anchor.ts, net, "creep"))

    events.sort(key=lambda e: e.ts)
    return events
