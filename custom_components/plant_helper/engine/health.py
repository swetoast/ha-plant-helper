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

# Pillar weights (moisture is the primary care engine, design.md section 7).
WEIGHT_MOISTURE = 0.45
WEIGHT_LIGHT = 0.30
WEIGHT_THERMAL = 0.25

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
) -> HealthResult:
    """Weighted health from available pillar scores.

    Each pillar score is 0-100 (100 = ideal). A None pillar is excluded and the
    remaining weights renormalise. Returns a frozen (None) score while the plant
    is still calibrating.
    """
    if calibrating:
        return HealthResult(None, CALIBRATING, {})

    pillars = (
        ("moisture", moisture_score, WEIGHT_MOISTURE),
        ("light", light_score, WEIGHT_LIGHT),
        ("thermal", thermal_score, WEIGHT_THERMAL),
    )
    used = {name: max(0.0, min(100.0, s)) for name, s, _ in pillars if s is not None}
    total_weight = sum(w for name, s, w in pillars if s is not None)

    if not used or total_weight <= 0:
        # No measurable pillar at all -> neutral, not a penalty.
        return HealthResult(None, CALIBRATING, {})

    weighted = sum(
        used[name] * w for name, s, w in pillars if s is not None
    ) / total_weight
    score = weighted

    if dormant:
        score = max(score, DORMANCY_FLOOR)

    score = round(score, 1)
    return HealthResult(score, _band(score), used)
