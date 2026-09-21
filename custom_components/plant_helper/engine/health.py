"""Plant health score (design.md section 10) — review shortcoming #3.

An explicit, weighted, *pure* function of measured growing conditions. Starts
from a baseline of stability (100) and is reduced by sustained deviation, blended
across the measured pillars. Notification side effects live elsewhere; this
returns only a number, a state band, and the per-pillar components.

Design rules honoured:
  * Frozen during calibration — no score (and therefore no false penalty) until
    baselines exist.
  * Normalised under dormancy — a relaxed floor so a legitimately slow winter
    plant is not marked unhealthy.
  * Pillars with no data are excluded and the weights renormalise, so a plant
    without (say) a light sensor is scored on what it does have rather than
    penalised for what it lacks.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

# Pillar weights (moisture is the primary care engine, design.md section 7).
WEIGHT_MOISTURE = 0.45
WEIGHT_LIGHT = 0.30
WEIGHT_THERMAL = 0.25

# Per-profile weights: a succulent's health is dominated by not-overwatering and
# by getting enough light; a moisture-loving plant's by moisture. The default
# balanced profile keeps the original split. Each row sums to 1.0.
PROFILE_WEIGHTS = {
    "balanced": (WEIGHT_MOISTURE, WEIGHT_LIGHT, WEIGHT_THERMAL),
    "dry_tolerant": (0.35, 0.40, 0.25),      # light-hungry, dryness less critical
    "moisture_loving": (0.55, 0.25, 0.20),   # moisture is king
}


def _weights_for(profile: str | None) -> tuple[float, float, float]:
    return PROFILE_WEIGHTS.get(profile or "balanced", PROFILE_WEIGHTS["balanced"])

# Health state bands.
EXCELLENT, GOOD, FAIR, POOR, CRITICAL = "excellent", "good", "fair", "poor", "critical"
CALIBRATING = "calibrating"
UNAVAILABLE = "unavailable"

# Dormancy relaxes the floor: a dormant plant cannot score below this from
# measured conditions alone.
DORMANCY_FLOOR = 60.0


@dataclass(frozen=True, slots=True)
class HealthResult:
    score: float | None            # None while calibrating
    state: str
    components: dict[str, float]   # pillar -> score actually used


def _band(score: float) -> str:
    if score >= 90:
        return EXCELLENT
    if score >= 75:
        return GOOD
    if score >= 55:
        return FAIR
    if score >= 30:
        return POOR
    return CRITICAL


def evaluate_health(
    *,
    moisture_score: float | None,
    light_score: float | None,
    thermal_score: float | None,
    calibrating: bool = False,
    dormant: bool = False,
    profile: str | None = None,
) -> HealthResult:
    """Weighted health from available pillar scores.

    Each pillar score is 0-100 (100 = ideal). A None pillar is excluded and the
    remaining weights renormalise. Returns a frozen (None) score while the plant
    is still calibrating.
    """
    if calibrating:
        return HealthResult(None, CALIBRATING, {})

    w_moist, w_light, w_thermal = _weights_for(profile)
    pillars = (
        ("moisture", moisture_score, w_moist),
        ("light", light_score, w_light),
        ("thermal", thermal_score, w_thermal),
    )
    finite_pillars = [
        (name, float(score), weight)
        for name, score, weight in pillars
        if score is not None and math.isfinite(float(score))
    ]
    used = {
        name: max(0.0, min(100.0, score))
        for name, score, _ in finite_pillars
    }
    total_weight = sum(weight for _, _, weight in finite_pillars)

    if not used or total_weight <= 0:
        # No measurable pillar at all -> neutral, not a penalty.
        return HealthResult(None, CALIBRATING, {})

    weighted = sum(
        used[name] * weight for name, _, weight in finite_pillars
    ) / total_weight
    score = weighted

    if dormant:
        score = max(score, DORMANCY_FLOOR)

    score = round(score, 1)
    return HealthResult(score, _band(score), used)
