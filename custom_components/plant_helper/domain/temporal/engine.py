"""Combined temporal interpretation (roadmap Phase 5).

Pure: no clock, no I/O. evaluate_plant runs every signal engine against one
plant's rolling history and daily ledger and combines them into the published
outputs: one status (deterministic precedence), one health verdict (good /
watch / stressed / unknown), the needs-attention flag with its reason, and a
natural-language summary. The Home Assistant runtime only gathers inputs and
publishes the result, so every roadmap timeline scenario runs as a plain test.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, tzinfo
from typing import Any, Mapping

from . import humidity as humidity_mod
from . import temperature as temperature_mod
from .combined import combined_condition
from .daily import DailySummary, completed_days
from .drying import drying_context
from .exposure import track_exposure
from .history import ObservationHistory
from .light import MAX_HOLD_HOURS, assess_light
from .moisture import (
    MIN_SLOPE_SPAN_HOURS,
    PROFILE_BANDS,
    RECENTLY_WATERED_HOURS,
    SLOPE_WINDOW_HOURS,
    WET_DURATION_LIMIT_HOURS,
    TemporalMoistureState,
    evaluate_moisture,
    watering_rise_threshold,
)
from .season import assess_dormancy, dormant_band
from .sensor_health import assess_sensor
from .status import (
    ATTENTION_REASONS,
    DRYING,
    HEALTH_STRESSED,
    HEALTH_UNKNOWN,
    HEALTH_WATCH,
    NORMAL,
    PARTIAL_WATERING,
    RECENTLY_WATERED,
    SENSOR_PROBLEM,
    STAYING_WET,
    TOO_WET,
    WAITING_FOR_DATA,
    WET,
    worst_health,
    worst_of,
)

PARTIAL_WATERING_MARGIN = 15.0  # points below the learned typical peak
PARTIAL_RISE_RATIO = 0.5  # or a rise under half the learned typical rise
RECOVERY_ALLOWANCE = 1.25  # wet base limit = 1.25x the learned time back to range
MAX_BASE_WET_HOURS = 240.0
PARTIAL_WATERING_WINDOW_HOURS = 72.0
SLOW_DRYING_RATIO = 0.3  # current decline below 30% of the learned slope
SLOW_DRYING_MIN_HOURS = 24.0
REPEATED_WINDOW_DAYS = 5
# A fresh dry run must hold this long before it raises attention, so a sensor
# wobbling across the band edge (or a watering still soaking in) cannot flicker
# needs-attention on and off.
ATTENTION_ONSET = timedelta(minutes=30)

_WET_FAMILY = frozenset({RECENTLY_WATERED, WET, STAYING_WET, TOO_WET})
_CALM = frozenset({NORMAL, WET, DRYING})
_MOISTURE_ATTENTION_REASONS = {
    "soil_dry",
    "persistently_dry",
    "persistently_wet",
}


@dataclass(frozen=True, slots=True)
class EngineInputs:
    history: ObservationHistory
    prior: TemporalMoistureState | None
    ledger: Mapping[str, DailySummary]
    now: datetime
    tz: tzinfo
    profile: str = "balanced"
    placement: str = "indoor"
    learned: Mapping[str, Any] = field(default_factory=dict)
    rain_suppression: bool = False
    growth_season: bool | None = None
    radiation_24h: float | None = None


@dataclass(frozen=True, slots=True)
class EngineResult:
    status: str
    health: str
    needs_attention: bool
    attention_reason: str | None
    summary: str
    reason: str
    since: datetime | None
    health_summary: str
    moisture_state: TemporalMoistureState
    confidence: str
    drying_context: str
    light_context: str | None
    humidity_context: str | None
    temperature_context: str | None
    dormant: bool
    condition: str | None


def evaluate_plant(inp: EngineInputs) -> EngineResult:
    now = inp.now
    history = inp.history
    days = completed_days(inp.ledger, now, inp.tz)
    today_key = now.astimezone(inp.tz).date().isoformat()
    today = inp.ledger.get(today_key)

    sensor = assess_sensor(history, days, now)
    dormant = assess_dormancy(
        days, profile=inp.profile, placement=inp.placement,
        growth_season=inp.growth_season,
    )
    profile_band = PROFILE_BANDS.get(inp.profile, PROFILE_BANDS["balanced"])
    learned = inp.learned or {}
    if learned.get("complete") and "low" in learned and "high" in learned:
        band = (float(learned["low"]), float(learned["high"]))
    else:
        band = profile_band
    band = dormant_band(band, dormant)

    temp_report = track_exposure(
        history, "soil_temperature", "soil_temperature_valid", now,
        temperature_mod.classifier(inp.placement, learned),
    )
    repeated = sum(
        1
        for d in days[-REPEATED_WINDOW_DAYS:]
        if max(d.temperature_low_hours, d.temperature_high_hours)
        >= temperature_mod.PROLONGED_TOTAL_24H_HOURS
    )
    temperature = temperature_mod.assess_temperature(temp_report, repeated_days=repeated)
    hum_report = track_exposure(
        history, "humidity", "humidity_valid", now,
        humidity_mod.classifier(inp.placement, learned),
    )
    humidity = humidity_mod.assess_humidity(hum_report)
    light = assess_light(
        [d.light for d in days if d.light is not None],
        today.light if today is not None else None,
        supplemental_share=learned.get("supplemental_share"),
    )

    # Learned time back to range sets this pot's own wet allowance (Phase 6).
    base_limit = WET_DURATION_LIMIT_HOURS
    if learned.get("recovery_hours"):
        base_limit = min(
            MAX_BASE_WET_HOURS,
            max(WET_DURATION_LIMIT_HOURS, RECOVERY_ALLOWANCE * float(learned["recovery_hours"])),
        )

    # The expected-drying estimate uses the trend since the last known watering.
    slope = history.moisture_slope(
        now,
        window_hours=SLOPE_WINDOW_HOURS,
        since=inp.prior.last_watering_event if inp.prior is not None else None,
        min_span_hours=MIN_SLOPE_SPAN_HOURS,
    )
    drying = drying_context(
        base_limit_hours=base_limit,
        slope=None if slope is None else min(slope, 0.0),
        temperature=temp_report.value,
        humidity=hum_report.value,
        light_lux_hours_24h=_lux_hours(history, now),
        radiation_24h=inp.radiation_24h,
        dormant=dormant,
    )
    decision, moisture_state = evaluate_moisture(
        history,
        inp.prior,
        now,
        inp.profile,
        {"placement": inp.placement, "rain_suppression": inp.rain_suppression},
        band=band,
        wet_limit_hours=drying.adjusted_wet_duration_limit,
        drying_label=drying.label,
        watering_rise=watering_rise_threshold(days),
    )

    status = decision.status
    summary, reason, since = decision.summary, decision.reason, decision.since
    slope = moisture_state.drying_rate_per_hour  # same trend the state machine used
    moisture_health = decision.health

    # Partial watering (appendix): the last watering peaked well short of what
    # this pot normally reaches, so the reservoir is smaller than it looks.
    typical_peak = learned.get("peak")
    typical_rise = learned.get("rise")
    last_watering = moisture_state.last_watering_event
    peak = moisture_state.cycle_peak_moisture
    rise = _watering_rise(history, last_watering, peak)
    short_peak = typical_peak is not None and peak is not None and (
        peak < float(typical_peak) - PARTIAL_WATERING_MARGIN
    )
    short_rise = typical_rise and rise is not None and rise < PARTIAL_RISE_RATIO * float(typical_rise)
    if (
        (short_peak or short_rise)
        and last_watering is not None
        and status in (NORMAL, DRYING, WET)
        and timedelta(hours=RECENTLY_WATERED_HOURS)
        < now - last_watering
        <= timedelta(hours=PARTIAL_WATERING_WINDOW_HOURS)
    ):
        status = PARTIAL_WATERING
        summary = "The last watering only partly soaked the soil"
        reason = "partial_watering"
        since = last_watering

    combined = combined_condition(
        soil_wet=status in _WET_FAMILY,
        slope=slope,
        temperature_condition=temperature.condition,
        humidity_condition=humidity.condition,
        vpd=drying.vpd_kpa,
    )
    combined_health = None
    if combined is not None and status in _WET_FAMILY | {DRYING}:
        summary = combined.summary
        if combined.name == "cold_wet_condition" and status in (STAYING_WET, TOO_WET):
            combined_health = HEALTH_STRESSED if status == TOO_WET else HEALTH_WATCH

    # Baseline comparison (Phase 6): wet soil drying far slower than usual.
    typical_slope = learned.get("slope")
    if (
        typical_slope
        and status in (WET, STAYING_WET)
        and since is not None
        and now - since >= timedelta(hours=SLOW_DRYING_MIN_HOURS)
        and (slope is None or -slope < SLOW_DRYING_RATIO * float(typical_slope))
    ):
        summary = "Soil is drying much more slowly than usual for this plant"
        combined_health = combined_health or HEALTH_WATCH

    if dormant and status in _CALM:
        reason = "seasonal_dormancy"
        summary = summary + " (the plant is resting for the season)"

    # Combine statuses by precedence; the winning source supplies the text.
    candidates = [status, temperature.status, light.status]
    if sensor.problem:
        candidates.append(SENSOR_PROBLEM)
    final = worst_of(candidates)
    if final == SENSOR_PROBLEM:
        summary, reason, since = sensor.summary, "sensor_problem", sensor.since
    elif final == temperature.status and final != status:
        summary, reason, since = temperature.summary, temperature.reason, temperature.since
    elif final == light.status and final != status:
        summary, reason, since = light.summary, light.reason, light.since

    # Health: the worst sustained verdict across signals.
    if final in (SENSOR_PROBLEM, WAITING_FOR_DATA):
        health = HEALTH_UNKNOWN
        health_summary = summary
    else:
        parts = [
            (moisture_health, summary),
            (temperature.health, temperature.summary),
            (humidity.health, humidity.summary),
            (light.health, light.summary),
        ]
        if combined_health is not None:
            parts.append((combined_health, summary))
        health = worst_health(value for value, _text in parts)
        health_summary = next(
            (text for value, text in parts if value == health and text), summary
        )

    # Attention: only sustained, actionable conditions (Phase 5).
    reasons = []
    if sensor.problem:
        reasons.append("sensor_problem")
    if (
        decision.needs_attention
        and decision.reason in _MOISTURE_ATTENTION_REASONS
        and (decision.since is None or now - decision.since >= ATTENTION_ONSET)
    ):
        reasons.append(decision.reason)
    if temperature.attention:
        reasons.append("prolonged_temperature_stress")
    if light.attention:
        reasons.append("several_days_insufficient_light")
    reasons = [r for r in reasons if r in ATTENTION_REASONS]

    return EngineResult(
        status=final,
        health=health,
        needs_attention=bool(reasons),
        attention_reason=reasons[0] if reasons else None,
        summary=summary,
        reason=reason,
        since=since,
        health_summary=health_summary,
        moisture_state=moisture_state,
        confidence=decision.confidence,
        drying_context=drying.label,
        light_context=light.context,
        humidity_context=humidity.context,
        temperature_context=(
            {"low": "low", "high": "high"}.get(temp_report.direction, "adequate")
            if temp_report.has_data
            else None
        ),
        dormant=dormant,
        condition=combined.name if combined is not None else None,
    )


def _watering_rise(
    history: ObservationHistory, watering: datetime | None, peak: float | None
) -> float | None:
    """Peak since the watering minus the lowest reading just before it."""
    if watering is None or peak is None:
        return None
    before = [
        value
        for t, value in history.points("moisture", "moisture_valid", watering - timedelta(hours=6))
        if t < watering
    ]
    return peak - min(before) if before else None


def _lux_hours(history: ObservationHistory, now: datetime) -> float | None:
    pieces = history.segments(
        "light", "light_valid", now - timedelta(hours=24), now,
        max_hold_hours=MAX_HOLD_HOURS,
    )
    valid = [(a, b, v) for a, b, v, _d in pieces if v is not None]
    if not valid:
        return None
    return sum(v * (b - a).total_seconds() / 3600.0 for a, b, v in valid)
