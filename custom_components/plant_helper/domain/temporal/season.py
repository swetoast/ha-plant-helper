"""Evidence-based seasonal dormancy (roadmap appendix: wintering).

Pure. A plant is treated as dormant when the last 30 days show both low light
and a slight cooling: at least DORMANCY_MIN_DAYS of judged light days whose mean
effective exposure is below the profile's threshold, and a recent week that is
cooler than the weeks before it (or simply a cool room). Without a temperature
sensor the light evidence alone decides. An outdoor plant is also dormant when
Open-Meteo reports it is outside the growing season.

Dormancy lengthens the tolerated wet period (see drying.py), lowers the
needs_water threshold by NEEDS_WATER_RELAX so a resting plant is not prompted at
its summer rhythm, and adds reason ``seasonal_dormancy`` to calm statuses.
"""
from __future__ import annotations

from typing import Sequence

from .daily import DailySummary

DORMANCY_MIN_DAYS = 14
DORMANCY_WINDOW_DAYS = 30
DORMANCY_LIGHT_LUX_HOURS = {
    "dry": 2500.0,
    "balanced": 4000.0,
    "moist": 5000.0,
    "custom": 4000.0,
}
RECENT_DAYS = 7
TEMPERATURE_DROP = 0.5
COOL_ROOM = 20.0
NEEDS_WATER_RELAX = 0.75


def assess_dormancy(
    days: Sequence[DailySummary],
    *,
    profile: str,
    placement: str,
    growth_season: bool | None = None,
) -> bool:
    if placement == "outdoor" and growth_season is False:
        return True
    window = list(days)[-DORMANCY_WINDOW_DAYS:]
    judged = [d.light for d in window if d.light is not None and d.light.judged]
    if len(judged) < DORMANCY_MIN_DAYS:
        return False
    mean_light = sum(d.effective_light_exposure for d in judged) / len(judged)
    threshold = DORMANCY_LIGHT_LUX_HOURS.get(profile, DORMANCY_LIGHT_LUX_HOURS["balanced"])
    if mean_light >= threshold:
        return False
    temps = [d.temperature_mean for d in window if d.temperature_mean is not None]
    if len(temps) <= RECENT_DAYS:
        return True
    recent = sum(temps[-RECENT_DAYS:]) / RECENT_DAYS
    earlier = sum(temps[:-RECENT_DAYS]) / (len(temps) - RECENT_DAYS)
    return recent <= earlier - TEMPERATURE_DROP or recent < COOL_ROOM


def dormant_band(band: tuple[float, float], dormant: bool) -> tuple[float, float]:
    low, high = band
    return (low * NEEDS_WATER_RELAX, high) if dormant else band
