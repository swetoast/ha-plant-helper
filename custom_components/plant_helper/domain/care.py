from __future__ import annotations

from dataclasses import dataclass

# Moisture comfort band per care profile, as (low, high) percentages.
PROFILE_BANDS: dict[str, tuple[float, float]] = {
    "dry": (15.0, 45.0),
    "balanced": (25.0, 65.0),
    "moist": (40.0, 80.0),
    "custom": (25.0, 65.0),
}

# Below this moisture percentage the plant is treated as critically dry, and
# forecast rain suppression never holds back a watering recommendation.
CRITICAL_MOISTURE = 5.0


@dataclass(frozen=True, slots=True)
class CareDecision:
    care_status: str
    summary: str
    reason: str
    attention: bool
    health: str


def evaluate_care(
    moisture: float | None,
    profile: str,
    placement: str = "indoor",
    *,
    rain_suppression: bool = False,
) -> CareDecision:
    """Decide care status from physical moisture and outdoor rain context.

    Physical moisture stays authoritative. Rain suppression only softens an
    outdoor watering recommendation, and only while the soil is not critically
    dry.
    """
    low, high = PROFILE_BANDS.get(profile, PROFILE_BANDS["balanced"])
    if moisture is None:
        return CareDecision(
            "waiting_for_data",
            "Waiting for a valid moisture reading",
            "moisture_unavailable",
            False,
            "unknown",
        )
    if moisture < low:
        if (
            placement == "outdoor"
            and rain_suppression
            and moisture >= CRITICAL_MOISTURE
        ):
            return CareDecision(
                "watering_paused",
                "Soil moisture is below the selected care profile, but rain is expected soon; watering is paused",
                "rain_expected",
                False,
                "needs_water",
            )
        return CareDecision(
            "water_soon",
            "Soil moisture is below the selected care profile",
            "soil_dry",
            True,
            "needs_water",
        )
    if moisture > high:
        return CareDecision(
            "too_wet",
            "Soil moisture is above the selected care profile",
            "soil_wet",
            True,
            "too_wet",
        )
    return CareDecision(
        "normal",
        "Soil moisture is within the selected care profile",
        "moisture_in_range",
        False,
        "good",
    )
