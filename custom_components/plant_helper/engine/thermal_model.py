"""Temperature & environmental context (design.md section 9).

Temperature is a *modifier* that explains moisture behaviour, plus a source of
its own alert states. Three jobs:

  * Cloud dynamics -> a drying-rate modifier. Heavy cloud (high diffuse/global
    irradiance ratio) slows drying; a forecast turning persistently wet
    pre-emptively lowers the modelled drying rate.
  * Thermal state -> stable / cooler / warmer / cold_too_long / warm_too_long /
    swingy, judged against the learned mean and diurnal swing.
  * Severe-weather defense (outdoor only) -> weather_hazard_imminent when the
    hourly forecast shows lightning / hail / extreme wind within the horizon.

Notification firing lives elsewhere; this model only reports the hazard *state*.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

# Thermal & hazard states (design.md section 9)
STABLE = "stable"
COOLER_THAN_USUAL = "cooler_than_usual"
WARMER_THAN_USUAL = "warmer_than_usual"
COLD_TOO_LONG = "cold_too_long"
WARM_TOO_LONG = "warm_too_long"
SWINGY = "swingy"
WEATHER_HAZARD_IMMINENT = "weather_hazard_imminent"
UNKNOWN = "unknown"

# How far from the learned mean counts as "cooler/warmer than usual" (deg C).
DEVIATION_C = 3.0
# Today's swing beyond learned swing * this factor reads as "swingy".
SWING_FACTOR = 1.75
# Minutes outside band before "too_long".
TOO_LONG_MINUTES = 180.0

# Cloud dynamics: forecast turning persistently wet lowers drying by this much.
FORECAST_WET_DRYING_CUT = 0.20
WET_CONDITIONS = {"cloudy", "rainy", "pouring", "snowy", "snowy-rainy", "hail"}

# Severe-weather triggers.
HAZARD_CONDITIONS = {"lightning", "lightning-rainy", "hail", "exceptional"}
EXTREME_WIND_GUST_KMH = 40.0

# Outdoor ET0 drying pressure. ET0 is a reference surface, not the plant or pot,
# so its influence is deliberately modest and bounded. Around 3 mm/day is
# neutral; each 1 mm/day deviation changes the learned rate by 5%, capped at
# -15% / +15%. Missing, invalid, or indoor ET0 is neutral.
ET0_NEUTRAL_MM_DAY = 3.0
ET0_CHANGE_PER_MM = 0.05
ET0_MODIFIER_MIN = 0.85
ET0_MODIFIER_MAX = 1.15
COMBINED_DRYING_MODIFIER_MIN = 0.60
COMBINED_DRYING_MODIFIER_MAX = 1.15


def drying_modifier_from_et0(
    et0_next_24h_mm: float | None,
    *,
    placement: str,
) -> float:
    """Bounded outdoor modifier from 24-hour reference evapotranspiration."""
    if placement != "outdoor" or et0_next_24h_mm is None:
        return 1.0
    try:
        et0 = float(et0_next_24h_mm)
    except (TypeError, ValueError):
        return 1.0
    if et0 < 0.0 or et0 > 30.0:
        return 1.0
    raw = 1.0 + (et0 - ET0_NEUTRAL_MM_DAY) * ET0_CHANGE_PER_MM
    return max(ET0_MODIFIER_MIN, min(ET0_MODIFIER_MAX, raw))


def combine_drying_modifiers(environmental: float, et0: float) -> float:
    """Combine existing weather context with ET0 under one strict bound."""
    return max(
        COMBINED_DRYING_MODIFIER_MIN,
        min(COMBINED_DRYING_MODIFIER_MAX, environmental * et0),
    )


def cloud_factor(diffuse_irradiance: float | None, global_irradiance: float | None) -> float | None:
    """Fraction of light that is diffuse (0 clear .. 1 fully overcast)."""
    if diffuse_irradiance is None or global_irradiance is None or global_irradiance <= 0:
        return None
    return max(0.0, min(1.0, diffuse_irradiance / global_irradiance))


def drying_modifier_from_cloud(cf: float | None) -> float:
    """Multiplier on drying rate from live cloud cover (heavier cloud -> slower).

    Clear sky (cf ~ 0) -> 1.0; fully overcast (cf ~ 1) -> ~0.75.
    """
    if cf is None:
        return 1.0
    return 1.0 - 0.25 * cf


def drying_modifier_from_forecast(next24_conditions: Sequence[str]) -> float:
    """Multiplier from the forward 24h forecast.

    If the majority of the next 24h is a wet condition, pre-emptively cut the
    drying rate (design.md section 9 predictive modification).
    """
    conds = [str(c).lower() for c in next24_conditions if c]
    if not conds:
        return 1.0
    wet = sum(1 for c in conds if c in WET_CONDITIONS)
    if wet / len(conds) >= 0.5:
        return 1.0 - FORECAST_WET_DRYING_CUT
    return 1.0


@dataclass(frozen=True, slots=True)
class ForecastHour:
    hours_ahead: float
    condition: str
    wind_gust_kmh: float | None = None
    precipitation_mm: float | None = None
    precipitation_probability: float | None = None


def detect_hazard(
    forecast: Sequence[ForecastHour],
    *,
    placement: str,
    horizon_hours: float = 12.0,
) -> tuple[bool, str | None]:
    """Severe-weather hazard within the horizon (outdoor plants only)."""
    if placement != "outdoor":
        return (False, None)
    for fh in forecast:
        if fh.hours_ahead < 0 or fh.hours_ahead > horizon_hours:
            continue
        cond = str(fh.condition).lower()
        gust = fh.wind_gust_kmh or 0.0
        if cond in HAZARD_CONDITIONS:
            return (True, cond)
        if "wind" in cond and gust >= EXTREME_WIND_GUST_KMH:
            return (True, "windy")
        if gust >= EXTREME_WIND_GUST_KMH:
            return (True, "wind_gust")
    return (False, None)


def aggregate_forecast_precip(
    forecast: Sequence[ForecastHour],
    *,
    horizon_hours: float = 48.0,
) -> float:
    """Sum forecast precipitation over the horizon (feeds rain suppression)."""
    return sum(
        (fh.precipitation_mm or 0.0)
        for fh in forecast
        if 0 <= fh.hours_ahead <= horizon_hours
    )


def max_forecast_precip_probability(
    forecast: Sequence[ForecastHour],
    *,
    horizon_hours: float = 48.0,
) -> float | None:
    """Highest valid precipitation probability in the selected horizon."""
    values = [
        float(fh.precipitation_probability)
        for fh in forecast
        if 0 <= fh.hours_ahead <= horizon_hours
        and fh.precipitation_probability is not None
        and 0.0 <= float(fh.precipitation_probability) <= 100.0
    ]
    return max(values) if values else None


@dataclass(frozen=True, slots=True)
class ThermalAssessment:
    state: str
    score: float | None            # 0-100, 100 = at learned mean
    drying_modifier: float         # combined cloud + forecast multiplier
    hazard: bool
    hazard_type: str | None
    below_band: bool = False       # instantaneous: ref < mean - deviation
    above_band: bool = False       # instantaneous: ref > mean + deviation


def evaluate_thermal(
    *,
    current_temp: float | None,
    mean_24h: float | None,
    thermal_mean: float | None,
    swing_today: float | None,
    learned_swing: float | None,
    cold_run_minutes: float = 0.0,
    warm_run_minutes: float = 0.0,
    cloud: float | None = None,
    forecast_next24: Sequence[str] = (),
    hazard: bool = False,
    hazard_type: str | None = None,
) -> ThermalAssessment:
    """Classify thermal state and compute the drying-rate modifier."""
    modifier = drying_modifier_from_cloud(cloud) * drying_modifier_from_forecast(
        forecast_next24
    )

    # Hazard outranks the ordinary thermal state.
    if hazard:
        return ThermalAssessment(
            WEATHER_HAZARD_IMMINENT, None, modifier, True, hazard_type
        )

    ref = mean_24h if mean_24h is not None else current_temp
    if ref is None or thermal_mean is None:
        return ThermalAssessment(UNKNOWN, None, modifier, False, None)

    deviation = ref - thermal_mean
    score = max(0.0, 100.0 - abs(deviation) * 8.0)
    below_band = deviation < -DEVIATION_C
    above_band = deviation > DEVIATION_C

    # Sustained excursions first.
    if cold_run_minutes >= TOO_LONG_MINUTES and deviation < 0:
        state = COLD_TOO_LONG
    elif warm_run_minutes >= TOO_LONG_MINUTES and deviation > 0:
        state = WARM_TOO_LONG
    elif (
        swing_today is not None
        and learned_swing is not None
        and learned_swing > 0
        and swing_today > learned_swing * SWING_FACTOR
    ):
        state = SWINGY
    elif below_band:
        state = COOLER_THAN_USUAL
    elif above_band:
        state = WARMER_THAN_USUAL
    else:
        state = STABLE
    return ThermalAssessment(
        state, round(score, 1), modifier, False, None,
        below_band=below_band, above_band=above_band,
    )
