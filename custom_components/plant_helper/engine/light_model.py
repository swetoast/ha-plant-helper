"""Light model (design.md section 8).

Light is judged as an integrated accumulator, not a snapshot. The path branches
on placement:

  * Outdoor: true Daily Light Integral from SMHI PAR, compared to the learned
    baseline DLI target, with 3-day / 7-day shortfall detection.
  * Indoor: a Window Efficiency Ratio. Expected indoor light is
    K_window(elevation) x outdoor light; the observed/expected comparison
    separates a genuinely dim day (proportional drop -> normal) from an
    obstruction (disproportionate drop -> lower_daily_light + obstruction flag).

Missing external data does not fabricate a "dark" verdict: if DLI/outdoor data
is unavailable the model returns a neutral state and leaves the SMHI-baseline
failover to the source/engine layer (design.md section 6).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .calibration_math import resolve_k

# Light states (design.md section 8)
NORMAL = "normal"
HIGHER_DAILY_LIGHT = "higher_daily_light"
LOWER_DAILY_LIGHT = "lower_daily_light"
LOWER_3D = "lower_3d"
LOWER_THIS_WEEK = "lower_this_week"
RECOVERING = "recovering"
UNKNOWN = "unknown"

# Adequacy bands (fraction of target/expected).
HIGHER_RATIO = 1.10
ADEQUATE_RATIO = 0.85
# Below this, during bright outdoor conditions, a shortfall reads as obstruction.
OBSTRUCTION_RATIO = 0.60
# Outdoor PAR (W/m^2) above which we consider it solidly daytime — bright enough
# outside that a dark room implies obstruction. In PAR units to match the PAR
# reference the indoor pairing uses (was a 1000-lux value before the PAR switch,
# which PAR never reaches, silently disabling obstruction). Set well above the
# 10 W/m^2 dawn/dusk floor so overcast dawn/dusk never counts as "bright".
OUTDOOR_BRIGHT_FLOOR = 40.0


@dataclass(frozen=True, slots=True)
class LightAssessment:
    state: str
    score: float | None            # 0-100 adequacy score, None if unknown
    adequacy_ratio: float | None
    obstruction: bool
    source: str                    # "dli" | "window" | "none"
    reason: str = "ok"             # diagnostic: why the state is what it is


def _score_from_ratio(ratio: float) -> float:
    """Map an adequacy ratio to a 0-100 score (1.0 -> 100, saturating)."""
    return max(0.0, min(100.0, ratio * 100.0))


def evaluate_light_outdoor(
    *,
    today_dli: float | None,
    dli_target: float | None,
    dli_mean_3d: float | None = None,
    dli_mean_7d: float | None = None,
) -> LightAssessment:
    """Outdoor light state from DLI vs the learned baseline."""
    if today_dli is None or dli_target is None or dli_target <= 0:
        reason = "no_radiation" if today_dli is None else "calibrating"
        return LightAssessment(UNKNOWN, None, None, False, "none", reason)

    ratio = today_dli / dli_target
    score = _score_from_ratio(ratio)

    if ratio >= HIGHER_RATIO:
        return LightAssessment(HIGHER_DAILY_LIGHT, score, ratio, False, "dli")
    if ratio >= ADEQUATE_RATIO:
        return LightAssessment(NORMAL, score, ratio, False, "dli")

    # Below adequate: qualify by how long the shortfall has persisted.
    week_low = dli_mean_7d is not None and dli_mean_7d < ADEQUATE_RATIO * dli_target
    three_low = dli_mean_3d is not None and dli_mean_3d < ADEQUATE_RATIO * dli_target
    recovering = (
        dli_mean_3d is not None and today_dli > dli_mean_3d * 1.15
    )

    if recovering:
        state = RECOVERING
    elif week_low:
        state = LOWER_THIS_WEEK
    elif three_low:
        state = LOWER_3D
    else:
        state = LOWER_DAILY_LIGHT
    return LightAssessment(state, score, ratio, False, "dli")


@dataclass(frozen=True, slots=True)
class IndoorLightObservation:
    ts: datetime
    elevation_deg: float
    indoor_lux: float
    outdoor_lux: float


def indoor_light_hours(
    observations: Sequence[IndoorLightObservation],
    k_by_band: dict[str, float] | None,
    k_scalar: float | None,
    max_gap: timedelta,
) -> tuple[float, float, float, float]:
    """Integrate observed vs K-expected indoor lux-hours over the day.

    Returns (observed_hours, expected_hours, bright_observed, bright_expected),
    where the bright-* totals only accumulate over intervals whose mean outdoor
    lux clears the bright floor (used for obstruction, which is only meaningful
    when there is outdoor light to be blocked). Trapezoidal over real timestamps.
    """
    obs = sorted(observations, key=lambda o: o.ts)
    max_minutes = max_gap.total_seconds() / 60.0
    observed = expected = bright_obs = bright_exp = 0.0
    for a, b in zip(obs, obs[1:]):
        minutes = (b.ts - a.ts).total_seconds() / 60.0
        if minutes <= 0:
            continue
        hours = min(minutes, max_minutes) / 60.0
        mean_indoor = (a.indoor_lux + b.indoor_lux) / 2.0
        mean_outdoor = (a.outdoor_lux + b.outdoor_lux) / 2.0
        mean_elev = (a.elevation_deg + b.elevation_deg) / 2.0
        k = resolve_k(mean_elev, k_by_band, k_scalar)
        observed += mean_indoor * hours
        if k is not None:
            exp = k * mean_outdoor * hours
            expected += exp
            if mean_outdoor >= OUTDOOR_BRIGHT_FLOOR:
                bright_obs += mean_indoor * hours
                bright_exp += exp
    return observed, expected, bright_obs, bright_exp


def evaluate_light_indoor(
    *,
    observations: Sequence[IndoorLightObservation],
    k_by_band: dict[str, float] | None,
    k_scalar: float | None,
    max_gap: timedelta,
    daily_target_hours: float | None = None,
    adequacy_3d: float | None = None,
    adequacy_7d: float | None = None,
    settled: bool = True,
) -> LightAssessment:
    """Indoor light state via the window-efficiency ratio + obstruction check.

    Obstruction is a *relative* drop against the learned window baseline, so it is
    only reported when that baseline is settled (`settled=True`). While the window
    coefficient is still provisional (calibration), the level is reported but no
    obstruction 'problem' is raised — an unsettled baseline cannot reliably tell an
    obstruction from a plain dim day, and a plant with no blinds must never be
    complained about.
    """
    if not observations:
        # No paired daylight observations at all: either no light (lux) sensor is
        # linked, no outdoor radiation reference is available yet, or their
        # timestamps do not overlap. The coordinator adds which of these applies.
        return LightAssessment(UNKNOWN, None, None, False, "none", "no_observations")
    if k_by_band is None and k_scalar is None:
        # Observations exist but no window coefficient yet (still gathering data /
        # too few daylight hours for even a provisional value).
        return LightAssessment(UNKNOWN, None, None, False, "none", "calibrating")

    observed, expected, bright_obs, bright_exp = indoor_light_hours(
        observations, k_by_band, k_scalar, max_gap
    )
    if expected <= 0:
        return LightAssessment(UNKNOWN, None, None, False, "window", "no_daylight_yet")

    # Obstruction: during bright outdoor conditions the room got far less than
    # the window should pass -> something is blocking it (disproportionate drop).
    # Only trustworthy against a settled baseline; suppressed while provisional so
    # a no-blinds window is never falsely flagged during calibration.
    obstruction = (
        settled and bright_exp > 0 and (bright_obs / bright_exp) < OBSTRUCTION_RATIO
    )

    # Adequacy against the learned indoor daily light target if available,
    # otherwise against the K-expected total (i.e. "did the room get what this
    # window normally delivers").
    denom = daily_target_hours if daily_target_hours and daily_target_hours > 0 else expected
    ratio = observed / denom
    score = _score_from_ratio(ratio)

    if obstruction:
        return LightAssessment(LOWER_DAILY_LIGHT, score, ratio, True, "window")
    if ratio >= HIGHER_RATIO:
        return LightAssessment(HIGHER_DAILY_LIGHT, score, ratio, False, "window")
    if ratio >= ADEQUATE_RATIO:
        return LightAssessment(NORMAL, score, ratio, False, "window")

    week_low = adequacy_7d is not None and adequacy_7d < ADEQUATE_RATIO
    three_low = adequacy_3d is not None and adequacy_3d < ADEQUATE_RATIO
    recovering = adequacy_3d is not None and ratio > adequacy_3d * 1.15

    if recovering:
        state = RECOVERING
    elif week_low:
        state = LOWER_THIS_WEEK
    elif three_low:
        state = LOWER_3D
    else:
        state = LOWER_DAILY_LIGHT
    return LightAssessment(state, score, ratio, False, "window")


# --- absolute light adequacy from species preference (advisory only) ------
#
# The window-transmission model above answers "is the plant getting all the light
# this window offers?" (obstruction). It cannot answer "is this location bright
# enough for this species at all?" — an unobstructed but fundamentally dark corner
# reads normal. This advisory closes that gap using the species light preference,
# staying "a say, not the wheel": it never changes health or a care action, it
# only surfaces that the spot itself may be wrong.

# Approximate minimum sustained bright-time indoor illuminance (lux) below which a
# plant of each preference will genuinely decline (not merely "less than ideal").
# Deliberately conservative — low-light plants (snake, ZZ, pothos) tolerate very
# dim spots, so this must not nag a healthy plant in a normal Nordic window. The
# advisory is for "this spot is too dark for this plant to survive here", not for
# "brighter would be nicer".
LIGHT_FLOOR_LUX = {
    "low_light": 100.0,        # snake/ZZ/pothos survive well below a bright window
    "bright_indirect": 500.0,  # most tropicals struggle when persistently dimmer
    "full_sun": 1500.0,        # succulents/cacti etiolate below this
}

# Require a real sample of bright-time observations before advising, so a single
# overcast reading (or a thin buffer) never triggers a false "under_lit".
MIN_BRIGHT_OBS_FOR_ADEQUACY = 6


@dataclass(frozen=True, slots=True)
class LightAdequacyAssessment:
    state: str                       # ok | under_lit | no_reference
    daytime_lux: float | None
    required_lux: float | None
    message: str | None

    @property
    def active(self) -> bool:
        return self.state == "under_lit"


def species_light_adequacy(
    observations: Sequence[IndoorLightObservation],
    light_preference: str | None,
    *,
    bright_floor: float = OUTDOOR_BRIGHT_FLOOR,
) -> LightAdequacyAssessment:
    """Advisory: is this indoor spot bright enough for the species at all?

    Uses the plant's own median indoor illuminance during bright outdoor
    conditions versus a species light floor. `no_reference` when there is no
    species light preference or not enough bright-time data yet.
    """
    if not light_preference or light_preference not in LIGHT_FLOOR_LUX:
        return LightAdequacyAssessment("no_reference", None, None, None)
    bright = sorted(o.indoor_lux for o in observations if o.outdoor_lux >= bright_floor)
    if len(bright) < MIN_BRIGHT_OBS_FOR_ADEQUACY:
        # Not enough bright-time data to judge the location fairly yet.
        return LightAdequacyAssessment("no_reference", None, None, None)
    daytime_lux = bright[len(bright) // 2]  # median bright-time indoor lux
    required = LIGHT_FLOOR_LUX[light_preference]
    if daytime_lux < required:
        pref = light_preference.replace("_", " ")
        return LightAdequacyAssessment(
            "under_lit", daytime_lux, required,
            f"This spot gives about {daytime_lux:.0f} lx in bright conditions, "
            f"but a {pref} plant wants roughly {required:.0f} lx — a brighter "
            "location or a grow light would help.",
        )
    return LightAdequacyAssessment("ok", daytime_lux, required, None)
