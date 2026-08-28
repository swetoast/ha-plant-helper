"""Cross-model precedence (review shortcoming #4).

Moisture, light, thermal and dormancy can each raise a state in the same cycle.
This module is the single priority ladder that collapses them into one primary
issue, one recommended care action, and one human-readable reason, so the UI
never shows contradictory guidance.

Ordering is by danger to the plant, with the sensor-fault gate on top: if care
was halted (critical battery / no valid sensors) we describe the fault instead
of emitting a possibly-false plant status (design.md section 6).
"""

from __future__ import annotations

from dataclasses import dataclass

from . import moisture_model as mm
from . import light_model as lm
from . import thermal_model as th

# Care actions
WATER_NOW = "water_now"
WATER_SOON = "water_soon"
REDUCE_WATER = "reduce_water"
SEEK_SHELTER = "seek_shelter"
MOVE_WARMER = "move_warmer"
MOVE_COOLER = "move_cooler"
CLEAR_OBSTRUCTION = "clear_obstruction"
INCREASE_LIGHT = "increase_light"
CHECK_SENSOR = "check_sensor"
MONITOR = "monitor"
NONE = "none"


@dataclass(frozen=True, slots=True)
class Precedence:
    primary_issue: str
    care_action: str
    reason: str
    severity: int          # 0 (none) .. 100 (act now)


def resolve_precedence(
    *,
    care_ok: bool,
    care_reason: str,
    moisture_state: str,
    light_state: str,
    light_obstruction: bool,
    thermal_state: str,
    dormant: bool,
) -> Precedence:
    """Collapse all model states into one prioritised recommendation."""

    # 0. Sensor fault gate — describe the fault, do not guess plant status.
    if not care_ok:
        if care_reason == "battery_critical":
            return Precedence(
                "sensor_fault", CHECK_SENSOR,
                "Sensor battery critical — readings paused until replaced.", 95,
            )
        return Precedence(
            "sensor_fault", CHECK_SENSOR,
            "No usable sensor readings — check the plant's sensors.", 90,
        )

    # 1. Severe weather (outdoor) outranks everything else actionable.
    if thermal_state == th.WEATHER_HAZARD_IMMINENT:
        return Precedence(
            "weather_hazard", SEEK_SHELTER,
            "Severe weather imminent — move the plant to shelter.", 92,
        )

    # 2. Water extremes.
    if moisture_state == mm.DRY_TOO_LONG:
        return Precedence(
            "underwatered", WATER_NOW,
            "Soil has been dry too long — water now.", 90,
        )
    if moisture_state == mm.WET_TOO_LONG:
        return Precedence(
            "overwatered", REDUCE_WATER,
            "Soil has stayed saturated too long — hold off and check drainage.", 70,
        )

    # 3. Thermal extremes (sustained).
    if thermal_state == th.COLD_TOO_LONG:
        return Precedence("cold_stress", MOVE_WARMER,
                          "Too cold for too long — move somewhere warmer.", 75)
    if thermal_state == th.WARM_TOO_LONG:
        return Precedence("heat_stress", MOVE_COOLER,
                          "Too warm for too long — move somewhere cooler.", 75)

    # 4. Getting dry (pre-emptive).
    if moisture_state == mm.GETTING_DRY:
        return Precedence("getting_dry", WATER_SOON,
                          "Soil is getting dry — water soon.", 55)

    # 5. Light problems.
    if light_obstruction:
        return Precedence("light_obstruction", CLEAR_OBSTRUCTION,
                          "Light obstruction detected — clear what's blocking the window.", 50)
    if light_state in (lm.LOWER_THIS_WEEK, lm.LOWER_3D, lm.LOWER_DAILY_LIGHT):
        return Precedence("low_light", INCREASE_LIGHT,
                          "Daily light is below target — give it a brighter spot.", 45)

    # 6. Milder thermal variation.
    if thermal_state in (th.COOLER_THAN_USUAL, th.WARMER_THAN_USUAL, th.SWINGY):
        return Precedence("temperature_variation", MONITOR,
                          "Temperature is drifting from its norm — keep an eye on it.", 25)

    # 7. Informational holds.
    if moisture_state == mm.SUPPRESSED_BY_RAIN:
        return Precedence("rain_expected", MONITOR,
                          "Dry, but rain is forecast — holding off on watering.", 20)
    if dormant:
        return Precedence("dormant", NONE,
                          "Dormant for the season — care is intentionally reduced.", 10)
    if light_state == lm.RECOVERING:
        return Precedence("light_recovering", MONITOR,
                          "Light is recovering after a dim spell.", 10)

    # 8. All clear.
    return Precedence("none", NONE, "Conditions are within range.", 0)
