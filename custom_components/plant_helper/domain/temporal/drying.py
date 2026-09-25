"""Balanced drying coefficient and the dynamic wet-duration limit (roadmap 6).

Pure. k_drying expresses how strongly the environment is expected to dry the
soil, on a 0..1 scale, as a weighted blend of NORMALIZED inputs (raw Celsius,
percent, lux and W/m2 are never combined directly):

    k = 0.40 * moisture trend + 0.20 * local temperature
      + 0.15 * vapor dryness  + 0.10 * local light
      + 0.15 * bounded outdoor radiation

A missing input contributes the neutral value 0.5 at its own weight, so outdoor
radiation can never carry more than its 15% share. Vapor dryness is the true
vapor pressure deficit (Tetens equation), per the roadmap appendix.

k maps to a wet-duration factor: 0.5 is neutral (1.0x), 1.0 shortens the
allowance to 0.65x, 0.0 lengthens it to 2.0x. Seasonal dormancy extends the
allowance further, up to DORMANT_MAX_EXTEND. The realized moisture slope stays
the safety override in the moisture state machine: soil that is measurably
drying reads as drying whatever this prediction says.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

WEIGHTS = {
    "slope": 0.40,
    "temperature": 0.20,
    "vapor": 0.15,
    "light": 0.10,
    "radiation": 0.15,
}
NEUTRAL = 0.5
SLOPE_REF = 0.5  # percent per hour (12 points a day) counts as fast drying
TEMP_MIN = 10.0
TEMP_MAX = 30.0
VPD_REF = 2.0  # kPa
LIGHT_REF = 20000.0  # lux-hours over the trailing 24 hours
RADIATION_REF = 6000.0  # Wh/m2 over 24 hours

MAX_SHORTEN = 0.65
MAX_EXTEND = 2.0
DORMANT_FACTOR = 1.5
DORMANT_MAX_EXTEND = 3.0

CONTEXT_HIGH = 0.65
CONTEXT_LOW = 0.35


@dataclass(frozen=True, slots=True)
class EnvironmentalDryingContext:
    k_drying: float
    local_moisture_slope: float | None
    outdoor_radiation_bounded: float | None
    adjusted_wet_duration_limit: float
    confidence: str
    vpd_kpa: float | None

    @property
    def label(self) -> str:
        if self.k_drying >= CONTEXT_HIGH:
            return "high"
        if self.k_drying <= CONTEXT_LOW:
            return "low"
        return "normal"


def vpd_kpa(temperature: float | None, humidity: float | None) -> float | None:
    """Vapor pressure deficit in kPa (Tetens), or None without both inputs."""
    if temperature is None or humidity is None:
        return None
    svp = 0.61078 * math.exp(17.27 * temperature / (temperature + 237.3))
    return max(0.0, svp * (1.0 - _clamp(humidity, 0.0, 100.0) / 100.0))


def drying_context(
    *,
    base_limit_hours: float,
    slope: float | None,
    temperature: float | None,
    humidity: float | None,
    light_lux_hours_24h: float | None,
    radiation_24h: float | None,
    dormant: bool = False,
) -> EnvironmentalDryingContext:
    vpd = vpd_kpa(temperature, humidity)
    normalized = {
        "slope": None if slope is None else _clamp(-slope / SLOPE_REF, 0.0, 1.0),
        "temperature": None if temperature is None
        else _clamp((temperature - TEMP_MIN) / (TEMP_MAX - TEMP_MIN), 0.0, 1.0),
        "vapor": None if vpd is None else _clamp(vpd / VPD_REF, 0.0, 1.0),
        "light": None if light_lux_hours_24h is None
        else _clamp(light_lux_hours_24h / LIGHT_REF, 0.0, 1.0),
        "radiation": None if radiation_24h is None
        else _clamp(radiation_24h / RADIATION_REF, 0.0, 1.0),
    }
    k = sum(
        WEIGHTS[name] * (NEUTRAL if value is None else value)
        for name, value in normalized.items()
    )
    k = _clamp(k, 0.0, 1.0)
    local = sum(1 for name in ("slope", "temperature", "vapor") if normalized[name] is not None)
    confidence = "high" if local == 3 else "medium" if local == 2 else "low"
    factor = limit_factor(k)
    ceiling = MAX_EXTEND
    if dormant:
        factor *= DORMANT_FACTOR
        ceiling = DORMANT_MAX_EXTEND
    factor = _clamp(factor, MAX_SHORTEN, ceiling)
    radiation = normalized["radiation"]
    return EnvironmentalDryingContext(
        k_drying=k,
        local_moisture_slope=slope,
        outdoor_radiation_bounded=None if radiation is None else radiation * WEIGHTS["radiation"],
        adjusted_wet_duration_limit=base_limit_hours * factor,
        confidence=confidence,
        vpd_kpa=vpd,
    )


def limit_factor(k: float) -> float:
    """Wet-duration multiplier for k: 2.0 at 0, 1.0 at 0.5, 0.65 at 1."""
    if k <= NEUTRAL:
        return MAX_EXTEND - (MAX_EXTEND - 1.0) * (k / NEUTRAL)
    return 1.0 - (1.0 - MAX_SHORTEN) * ((k - NEUTRAL) / (1.0 - NEUTRAL))


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))
