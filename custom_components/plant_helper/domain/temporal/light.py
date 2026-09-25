"""Gated light-exposure engine (roadmap Phase 4).

Pure. Light is judged on cumulative exposure across proper solar windows, never
on a plain average, so a dark night cannot make a well-lit plant look starved.

- Natural exposure: lux x hours while it is daylight. Readings taken while the
  daylight state is unknown also count as natural (unknown is never night), but
  they mark the day as uncertain so it cannot raise an alert.
- Supplemental exposure: at night, lux at or above SUPPLEMENTAL_THRESHOLD_LUX
  held for SUPPLEMENTAL_MIN_MINUTES continuous minutes forms a session. Shorter
  room-light events are ignored. A session is weighted by ARTIFICIAL_WEIGHT
  (unknown artificial source, lux only) and belongs entirely to the local day on
  which it started, so a session crossing midnight stays intact.
- Units are lux-hours; this is deliberately not called DLI.

Days are classified against outdoor shortwave radiation, and the multi-day
assessment suppresses overcast days (up to OVERCAST_SUPPRESS_DAYS) and requires
SHADING_DAYS of evidence before calling a spot shaded.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo
from typing import Iterable, Sequence

from .history import ObservationHistory
from .status import HEALTH_GOOD, HEALTH_WATCH, INSUFFICIENT_LIGHT

SUPPLEMENTAL_THRESHOLD_LUX = 100.0
SUPPLEMENTAL_MIN_MINUTES = 15.0
ARTIFICIAL_WEIGHT = 0.60
MAX_HOLD_HOURS = 2.0

# Live data (September, Boras): dim days 500-1740 lx-h, normal days 3300-6400.
# The default sits in that gap until the plant's own normal is learned; the
# learned normal can only relax it (half the normal, never below the floor).
LOW_LIGHT_LUX_HOURS = 2500.0
LOW_LIGHT_FLOOR = 1000.0
RELATIVE_LOW = 0.5
GROW_LIGHT_SHARE = 0.6
GROW_LIGHT_MISSING_DAYS = 2
MIN_COVERAGE_HOURS = 16.0
HIGH_CONFIDENCE_COVERAGE_HOURS = 20.0
BRIGHT_RADIATION = 150.0  # W/m2, mean over daylight hours
OVERCAST_RADIATION = 60.0

INSUFFICIENT_DAYS = 3
OVERCAST_SUPPRESS_DAYS = 3
SHADING_DAYS = 2

LOW_CLASSES = frozenset({"low_light", "overcast_day", "shaded_or_obstructed"})


@dataclass(frozen=True, slots=True)
class DailyLightExposure:
    day_date: str
    daylight_start: datetime | None
    daylight_end: datetime | None
    daylight_classification_certain: bool

    natural_light_exposure: float
    artificial_light_exposure: float
    effective_light_exposure: float

    artificial_weight_applied: float
    confidence: str
    classification: str

    daily_peak_lux: float
    valid_coverage_hours: float
    mean_outdoor_radiation: float | None

    @property
    def judged(self) -> bool:
        """A day only counts toward a verdict when coverage and daylight are solid."""
        return self.confidence != "low"


@dataclass(frozen=True, slots=True)
class LightAssessment:
    context: str | None
    status: str | None
    health: str
    attention: bool
    reason: str | None
    summary: str | None
    since: datetime | None


def low_light_threshold(normal: float | None) -> float:
    """Low-light threshold for a day, relaxed toward the plant's learned normal."""
    if not normal:
        return LOW_LIGHT_LUX_HOURS
    return min(LOW_LIGHT_LUX_HOURS, max(LOW_LIGHT_FLOOR, RELATIVE_LOW * normal))


def day_bounds(day: date, tz: tzinfo) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), tz)
    return start, start + timedelta(days=1)


def supplemental_sessions(
    history: ObservationHistory, start: datetime, end: datetime
) -> list[tuple[datetime, datetime, float]]:
    """Qualifying night sessions as (session_start, session_end, lux_hours)."""
    pieces = history.segments(
        "light", "light_valid", start, end, max_hold_hours=MAX_HOLD_HOURS
    )
    sessions: list[tuple[datetime, datetime, float]] = []
    current: list[tuple[datetime, datetime, float]] = []

    def close() -> None:
        if not current:
            return
        minutes = (current[-1][1] - current[0][0]).total_seconds() / 60.0
        if minutes >= SUPPLEMENTAL_MIN_MINUTES:
            lux_hours = sum(
                value * (b - a).total_seconds() / 3600.0 for a, b, value in current
            )
            sessions.append((current[0][0], current[-1][1], lux_hours))
        current.clear()

    for a, b, value, daylight in pieces:
        lit_night = (
            daylight is False
            and value is not None
            and value >= SUPPLEMENTAL_THRESHOLD_LUX
        )
        if lit_night and current and current[-1][1] != a:
            close()  # an uncovered gap ends the session
        if lit_night:
            current.append((a, b, value))
        else:
            close()
    close()
    return sessions


def daily_light(
    history: ObservationHistory,
    day: date,
    tz: tzinfo,
    now: datetime,
    *,
    mean_outdoor_radiation: float | None = None,
    low_threshold: float = LOW_LIGHT_LUX_HOURS,
) -> DailyLightExposure | None:
    """Exposure for one local day, or None when there is no light data for it."""
    d0, d1 = day_bounds(day, tz)
    end = min(d1, now)
    if end <= d0:
        return None
    pieces = history.segments(
        "light", "light_valid", d0, end, max_hold_hours=MAX_HOLD_HOURS
    )
    natural = coverage = peak = 0.0
    certain = True
    first_day: datetime | None = None
    last_day: datetime | None = None
    for a, b, value, daylight in pieces:
        if value is None:
            continue
        hours = (b - a).total_seconds() / 3600.0
        coverage += hours
        peak = max(peak, value)
        if daylight is None:
            certain = False
        if daylight is not False:
            natural += value * hours
            if daylight is True:
                first_day = first_day or a
                last_day = b
    if coverage <= 0:
        return None
    # Sessions that START on this day, even if they run past midnight.
    horizon = min(d1 + timedelta(hours=12), now)
    artificial = sum(
        lux_hours
        for s_start, _s_end, lux_hours in supplemental_sessions(
            history, d0 - timedelta(hours=12), horizon
        )
        if d0 <= s_start < d1
    )
    effective = natural + artificial * ARTIFICIAL_WEIGHT
    if coverage >= HIGH_CONFIDENCE_COVERAGE_HOURS and certain:
        confidence = "high"
    elif coverage >= MIN_COVERAGE_HOURS and certain:
        confidence = "medium"
    else:
        confidence = "low"
    return DailyLightExposure(
        day_date=day.isoformat(),
        daylight_start=first_day,
        daylight_end=last_day,
        daylight_classification_certain=certain,
        natural_light_exposure=natural,
        artificial_light_exposure=artificial,
        effective_light_exposure=effective,
        artificial_weight_applied=ARTIFICIAL_WEIGHT if artificial else 0.0,
        confidence=confidence,
        classification=classify_day(
            natural, artificial, effective, mean_outdoor_radiation, low_threshold
        ),
        daily_peak_lux=peak,
        valid_coverage_hours=coverage,
        mean_outdoor_radiation=mean_outdoor_radiation,
    )


def classify_day(
    natural: float,
    artificial: float,
    effective: float,
    radiation: float | None,
    low_threshold: float = LOW_LIGHT_LUX_HOURS,
) -> str:
    low = effective < low_threshold
    bright = radiation is not None and radiation >= BRIGHT_RADIATION
    dull = radiation is not None and radiation <= OVERCAST_RADIATION
    if low and bright:
        return "shaded_or_obstructed"
    if low and dull:
        return "overcast_day"
    if low:
        return "low_light"
    if artificial > 0:
        return "supplemental_light_detected"
    if bright:
        return "optimal_natural_exposure"
    return "adequate"


def mean_daytime_radiation(
    samples: Iterable[tuple[datetime, float | None]], start: datetime, end: datetime
) -> float | None:
    """Mean of positive hourly radiation within [start, end); None if too sparse."""
    values = [
        float(value)
        for t, value in samples
        if value is not None and start <= t < end and float(value) > 0
    ]
    return sum(values) / len(values) if len(values) >= 3 else None


def assess_light(
    completed: Sequence[DailyLightExposure],
    today: DailyLightExposure | None,
    *,
    supplemental_share: float | None = None,
) -> LightAssessment:
    """Multi-day light verdict from completed days (oldest first) plus today."""
    context = None
    latest = completed[-1] if completed else None
    if latest is not None and latest.judged:
        context = "low" if latest.classification in LOW_CLASSES else "adequate"

    streak: list[DailyLightExposure] = []
    for day in reversed(completed):
        if not day.judged or day.classification not in LOW_CLASSES:
            break
        streak.append(day)
    streak.reverse()  # oldest first

    since = streak[0].daylight_start if streak else None
    all_overcast = bool(streak) and all(
        d.classification == "overcast_day" for d in streak
    )
    shaded_run = 0
    for day in reversed(streak):
        if day.classification != "shaded_or_obstructed":
            break
        shaded_run += 1

    if len(streak) >= INSUFFICIENT_DAYS and not (
        all_overcast and len(streak) <= OVERCAST_SUPPRESS_DAYS
    ):
        return LightAssessment(
            "low",
            INSUFFICIENT_LIGHT,
            HEALTH_WATCH,
            True,
            "several_days_insufficient_light",
            f"Light exposure has remained low for {len(streak)} days",
            since,
        )
    if shaded_run >= SHADING_DAYS:
        return LightAssessment(
            "low",
            INSUFFICIENT_LIGHT,
            HEALTH_WATCH,
            False,
            "likely_shaded",
            "It is bright outside but this spot stays dim; the plant is probably shaded",
            since,
        )
    # A plant that normally gets a grow light at night, but has not for the last
    # judged nights: the light has probably failed or its schedule changed.
    judged = [d for d in completed if d.judged]
    if (
        supplemental_share is not None
        and supplemental_share >= GROW_LIGHT_SHARE
        and len(judged) >= GROW_LIGHT_MISSING_DAYS
        and all(d.artificial_light_exposure == 0 for d in judged[-GROW_LIGHT_MISSING_DAYS:])
    ):
        return LightAssessment(
            context, None, HEALTH_WATCH, False, "grow_light_missing",
            "No grow-light session was detected for two nights", None,
        )
    if streak and all_overcast:
        return LightAssessment(
            context, None, HEALTH_GOOD, False, "overcast",
            "Light was low, but overcast weather explains it", None,
        )
    if today is not None and today.classification == "supplemental_light_detected":
        return LightAssessment(
            context, None, HEALTH_GOOD, False, None,
            "Natural and supplemental light provided adequate exposure today", None,
        )
    return LightAssessment(context, None, HEALTH_GOOD, False, None, None, None)
