"""Moisture model — the primary care engine (design.md section 7).

Pipeline: temperature-compensate the raw moisture signal, detect watering
events on the compensated series, then classify the current moisture state
against the learned dry threshold, with revocable rain suppression for outdoor
plants.

Review shortcomings closed here:
  * #8  Moisture/temperature coupling — capacitive probes drift with soil
        temperature, so the signal is compensated *before* watering detection,
        otherwise a warm afternoon reads as drying and a cold watering-can
        reads as an impossible jump.
  * #10 Rain suppression is a *downgrade*, not a mute, and is *revocable*: it is
        recomputed from the current forecast every cycle, so if the rain no
        longer appears in the forecast the alert re-escalates on its own.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .accumulator import Sample, nearest_value
from .timeseries import StepEvent, current_run_minutes, detect_sustained_step

# Moisture states
RECENTLY_WATERED = "recently_watered"
DRYING_NORMALLY = "drying_normally"
GETTING_DRY = "getting_dry"
DRY_TOO_LONG = "dry_too_long"
WET_TOO_LONG = "wet_too_long"
NORMAL = "normal"
SUPPRESSED_BY_RAIN = "suppressed_by_rain"

# Capacitive-probe temperature coefficient: apparent moisture rises ~this many
# percentage points per +1 C of soil temperature above the reference. Small and
# tunable; compensation removes it before analysis.
DEFAULT_TEMP_COEFF = 0.20
REFERENCE_SOIL_TEMP = 20.0

# Watering detection thresholds (percentage points), as fractions of the
# dynamic range are applied by the caller; these are sane absolute defaults.
SHARP_STEP_DELTA = 12.0
CREEP_DELTA = 10.0
CREEP_WINDOW = timedelta(hours=6)
STEP_PERSISTENCE = timedelta(hours=2)

# Duration a plant may sit below M_dry / near saturation before it is "too long"
# (relaxed under dormancy by the caller lowering these).
DRY_TOO_LONG_AFTER = timedelta(days=2)
WET_TOO_LONG_AFTER = timedelta(days=3)
RECENTLY_WATERED_WINDOW = timedelta(hours=12)


def temperature_compensate(
    moisture: Sequence[Sample],
    soil_temp: Sequence[Sample],
    *,
    coeff: float = DEFAULT_TEMP_COEFF,
    ref_temp: float = REFERENCE_SOIL_TEMP,
    pair_tolerance: timedelta = timedelta(minutes=15),
) -> list[Sample]:
    """Remove soil-temperature drift from the moisture signal.

    Each moisture reading is corrected by the nearest-in-time soil-temperature
    reading within `pair_tolerance`:
        compensated = raw - coeff * (soil_temp - ref_temp)
    Moisture readings with no nearby temperature reading pass through unchanged
    (better than dropping data); invalid moisture stays invalid.
    """
    temps = [s for s in sorted(soil_temp, key=lambda s: s.ts) if s.usable]
    out: list[Sample] = []
    for m in sorted(moisture, key=lambda s: s.ts):
        if not m.usable:
            out.append(m)
            continue
        t = nearest_value(temps, m.ts, pair_tolerance)
        if t is None:
            out.append(m)
            continue
        corrected = m.value - coeff * (t - ref_temp)
        out.append(Sample(m.ts, corrected, valid=True))
    return out


def detect_watering(
    compensated: Sequence[Sample],
    max_gap: timedelta,
    *,
    sharp_delta: float = SHARP_STEP_DELTA,
    creep_delta: float = CREEP_DELTA,
) -> list[StepEvent]:
    """Detect top- (sharp) and bottom- (creep) watering on the clean signal."""
    return detect_sustained_step(
        compensated,
        max_gap,
        sharp_delta=sharp_delta,
        creep_delta=creep_delta,
        creep_window=CREEP_WINDOW,
        persistence=STEP_PERSISTENCE,
    )


def last_watering(events: Sequence[StepEvent]) -> StepEvent | None:
    return events[-1] if events else None


def rain_expected(forecast_precip_mm: float | None, profile_limit_mm: float) -> bool:
    """Whether aggregate forecast precipitation clears the suppression bar."""
    return forecast_precip_mm is not None and forecast_precip_mm >= profile_limit_mm


@dataclass(frozen=True, slots=True)
class MoistureAssessment:
    state: str
    urgency: float                 # 0-100
    calculated_moisture: float | None
    days_since_watered: float | None
    days_until_dry: float | None
    watering_kind: str | None      # "sharp" | "creep" | None
    suppressed: bool               # rain downgrade currently applied
    rain_would_alert: str | None   # state that suppression is standing in for
    below_dry: bool = False        # instantaneous: current < m_dry
    above_wet: bool = False        # instantaneous: current >= wet ceiling


def evaluate_moisture(
    *,
    now: datetime,
    compensated: Sequence[Sample],
    max_gap: timedelta,
    m_dry: float | None,
    m_max: float | None,
    drying_rate: float | None,          # % per day (learned)
    placement: str,
    forecast_precip_mm: float | None,
    profile_rain_limit_mm: float,
    dormant: bool = False,
    dry_too_long_after: timedelta = DRY_TOO_LONG_AFTER,
    wet_too_long_after: timedelta = WET_TOO_LONG_AFTER,
    dry_run_minutes: float | None = None,
    wet_run_minutes: float | None = None,
) -> MoistureAssessment:
    """Classify current moisture into a state + urgency.

    Learned constants may be absent (plant still calibrating); the model then
    reports NORMAL with zero urgency rather than inventing thresholds.

    `dry_run_minutes` / `wet_run_minutes`, when supplied, override the
    sample-walk run durations with persisted, reboot-safe timers (the coordinator
    passes these). When omitted, durations are computed from the sample buffer
    (used by unit tests and as a fallback).
    """
    usable = [s for s in sorted(compensated, key=lambda s: s.ts) if s.usable]
    current = usable[-1].value if usable else None

    events = detect_watering(compensated, max_gap)
    last = last_watering(events)
    days_since = None
    if last is not None:
        days_since = max(0.0, (now - last.ts).total_seconds() / 86400.0)

    # Recently watered wins outright.
    if last is not None and (now - last.ts) <= RECENTLY_WATERED_WINDOW:
        return MoistureAssessment(
            state=RECENTLY_WATERED, urgency=0.0, calculated_moisture=current,
            days_since_watered=days_since, days_until_dry=None,
            watering_kind=last.kind, suppressed=False, rain_would_alert=None,
        )

    # Without learned thresholds or a live reading we stay neutral.
    if current is None or m_dry is None or m_max is None:
        return MoistureAssessment(
            state=NORMAL, urgency=0.0, calculated_moisture=current,
            days_since_watered=days_since, days_until_dry=None,
            watering_kind=None, suppressed=False, rain_would_alert=None,
        )

    if dormant:
        # Metabolic slowdown: relax both bounds.
        dry_too_long_after = dry_too_long_after * 2
        wet_too_long_after = wet_too_long_after * 2

    wet_ceiling = m_max - 0.10 * (m_max - m_dry)
    getting_dry_line = m_dry + 0.15 * (m_max - m_dry)

    below_dry = current < m_dry
    above_wet = current >= wet_ceiling

    # Duration timers: prefer persisted, reboot-safe timers when supplied,
    # otherwise walk the sample buffer (test/fallback path).
    dry_run = (
        dry_run_minutes if dry_run_minutes is not None
        else current_run_minutes(compensated, max_gap, lambda v: v < m_dry)
    )
    wet_run = (
        wet_run_minutes if wet_run_minutes is not None
        else current_run_minutes(compensated, max_gap, lambda v: v >= wet_ceiling)
    )

    days_until_dry = None
    if drying_rate and drying_rate > 0 and current > m_dry:
        days_until_dry = (current - m_dry) / drying_rate

    # Base classification -------------------------------------------------
    if current >= wet_ceiling and wet_run >= wet_too_long_after.total_seconds() / 60:
        base_state = WET_TOO_LONG
        urgency = 60.0
    elif current < m_dry and dry_run >= dry_too_long_after.total_seconds() / 60:
        base_state = DRY_TOO_LONG
        urgency = 90.0
    elif current < getting_dry_line:
        base_state = GETTING_DRY
        urgency = 55.0
    elif current <= wet_ceiling:
        base_state = DRYING_NORMALLY if current < m_max else NORMAL
        urgency = 10.0
    else:
        base_state = NORMAL
        urgency = 0.0

    # Revocable rain suppression (outdoor only) ---------------------------
    suppressed = False
    rain_would_alert = None
    if (
        placement == "outdoor"
        and base_state in (GETTING_DRY, DRY_TOO_LONG)
        and rain_expected(forecast_precip_mm, profile_rain_limit_mm)
    ):
        # Downgrade, don't mute: keep the underlying state visible and cut
        # urgency. Recomputed every cycle, so it revokes if the forecast changes.
        rain_would_alert = base_state
        base_state = SUPPRESSED_BY_RAIN
        urgency = min(urgency, 25.0)
        suppressed = True

    return MoistureAssessment(
        state=base_state, urgency=round(urgency, 1), calculated_moisture=round(current, 1),
        days_since_watered=round(days_since, 2) if days_since is not None else None,
        days_until_dry=round(days_until_dry, 2) if days_until_dry is not None else None,
        watering_kind=last.kind if last is not None else None,
        suppressed=suppressed, rain_would_alert=rain_would_alert,
        below_dry=below_dry, above_wet=above_wet,
    )
