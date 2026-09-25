"""Pure moisture interpretation: watering detection and the wet/dry state machine.

evaluate_moisture takes an observation history, the prior persisted state, the
caller's ``now``, the care profile, and optional environment context, and
returns a decision plus the next state. It has no clock or I/O of its own, so
the roadmap's timeline scenarios run as ordinary domain tests.

The wet-duration limit and drying label come from the environmental drying
context (drying.py), supplied by the combined engine. Escalation to too_wet /
too_dry is gated on both elapsed duration and confidence, which is why a single
elevated reading reads as ``wet`` (good health, no attention) not ``too_wet``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median
from typing import Any, Mapping, Sequence

from .history import WATERING_RISE, ObservationHistory, same_watering
from .status import (
    APPROACHING_DRY,
    DRYING,
    HEALTH_GOOD,
    HEALTH_STRESSED,
    HEALTH_UNKNOWN,
    HEALTH_WATCH,
    NEEDS_WATER,
    NORMAL,
    RECENTLY_WATERED,
    STAYING_WET,
    TOO_DRY,
    TOO_WET,
    WATERING_PAUSED,
    WAITING_FOR_DATA,
    WET,
)

# Moisture comfort band per care profile, as (low, high) percentages.
PROFILE_BANDS: dict[str, tuple[float, float]] = {
    "dry": (15.0, 45.0),
    "balanced": (25.0, 65.0),
    "moist": (40.0, 80.0),
    "custom": (25.0, 65.0),
}

# Below this the plant is critically dry; rain suppression never holds back a
# watering recommendation at or below it.
CRITICAL_MOISTURE = 5.0

# Duration limits (hours). The wet limit is the base the drying context scales.
WET_DURATION_LIMIT_HOURS = 72.0
STAYING_WET_LIMIT_HOURS = 24.0
DRY_DURATION_LIMIT_HOURS = 48.0

# A rise-and-hold after watering reads as recently_watered for this long.
RECENTLY_WATERED_HOURS = 6.0

# Trend and proximity tuning.
# Calibrated against live recorder data: real pots dry about 1-10 points a day,
# and sensors report whole percentages, so the trend is read over up to a day
# (starting after the last watering) and a gentle steady decline counts.
DRYING_SLOPE = 0.05  # percent per hour of decline to call a trend "drying"
SLOPE_WINDOW_HOURS = 48.0  # two daily cycles: cancels the probe's day/night swing
MIN_SLOPE_SPAN_HOURS = 4.0
APPROACH_MARGIN = 5.0  # within this many points above the low band = approaching
# Watering threshold scales with the sensor's typical daily swing.
NOISE_DAYS = 7
NOISE_MIN_DAYS = 3
NOISE_COVERAGE_HOURS = 20.0
NOISE_FACTOR = 1.5
WATERING_RISE_MIN = 5.0
WATERING_RISE_MAX = 20.0
# A status at a band edge only clears once moisture is this far back inside,
# so a sensor wobbling 24/25/26 does not flap needs-attention.
BAND_HYSTERESIS = 2.0

_CONFIDENT = ("medium", "high")

# Statuses that continue an existing wet or dry run. A run keeps its original
# start (from the persisted state or the watering event) so duration accumulates
# across ticks and across the pruning of old observations.
_WET_FAMILY = frozenset({RECENTLY_WATERED, WET, STAYING_WET, TOO_WET})
_DRY_FAMILY = frozenset({APPROACHING_DRY, NEEDS_WATER, TOO_DRY, WATERING_PAUSED})


@dataclass(frozen=True, slots=True)
class TemporalMoistureState:
    status: str
    state_since: datetime | None
    last_watering_event: datetime | None
    cycle_peak_moisture: float | None
    drying_rate_per_hour: float | None
    adjusted_wet_duration_limit: float | None
    confidence: str
    # Start of the current unbroken period above the band. It survives brief
    # "drying" dips and top-up waterings, so soil that is repeatedly watered
    # before it ever returns to range still accumulates wet duration.
    elevated_since: datetime | None = None


@dataclass(frozen=True, slots=True)
class MoistureDecision:
    status: str
    health: str
    needs_attention: bool
    summary: str
    reason: str
    since: datetime | None
    confidence: str
    drying_context: str


def evaluate_moisture(
    history: ObservationHistory,
    prior: TemporalMoistureState | None,
    now: datetime,
    profile: str,
    environment: Mapping | None = None,
    band: tuple[float, float] | None = None,
    *,
    wet_limit_hours: float = WET_DURATION_LIMIT_HOURS,
    drying_label: str = "normal",
    watering_rise: float = WATERING_RISE,
) -> tuple[MoistureDecision, TemporalMoistureState]:
    if band is not None:
        low, high = band
    else:
        low, high = PROFILE_BANDS.get(profile, PROFILE_BANDS["balanced"])
    env = environment or {}
    placement = str(env.get("placement", "indoor"))
    rain_suppression = bool(env.get("rain_suppression"))

    confidence = history.confidence(now)
    context = drying_label

    latest = history.latest_valid()
    if latest is None:
        decision = MoistureDecision(
            WAITING_FOR_DATA,
            HEALTH_UNKNOWN,
            False,
            "Waiting for a valid moisture reading",
            "moisture_unavailable",
            None,
            confidence,
            context,
        )
        state = TemporalMoistureState(
            WAITING_FOR_DATA,
            None,
            prior.last_watering_event if prior else None,
            None,
            None,
            None,
            confidence,
        )
        return decision, state

    moisture = float(latest.moisture)
    last_watering = same_watering(
        history.detect_watering(now, rise=watering_rise),
        prior.last_watering_event if prior else None,
        history,
    )
    slope = history.moisture_slope(
        now,
        window_hours=SLOPE_WINDOW_HOURS,
        since=last_watering,
        min_span_hours=MIN_SLOPE_SPAN_HOURS,
    )
    peak = history.peak_since(last_watering)
    declining = slope is not None and slope <= -DRYING_SLOPE
    confident = confidence in _CONFIDENT

    above = moisture > high or (
        prior is not None
        and prior.elevated_since is not None
        and moisture > high - BAND_HYSTERESIS
    )
    below = moisture < low or (
        prior is not None
        and prior.status in (NEEDS_WATER, TOO_DRY, WATERING_PAUSED)
        and moisture < low + BAND_HYSTERESIS
    )
    elevated_since = None
    if above:
        candidates = [now]
        above_for = history.duration_above(high, now)
        if above_for is not None:
            candidates.append(now - above_for)
        if prior is not None and prior.elevated_since is not None:
            candidates.append(prior.elevated_since)
        elevated_since = min(candidates)

    status, health, attention, summary, reason, since = _classify(
        moisture=moisture,
        low=low,
        high=high,
        now=now,
        history=history,
        slope=slope,
        declining=declining,
        confident=confident,
        last_watering=last_watering,
        wet_limit_hours=wet_limit_hours,
        placement=placement,
        rain_suppression=rain_suppression,
        prior=prior,
        elevated_since=elevated_since,
        above=above,
        below=below,
    )

    decision = MoistureDecision(
        status, health, attention, summary, reason, since, confidence, context
    )
    state = TemporalMoistureState(
        status,
        since,
        last_watering,
        peak,
        slope,
        wet_limit_hours,
        confidence,
        elevated_since,
    )
    return decision, state


def watering_rise_threshold(days: Sequence[Any]) -> float:
    """Rise that counts as a watering for this sensor.

    1.5x the median daily moisture range over the last week of well-covered
    days, bounded to 5..20 points. Waterings are occasional, so the median
    reflects the probe's noise and day/night swing, not the waterings. For a pot
    that dries many points a day this errs high, which can delay recognising a
    very slow soak by an hour or two; that is deliberate, because a false
    watering is far more harmful (it clears a real dry alert, restarts the wet
    and dry timers, and corrupts learning). Replayed against live recorder data,
    this estimate produced no false waterings on either sensor.
    """
    ranges = [
        d.moisture_max - d.moisture_min
        for d in list(days)[-NOISE_DAYS:]
        if d.moisture_coverage_hours >= NOISE_COVERAGE_HOURS
        and d.moisture_min is not None
        and d.moisture_max is not None
    ]
    if len(ranges) < NOISE_MIN_DAYS:
        return WATERING_RISE
    return max(WATERING_RISE_MIN, min(WATERING_RISE_MAX, NOISE_FACTOR * median(ranges)))


def _classify(
    *,
    moisture,
    low,
    high,
    now,
    history,
    slope,
    declining,
    confident,
    last_watering,
    wet_limit_hours,
    placement,
    rain_suppression,
    prior,
    elevated_since,
    above,
    below,
):
    # The recently-watered window runs from the recorded watering, not only
    # while the rise is still visible: a reading that dips a point during the
    # soak must not bounce the status back to needs_water.
    if last_watering is not None and timedelta(0) <= (now - last_watering) <= timedelta(
        hours=RECENTLY_WATERED_HOURS
    ):
        return (
            RECENTLY_WATERED,
            HEALTH_GOOD,
            False,
            "Soil moisture rose sharply; recently watered",
            "recent_watering",
            last_watering,
        )

    if above:
        wet_for = history.duration_above(high, now)
        since = _run_since(
            prior, _WET_FAMILY, wet_for, last_watering, now
        )
        if elevated_since is not None:
            since = min(since, elevated_since)
        elapsed = now - since
        if declining:
            return (
                DRYING,
                HEALTH_GOOD,
                False,
                "Soil moisture is elevated but falling",
                "drying_out",
                since,
            )
        if elapsed >= timedelta(hours=wet_limit_hours) and confident:
            return (
                TOO_WET,
                HEALTH_WATCH,
                True,
                "Soil has stayed wet well beyond the expected drying time",
                "persistently_wet",
                since,
            )
        # The staying-wet point scales with the dynamic wet limit (24 h of the
        # base 72 h), so slow-drying conditions delay both steps together.
        staying_hours = wet_limit_hours * (STAYING_WET_LIMIT_HOURS / WET_DURATION_LIMIT_HOURS)
        if elapsed >= timedelta(hours=staying_hours) and confident:
            return (
                STAYING_WET,
                HEALTH_WATCH,
                False,
                "Soil is holding water longer than usual",
                "slow_drying",
                since,
            )
        return (
            WET,
            HEALTH_GOOD,
            False,
            "Soil moisture is elevated after watering",
            "elevated_moisture",
            since,
        )

    if below:
        dry_for = history.duration_below(low, now)
        since = _run_since(prior, _DRY_FAMILY, dry_for, None, now)
        if last_watering is not None and since < last_watering <= now:
            since = last_watering  # a watering ends the previous dry run
        elapsed = now - since
        if elapsed >= timedelta(hours=DRY_DURATION_LIMIT_HOURS) and confident:
            return (
                TOO_DRY,
                HEALTH_STRESSED,
                True,
                "Soil has stayed dry well beyond the profile for too long",
                "persistently_dry",
                since,
            )
        if (
            placement == "outdoor"
            and rain_suppression
            and moisture >= CRITICAL_MOISTURE
        ):
            return (
                WATERING_PAUSED,
                HEALTH_GOOD,
                False,
                "Soil is below the profile, but rain is expected soon; watering is paused",
                "rain_expected",
                since,
            )
        return (
            NEEDS_WATER,
            HEALTH_WATCH,
            True,
            "Soil moisture is below the selected care profile",
            "soil_dry",
            since,
        )

    # Comfortable band.
    if moisture <= low + APPROACH_MARGIN and declining:
        status = APPROACHING_DRY
        summary = "Soil moisture is nearing the dry threshold"
        reason = "approaching_dry"
    elif declining:
        status = DRYING
        summary = "Soil moisture is easing down within range"
        reason = "drying_out"
    else:
        status = NORMAL
        summary = "Soil moisture is within the selected care profile"
        reason = "moisture_in_range"
    since = _regime_since(prior, status, now)
    return status, HEALTH_GOOD, False, summary, reason, since


def _run_since(
    prior: TemporalMoistureState | None,
    family: frozenset[str],
    hist_duration: timedelta | None,
    anchor: datetime | None,
    now: datetime,
) -> datetime:
    """Earliest evidence that the current wet or dry run began.

    Candidates are the watering anchor, the observed run length within the
    rolling window, and the persisted run start. The earliest wins, so a run
    that predates the retained observations still ages correctly.
    """
    candidates: list[datetime] = []
    if anchor is not None and anchor <= now:
        candidates.append(anchor)
    if hist_duration is not None:
        candidates.append(now - hist_duration)
    if (
        prior is not None
        and prior.status in family
        and prior.state_since is not None
    ):
        candidates.append(prior.state_since)
    return min(candidates) if candidates else now


def _regime_since(
    prior: TemporalMoistureState | None, status: str, now: datetime
) -> datetime:
    if prior is not None and prior.status == status and prior.state_since is not None:
        return prior.state_since
    return now
