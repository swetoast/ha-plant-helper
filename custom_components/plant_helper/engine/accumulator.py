"""Gap-aware time-series primitives shared by every Plant Helper model.

Design rule (design.md sections 3 and 6): time-based measurements drive
decisions, and a gap in *valid* data must never be extrapolated across. A dead
battery, a stale API reading, a flatlined probe, or a Home Assistant restart all
produce holes in the signal; these primitives integrate *around* holes rather
than crediting them at the last-known value.

This is the single shared invalidation mechanism the review called for: every
accumulator (light minutes, DLI energy, thermal-stress minutes, drying deltas)
is built from `valid_intervals`, so the gap rule is defined exactly once.

The module deliberately imports nothing from Home Assistant so the maths can be
exercised directly under unit test.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from statistics import median
from typing import Callable, Iterable, Iterator, Sequence

# Natural-sunlight conversion: 1 W/m^2 of PAR ~= 4.57 umol/m^2/s PPFD.
# Integrating one hour of mean PAR therefore yields
#   4.57 * 3600 / 1e6 = 0.016452 mol/m^2  (see design.md appendix section 2).
PAR_WH_TO_DLI = 4.57 * 3600.0 / 1_000_000.0  # mol/m^2 per (W/m^2 * hour)


@dataclass(frozen=True, slots=True)
class Sample:
    """One timestamped reading.

    `valid` is set False by the validation layer for readings that fail sanity
    checks (stale, flatlined, out of range, low battery). A sample is only
    `usable` when it is both valid and carries a numeric value.
    """

    ts: datetime
    value: float | None
    valid: bool = True

    @property
    def usable(self) -> bool:
        return self.valid and self.value is not None


@dataclass(frozen=True, slots=True)
class Interval:
    """A credited span between two consecutive usable samples."""

    start: Sample
    end: Sample
    minutes: float

    @property
    def hours(self) -> float:
        return self.minutes / 60.0

    @property
    def mean(self) -> float:
        """Trapezoidal mean of the endpoint values."""
        return (self.start.value + self.end.value) / 2.0


def _sorted(samples: Iterable[Sample]) -> list[Sample]:
    return sorted(samples, key=lambda s: s.ts)


def window(
    samples: Iterable[Sample],
    now: datetime,
    span: timedelta,
) -> list[Sample]:
    """Return samples falling within the trailing window [now - span, now]."""
    lo = now - span
    return [s for s in _sorted(samples) if lo <= s.ts <= now]


def valid_intervals(
    samples: Iterable[Sample],
    max_gap: timedelta,
) -> Iterator[Interval]:
    """Yield intervals between consecutive *usable* samples.

    An interval is only produced when both endpoints are usable. The credited
    duration is clamped to `max_gap`, so a long hole (restart, dead sensor)
    contributes at most one `max_gap` slice instead of the whole downtime. A
    zero/negative step is skipped.
    """
    ordered = _sorted(samples)
    max_minutes = max_gap.total_seconds() / 60.0
    for prev, cur in zip(ordered, ordered[1:]):
        if not prev.usable or not cur.usable:
            continue
        raw = (cur.ts - prev.ts).total_seconds() / 60.0
        if raw <= 0:
            continue
        yield Interval(prev, cur, min(raw, max_minutes))


def accumulate_minutes(
    samples: Iterable[Sample],
    max_gap: timedelta,
    predicate: Callable[[float], bool],
) -> float:
    """Sum minutes over intervals whose *start* value satisfies `predicate`.

    Step convention: the reading at the start of an interval is taken to hold
    until the next reading. Used for "minutes of sufficient light", "minutes of
    cold/heat stress", etc.
    """
    return sum(
        iv.minutes for iv in valid_intervals(samples, max_gap) if predicate(iv.start.value)
    )


def integrate(
    samples: Iterable[Sample],
    max_gap: timedelta,
    scale: float = 1.0,
) -> float:
    """Trapezoidal integral of value over time, in (value-units * hours) * scale.

    Unlike a naive one-value-per-hour sum, this integrates over the *actual*
    timestamps, so an irregular cadence integrates correctly (review note on
    DLI sampling).
    """
    return sum(iv.mean * iv.hours for iv in valid_intervals(samples, max_gap)) * scale


def daily_dli(
    par_samples: Iterable[Sample],
    max_gap: timedelta,
) -> float:
    """Daily Light Integral (mol/m^2/day) from PAR (W/m^2) samples.

    Trapezoidal integration over real timestamps, converted via PAR_WH_TO_DLI.
    """
    return integrate(par_samples, max_gap, scale=PAR_WH_TO_DLI)


def time_weighted_mean(
    samples: Iterable[Sample],
    max_gap: timedelta,
) -> float | None:
    """Duration-weighted mean value across valid intervals (None if no cover)."""
    total_minutes = 0.0
    weighted = 0.0
    for iv in valid_intervals(samples, max_gap):
        weighted += iv.mean * iv.minutes
        total_minutes += iv.minutes
    if total_minutes <= 0:
        return None
    return weighted / total_minutes


def extent(samples: Iterable[Sample]) -> tuple[float | None, float | None]:
    """(min, max) over usable sample values."""
    values = [s.value for s in samples if s.usable]
    if not values:
        return (None, None)
    return (min(values), max(values))


def covered_minutes(samples: Iterable[Sample], max_gap: timedelta) -> float:
    """Total minutes actually covered by valid intervals (gaps excluded)."""
    return sum(iv.minutes for iv in valid_intervals(samples, max_gap))


def coverage_ratio(
    samples: Iterable[Sample],
    now: datetime,
    span: timedelta,
    max_gap: timedelta,
) -> float:
    """Fraction of `span` covered by valid data ending at `now` (0.0-1.0).

    Used by the calibration layer to decide whether a day has enough valid
    coverage to contribute a baseline, and by validation to flag sparse days.
    """
    span_minutes = span.total_seconds() / 60.0
    if span_minutes <= 0:
        return 0.0
    covered = covered_minutes(window(samples, now, span), max_gap)
    return max(0.0, min(1.0, covered / span_minutes))


def rolling_average(
    samples: Sequence[Sample],
    width: timedelta,
) -> list[tuple[datetime, float]]:
    """Trailing rolling mean of usable values over `width` at each sample point.

    Returns (timestamp, average) pairs. Used to smooth capacitive-probe spikes
    before peak detection (M_max), per design.md appendix section 1.
    """
    ordered = [s for s in _sorted(samples) if s.usable]
    out: list[tuple[datetime, float]] = []
    for i, anchor in enumerate(ordered):
        lo = anchor.ts - width
        bucket = [s.value for s in ordered[: i + 1] if s.ts >= lo]
        if bucket:
            out.append((anchor.ts, sum(bucket) / len(bucket)))
    return out


def rolling_max_average(
    samples: Sequence[Sample],
    width: timedelta,
) -> float | None:
    """Peak of the trailing rolling average (the saturation-peak estimator).

    Resistant to instantaneous capacitive spikes because it maxes over a
    smoothed series rather than raw readings.
    """
    averaged = rolling_average(samples, width)
    if not averaged:
        return None
    return max(value for _, value in averaged)


def robust_median(
    values: Iterable[float | None],
    *,
    trim_full: int = 2,
    trim_min_days_full: int = 8,
    trim_min_days_partial: int = 5,
) -> float | None:
    """Outlier-trimmed median that degrades gracefully on short series.

    For a full calibration (>= `trim_min_days_full` days) it drops the
    `trim_full` highest and lowest values then takes the median of the rest
    (design.md: drop 2 high + 2 low of 14, median of the middle 10). For a
    partial series it trims less; for a very short series it does not trim at
    all rather than returning an empty core. Returns None when there is no data.
    """
    vals = sorted(v for v in values if v is not None)
    n = len(vals)
    if n == 0:
        return None
    if n >= trim_min_days_full:
        trim = trim_full
    elif n >= trim_min_days_partial:
        trim = 1
    else:
        trim = 0
    core = vals[trim : n - trim] if n - 2 * trim >= 1 else vals
    return median(core)


def latest_ts(samples: Iterable[Sample]) -> datetime | None:
    """Timestamp of the most recent usable sample, or None."""
    usable = [s.ts for s in samples if s.usable]
    return max(usable) if usable else None


def nearest_value(
    samples: Iterable[Sample],
    ts: datetime,
    tolerance: timedelta,
) -> float | None:
    """Value of the usable sample closest to `ts` within `tolerance`, else None."""
    best: float | None = None
    best_dt = tolerance
    for s in samples:
        if not s.usable:
            continue
        dt = abs(s.ts - ts)
        if dt <= best_dt:
            best_dt = dt
            best = s.value
    return best


def daily_dli_by_date(
    par_samples: Iterable[Sample],
    max_gap: timedelta,
) -> dict[date, float]:
    """DLI (mol/m^2/day) per calendar date of the sample timestamps.

    Integrates within each date only — it never bridges across midnight — so each
    value is a true per-calendar-day light integral. Because STRÅNG PAR samples
    are timestamped by the UTC hour they represent, the dates here are the actual
    (lagged) STRÅNG days, not the local clock.
    """
    by_date: dict[date, list[Sample]] = defaultdict(list)
    for s in par_samples:
        if s.usable:
            by_date[s.ts.date()].append(s)
    return {d: daily_dli(samples, max_gap) for d, samples in by_date.items()}


def _complete_day_samples(
    par_samples: Iterable[Sample],
    min_hours: int,
) -> list[Sample] | None:
    """Samples of the most recent complete calendar day (>= min_hours), else the
    newest available day; None if there are no usable samples."""
    by_date: dict[date, list[Sample]] = defaultdict(list)
    for s in par_samples:
        if s.usable:
            by_date[s.ts.date()].append(s)
    if not by_date:
        return None
    complete = [d for d, ss in by_date.items() if len(ss) >= min_hours]
    if not complete:
        return None
    return by_date[max(complete)]


def complete_day_dli(
    par_samples: Iterable[Sample],
    max_gap: timedelta,
    *,
    min_hours: int = 20,
) -> float | None:
    """DLI of the most recent *complete* calendar day (>= `min_hours` samples).

    STRÅNG publishes hourly (0 at night), so a full day has ~24 samples. Requiring
    a near-complete day means a just-started day right after midnight is skipped
    in favour of the last finished day — this is what stops "today's DLI" from
    dipping or jumping at 00:00. Falls back to the newest available day if none is
    yet complete (e.g. a fresh install).
    """
    day = _complete_day_samples(par_samples, min_hours)
    return daily_dli(day, max_gap) if day else None


def complete_day_light_hours(
    par_samples: Iterable[Sample],
    threshold: float,
    max_gap: timedelta,
    *,
    min_hours: int = 20,
) -> float | None:
    """Hours of the most recent complete day with PAR at/above `threshold`.

    A weather-aware "usable light hours": on a dark overcast day this drops even
    though the astronomical daylight length is unchanged. Same complete-day basis
    as `complete_day_dli`, so the two pair cleanly.
    """
    day = _complete_day_samples(par_samples, min_hours)
    if not day:
        return None
    hours = 0.0
    for iv in valid_intervals(day, max_gap):
        if iv.mean >= threshold:
            hours += iv.hours
    return round(hours, 1)
