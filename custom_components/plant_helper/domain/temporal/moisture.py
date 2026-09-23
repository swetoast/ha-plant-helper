"""Pure moisture interpretation: watering detection and the wet/dry state machine.

evaluate_moisture takes an observation history, the prior persisted state, the
caller's ``now``, the care profile, and optional environment context, and
returns a decision plus the next state. It has no clock or I/O of its own, so
the roadmap's timeline scenarios run as ordinary domain tests.

This slice uses a static wet-duration limit. Escalation to too_wet / too_dry is
gated on both elapsed duration and confidence, which is why a single elevated
reading reads as ``wet`` (good health, no attention) rather than ``too_wet``.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Mapping

from .history import ObservationHistory
from .status import (
    APPROACHING_DRY,
    DRYING,
    HEALTH_GOOD,
    HEALTH_NEEDS_WATER,
    HEALTH_TOO_DRY,
    HEALTH_TOO_WET,
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

# Static duration limits (hours). P4 makes the wet limit environment-driven.
WET_DURATION_LIMIT_HOURS = 72.0
STAYING_WET_LIMIT_HOURS = 24.0
DRY_DURATION_LIMIT_HOURS = 48.0

# A rise-and-hold after watering reads as recently_watered for this long.
RECENTLY_WATERED_HOURS = 6.0

# Trend and proximity tuning.
DRYING_SLOPE = 0.5  # percent per hour of decline to call a trend "drying"
APPROACH_MARGIN = 5.0  # within this many points above the low band = approaching

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


@dataclass(frozen=True, slots=True)
class MoistureDecision:
    status: str
    health: str
    needs_attention: bool
    summary: str
    reason: str
    since: datetime | None


def evaluate_moisture(
    history: ObservationHistory,
    prior: TemporalMoistureState | None,
    now: datetime,
    profile: str,
    environment: Mapping | None = None,
) -> tuple[MoistureDecision, TemporalMoistureState]:
    low, high = PROFILE_BANDS.get(profile, PROFILE_BANDS["balanced"])
    env = environment or {}
    placement = str(env.get("placement", "indoor"))
    rain_suppression = bool(env.get("rain_suppression"))

    confidence = history.confidence(now)
    latest = history.latest_valid()
    if latest is None:
        decision = MoistureDecision(
            WAITING_FOR_DATA,
            HEALTH_UNKNOWN,
            False,
            "Waiting for a valid moisture reading",
            "moisture_unavailable",
            None,
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
    slope = history.moisture_slope(now)
    watering_at = history.detect_watering(now)
    last_watering = watering_at or (prior.last_watering_event if prior else None)
    peak = history.peak_since(last_watering)
    declining = slope is not None and slope <= -DRYING_SLOPE
    confident = confidence in _CONFIDENT

    status, health, attention, summary, reason, since = _classify(
        moisture=moisture,
        low=low,
        high=high,
        now=now,
        history=history,
        slope=slope,
        declining=declining,
        confident=confident,
        watering_at=watering_at,
        last_watering=last_watering,
        placement=placement,
        rain_suppression=rain_suppression,
        prior=prior,
    )

    decision = MoistureDecision(status, health, attention, summary, reason, since)
    state = TemporalMoistureState(
        status,
        since,
        last_watering,
        peak,
        slope,
        None,
        confidence,
    )
    return decision, state


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
    watering_at,
    last_watering,
    placement,
    rain_suppression,
    prior,
):
    if watering_at is not None and (now - watering_at) <= timedelta(
        hours=RECENTLY_WATERED_HOURS
    ):
        return (
            RECENTLY_WATERED,
            HEALTH_GOOD,
            False,
            "Soil moisture rose sharply; recently watered",
            "recent_watering",
            watering_at,
        )

    if moisture > high:
        wet_for = history.duration_above(high, now)
        since = _run_since(
            prior, _WET_FAMILY, wet_for, last_watering, now
        )
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
        if elapsed >= timedelta(hours=WET_DURATION_LIMIT_HOURS) and confident:
            return (
                TOO_WET,
                HEALTH_TOO_WET,
                True,
                "Soil has stayed wet well beyond the expected drying time",
                "persistently_wet",
                since,
            )
        if elapsed >= timedelta(hours=STAYING_WET_LIMIT_HOURS) and confident:
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

    if moisture < low:
        dry_for = history.duration_below(low, now)
        since = _run_since(prior, _DRY_FAMILY, dry_for, None, now)
        elapsed = now - since
        if elapsed >= timedelta(hours=DRY_DURATION_LIMIT_HOURS) and confident:
            return (
                TOO_DRY,
                HEALTH_TOO_DRY,
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
                HEALTH_NEEDS_WATER,
                False,
                "Soil is below the profile, but rain is expected soon; watering is paused",
                "rain_expected",
                since,
            )
        return (
            NEEDS_WATER,
            HEALTH_NEEDS_WATER,
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
