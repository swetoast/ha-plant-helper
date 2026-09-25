"""Combined temperature, humidity and moisture conditions (roadmap Phase 3).

Pure. These conditions explain timing and shape summaries; they are never
separate public entities. VPD (roadmap appendix) sharpens the humidity side:
above VPD_HIGH the air pulls water fast, below VPD_LOW it barely does.
"""
from __future__ import annotations

from dataclasses import dataclass

from .moisture import DRYING_SLOPE

VPD_HIGH = 1.5
VPD_LOW = 0.4
WEAK_SLOPE = DRYING_SLOPE  # a slower decline than "drying" is weak

_COLD = frozenset({"cool", "cold", "prolonged_cold"})
_WARM = frozenset({"warm", "hot", "prolonged_heat"})
_DRY_AIR = frozenset({"dry_air", "prolonged_dry_air"})
_HUMID = frozenset({"humid_air", "prolonged_humidity"})


@dataclass(frozen=True, slots=True)
class CombinedCondition:
    name: str
    summary: str


def combined_condition(
    *,
    soil_wet: bool,
    slope: float | None,
    temperature_condition: str | None,
    humidity_condition: str | None,
    vpd: float | None,
) -> CombinedCondition | None:
    cold = temperature_condition in _COLD
    warm = temperature_condition in _WARM
    dry_air = humidity_condition in _DRY_AIR or (vpd is not None and vpd > VPD_HIGH)
    humid = humidity_condition in _HUMID or (vpd is not None and vpd < VPD_LOW)
    weak = slope is None or slope > -WEAK_SLOPE
    if soil_wet and cold and weak:
        return CombinedCondition(
            "cold_wet_condition",
            "Soil is drying slowly because it is cool and humid" if humid
            else "Soil is staying wet because it is cool around the plant",
        )
    if slope is not None and slope <= -WEAK_SLOPE and warm and dry_air:
        return CombinedCondition(
            "accelerated_drying",
            "Soil is drying quickly because it is warm and the air is dry",
        )
    if soil_wet and warm and humid:
        return CombinedCondition(
            "slow_drying_humid_condition",
            "Soil is drying slowly because it is warm and humid",
        )
    return None
