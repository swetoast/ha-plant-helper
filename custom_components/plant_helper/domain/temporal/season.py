"""Seasonal dormancy as a multiplier on the expected drying rate.

Pure. A dormant plant uses less water and dries more slowly, so wet soil is more
normal and should be tolerated longer before it reads too_wet. That is exactly a
lower drying coefficient, so dormancy is expressed as a multiplier (< 1 when
dormant) that drying.py folds into the coefficient. The coefficient's own clamp
bounds the effect, so a season can never fully silence a genuinely waterlogged
plant. Overwatering is the real dormancy-season risk, so this deliberately
relaxes only the wet side; a genuinely dry plant still reads needs_water.

Signals come from the interpretation layer already computed per plant: outdoor
``growth_season`` (bool), indoor ``season`` / ``day_length``. Every constant is a
starting value to tune against fixtures.
"""
from __future__ import annotations

from typing import Mapping

DORMANT_MULTIPLIER = 0.7  # deep dormancy: markedly slower drying
SHOULDER_MULTIPLIER = 0.85  # autumn / shortening days
DORMANCY_DAYLIGHT_HOURS = 10.0  # below this day length reads as dormant


def dormancy_multiplier(signals: Mapping | None) -> float:
    """Return a drying multiplier: 1.0 in active growth, lower when dormant."""
    if not signals:
        return 1.0

    growth = signals.get("growth_season")
    if growth is not None:  # outdoor: a definite seasonal signal
        return DORMANT_MULTIPLIER if growth is False else 1.0

    season = signals.get("season")
    if isinstance(season, str):
        name = season.lower()
        if name == "winter":
            return DORMANT_MULTIPLIER
        if name in ("autumn", "fall"):
            return SHOULDER_MULTIPLIER
        if name in ("spring", "summer"):
            return 1.0

    day_length = _as_float(signals.get("day_length"))
    if day_length is not None and day_length < DORMANCY_DAYLIGHT_HOURS:
        return DORMANT_MULTIPLIER

    return 1.0


def is_dormant(signals: Mapping | None) -> bool:
    return dormancy_multiplier(signals) < 1.0


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
