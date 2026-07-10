"""Smart seasonal dormancy (design.md section 5) with hysteresis (review #11).

Rather than guessing a calendar date, dormancy is inferred by cross-referencing
the macro signal (a sustained 30-day decline in outdoor SMHI PAR) with the micro
signal (a matching decline in local 24h-average soil temperature). In dormancy,
moisture timers are relaxed so dark winter cycles do not raise false
`wet_too_long` alerts.

Hysteresis prevents shoulder-season flapping:
  * Enter only on a *clear* decline in BOTH signals.
  * Exit only on a *clear* recovery in BOTH signals — a stricter, opposite-side
    threshold, never the mirror of the enter threshold.
  * A minimum dwell time holds a freshly-entered/exited state so trends that
    hover around the boundary cannot toggle it every day.
"""

from __future__ import annotations

from dataclasses import dataclass

# Enter when both 30-day slopes are below these (units per day). PAR in W/m^2,
# soil temp in deg C. Declines are negative slopes.
ENTER_PAR_SLOPE = -2.0
ENTER_TEMP_SLOPE = -0.10

# Exit requires a clear positive recovery in both — deliberately not the mirror
# of the enter thresholds, so the band between them is a dead zone.
EXIT_PAR_SLOPE = 2.0
EXIT_TEMP_SLOPE = 0.10

# Minimum days to hold a state before the opposite transition may fire.
MIN_DWELL_DAYS = 7


@dataclass(frozen=True, slots=True)
class DormancyResult:
    dormant: bool
    changed: bool
    reason: str


def evaluate_dormancy(
    *,
    currently_dormant: bool,
    days_in_state: int,
    par_slope_30d: float | None,
    soil_temp_slope_30d: float | None,
    enter_par: float = ENTER_PAR_SLOPE,
    enter_temp: float = ENTER_TEMP_SLOPE,
    exit_par: float = EXIT_PAR_SLOPE,
    exit_temp: float = EXIT_TEMP_SLOPE,
    min_dwell_days: int = MIN_DWELL_DAYS,
) -> DormancyResult:
    """Decide dormancy with enter/exit hysteresis and a dwell guard.

    Missing macro or micro data holds the current state (we never flip on a
    half-signal). Returns whether the state changed this evaluation.
    """
    if par_slope_30d is None or soil_temp_slope_30d is None:
        return DormancyResult(currently_dormant, False, "insufficient_data")

    # Dwell guard: hold a recently-changed state regardless of trend.
    if days_in_state < min_dwell_days:
        return DormancyResult(currently_dormant, False, "dwell_hold")

    if not currently_dormant:
        if par_slope_30d <= enter_par and soil_temp_slope_30d <= enter_temp:
            return DormancyResult(True, True, "entered_declining_light_and_cooling")
        return DormancyResult(False, False, "active")

    # currently dormant -> only exit on clear recovery in BOTH signals.
    if par_slope_30d >= exit_par and soil_temp_slope_30d >= exit_temp:
        return DormancyResult(False, True, "exited_recovering_light_and_warming")
    return DormancyResult(True, False, "dormant")
