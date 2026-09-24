"""Environmental drying coefficient and the dynamic wet-duration limit.

Pure and testable. The coefficient expresses how fast the environment is
expected to dry the soil relative to a baseline: 1.0 is baseline, above 1 is
faster (warm, dry, high evapotranspiration), below 1 is slower. The wet-duration
limit is scaled by it and bounded so a prediction can never shorten the
allowance by more than 35% or extend it by more than 100%.

The realized moisture slope is the roadmap's safety override and lives in the
moisture state machine, not here: a soil that is measurably drying reads as
``drying`` regardless of what this prediction says. This module only adjusts how
long a genuinely stalled wet soil is tolerated before it escalates.

Every constant here is a starting value to tune against fixtures.
"""
from __future__ import annotations

from typing import Mapping

from .season import dormancy_multiplier

# Baselines: the signal value treated as "ordinary" drying.
BASELINE_ET0_24H = 3.0  # mm of reference evapotranspiration over 24 h
BASELINE_SOIL_TEMP = 20.0  # Celsius
BASELINE_HUMIDITY = 50.0  # percent

# Indoor fallback sensitivities when no forecast evapotranspiration is present.
SOIL_TEMP_PER_DEGREE = 0.02  # coefficient change per Celsius from baseline
HUMIDITY_PER_PERCENT = 0.004  # coefficient change per percent from baseline

# Coefficient clamp, then the limit bounds relative to the base limit.
COEFF_MIN = 0.5
COEFF_MAX = 2.0
MAX_SHORTEN = 0.65  # limit never below 65% of base
MAX_EXTEND = 2.0  # limit never above 200% of base

# Coefficient thresholds for the human-facing drying speed. These share the
# outdoor interpretation's vocabulary (low / normal / high) so the same word
# means the same thing on an indoor and an outdoor plant.
CONTEXT_LOW = 0.85
CONTEXT_HIGH = 1.3


def drying_context(coefficient: float) -> str:
    """Bucket the coefficient into low / normal / high drying, for both placements."""
    if coefficient >= CONTEXT_HIGH:
        return "high"
    if coefficient <= CONTEXT_LOW:
        return "low"
    return "normal"


def drying_coefficient(signals: Mapping | None) -> float:
    """Expected drying rate relative to baseline (bounded to COEFF_MIN..MAX).

    The environmental estimate is scaled by seasonal dormancy: a dormant plant
    dries slower, which lengthens its tolerated wet period. The final clamp
    bounds the seasonal effect too.
    """
    if not signals:
        return 1.0
    et0 = _as_float(signals.get("et0_24h"))
    if et0 is not None:
        base = et0 / BASELINE_ET0_24H
    else:
        base = 1.0
        soil_temp = _as_float(signals.get("soil_temperature"))
        if soil_temp is not None:
            base += (soil_temp - BASELINE_SOIL_TEMP) * SOIL_TEMP_PER_DEGREE
        humidity = _as_float(signals.get("humidity"))
        if humidity is not None:
            base += (BASELINE_HUMIDITY - humidity) * HUMIDITY_PER_PERCENT
    return _clamp(base * dormancy_multiplier(signals), COEFF_MIN, COEFF_MAX)


def adjusted_wet_limit(base_hours: float, coefficient: float) -> float:
    """Scale the wet-duration limit by expected drying, bounded per the roadmap.

    Faster expected drying shortens the allowance, slower drying extends it.
    """
    raw = base_hours / coefficient if coefficient > 0 else base_hours
    return _clamp(raw, base_hours * MAX_SHORTEN, base_hours * MAX_EXTEND)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
