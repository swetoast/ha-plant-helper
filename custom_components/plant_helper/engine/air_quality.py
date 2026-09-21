"""Ground-level ozone advisory (optional, outdoor only).

Ozone (O3) is the one common air pollutant with real horticultural relevance:
elevated ground-level ozone injures foliage and depresses photosynthesis in
outdoor plants. This is an *advisory* signal only — it is context, not a care
driver, so it never changes the health score or the watering/light/temperature
recommendation.

Thresholds are instantaneous proxies in micrograms per cubic metre (the unit the
AccuWeather / most AQI integrations report). Roughly 1 ppb O3 ~= 1.96 ug/m3, so:
  * elevated  >= 80 ug/m3  (~40 ppb) — sensitive species may show stress
  * high      >= 160 ug/m3 (~80 ppb) — foliar damage likely for sensitive plants
(These are single-hour proxies, not the cumulative AOT40 vegetation metric.)
"""

from __future__ import annotations

from dataclasses import dataclass

from .util import to_float

# Advisory levels
NONE = "none"
ELEVATED = "elevated"
HIGH = "high"
NOT_APPLICABLE = "not_applicable"   # indoor plants

OZONE_ELEVATED_UGM3 = 80.0
OZONE_HIGH_UGM3 = 160.0


@dataclass(frozen=True, slots=True)
class AirQualityAssessment:
    advisory: str                  # none | elevated | high | not_applicable
    ozone_ugm3: float | None
    message: str | None

    @property
    def active(self) -> bool:
        return self.advisory in (ELEVATED, HIGH)


def assess_air_quality(
    *,
    ozone_ugm3: float | None,
    placement: str,
    elevated_ugm3: float = OZONE_ELEVATED_UGM3,
    high_ugm3: float = OZONE_HIGH_UGM3,
) -> AirQualityAssessment:
    """Advisory from a ground-level ozone reading (outdoor plants only).

    Indoor plants are shielded from outdoor ozone, so they always return
    `not_applicable`. A missing reading (feature not configured / sensor down)
    returns `none` — never a false alarm.
    """
    if placement != "outdoor":
        return AirQualityAssessment(NOT_APPLICABLE, ozone_ugm3, None)
    ozone = to_float(ozone_ugm3)
    if ozone is None or ozone < 0.0:
        return AirQualityAssessment(NONE, None, None)
    if ozone >= high_ugm3:
        return AirQualityAssessment(
            HIGH, ozone,
            "High ground-level ozone — foliar damage likely for sensitive plants.",
        )
    if ozone >= elevated_ugm3:
        return AirQualityAssessment(
            ELEVATED, ozone,
            "Elevated ground-level ozone — sensitive foliage may show stress.",
        )
    return AirQualityAssessment(NONE, ozone, None)
