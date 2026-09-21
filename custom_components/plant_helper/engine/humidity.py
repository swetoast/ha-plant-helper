"""Ambient-humidity advisory for indoor plants (optional, advisory only).

Many indoor sensors (including common Zigbee soil probes) also report air
humidity, and dry indoor air — especially in heating season — is a real, common
cause of decline for humidity-loving plants (browning tips, crisping edges). This
turns a signal the installation already collects into a gentle advisory.

It is *advisory* and species-gated: it only speaks when the plant actually prefers
humidity (so a succulent in dry air is never nagged), it is outdoor-irrelevant
(outdoor humidity isn't controllable), and it never changes the health score or a
care action — consistent with "external context is a say, not the wheel".
"""

from __future__ import annotations

from dataclasses import dataclass

from .util import to_float

OK = "ok"
LOW = "low"
VERY_LOW = "very_low"
NOT_APPLICABLE = "not_applicable"

# Indoor relative-humidity advisory thresholds (%) for humidity-loving plants.
HUMIDITY_LOW = 40.0        # on the dry side
HUMIDITY_VERY_LOW = 30.0   # clearly too dry


@dataclass(frozen=True, slots=True)
class HumidityAssessment:
    state: str                       # ok | low | very_low | not_applicable
    humidity_pct: float | None
    message: str | None

    @property
    def active(self) -> bool:
        return self.state in (LOW, VERY_LOW)


def assess_humidity(
    humidity_pct: float | None,
    *,
    prefers_humidity: bool,
    placement: str,
    low: float = HUMIDITY_LOW,
    very_low: float = HUMIDITY_VERY_LOW,
) -> HumidityAssessment:
    """Advisory from an ambient-humidity reading for a humidity-loving indoor plant.

    Returns `not_applicable` for outdoor plants or when no humidity reading is
    provided, and `ok` (silent) when the plant does not prefer humidity — so the
    advisory only ever appears where it is genuinely actionable.
    """
    if placement != "indoor" or humidity_pct is None:
        return HumidityAssessment(NOT_APPLICABLE, humidity_pct, None)
    h = to_float(humidity_pct)
    if h is None:
        return HumidityAssessment(NOT_APPLICABLE, None, None)
    if not (0.0 <= h <= 100.0):
        return HumidityAssessment(NOT_APPLICABLE, None, None)
    if not prefers_humidity:
        return HumidityAssessment(OK, h, None)
    if h < very_low:
        return HumidityAssessment(
            VERY_LOW, h,
            "Air is very dry for a humidity-loving plant — grouping plants, a "
            "pebble tray, or a humidifier would help.",
        )
    if h < low:
        return HumidityAssessment(
            LOW, h,
            "Air is on the dry side for this plant — misting or a pebble tray "
            "may help.",
        )
    return HumidityAssessment(OK, h, None)
