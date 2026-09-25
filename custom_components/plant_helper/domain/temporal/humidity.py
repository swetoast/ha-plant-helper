"""Air humidity exposure interpretation (roadmap Phase 3).

Pure. Conditions: normal, dry_air, humid_air, prolonged_dry_air,
prolonged_humidity. Humidity never produces its own status or attention; it
shapes summaries and, when persistent, moves health to watch. Recovery clears a
prolonged condition after RECOVERY_HOURS back in range.
"""
from __future__ import annotations

from dataclasses import dataclass

from .exposure import ExposureReport
from .status import HEALTH_GOOD, HEALTH_WATCH

# (dry below, very dry below, humid above, very humid above) in percent.
BANDS = {
    # Live data: healthy indoor plants routinely sit at 65-80 %; excess
    # humidity only becomes a concern around 90 %.
    "indoor": (30.0, 20.0, 80.0, 90.0),
    "outdoor": (25.0, 15.0, 95.0, 99.0),
}
PROLONGED_CONTINUOUS_HOURS = 12.0
PROLONGED_TOTAL_24H_HOURS = 16.0
RECOVERY_HOURS = 3.0


@dataclass(frozen=True, slots=True)
class HumidityAssessment:
    condition: str | None
    health: str
    summary: str | None

    @property
    def context(self) -> str | None:
        """Coarse low / adequate / high label for the status attributes."""
        if self.condition is None:
            return None
        if self.condition in ("dry_air", "prolonged_dry_air"):
            return "low"
        if self.condition in ("humid_air", "prolonged_humidity"):
            return "high"
        return "adequate"


def classifier(placement: str, learned=None):
    """Band classifier; learned normals widen the mild bands, never the extremes."""
    dry, very_dry, humid, very_humid = BANDS.get(placement, BANDS["indoor"])
    learned = learned or {}
    if learned.get("humidity_low") is not None:
        dry = min(dry, max(very_dry + 1.0, float(learned["humidity_low"]) - 2.0))
    if learned.get("humidity_high") is not None:
        humid = max(humid, min(very_humid - 1.0, float(learned["humidity_high"]) + 2.0))

    def classify(value: float) -> tuple[str | None, int]:
        if value < very_dry:
            return "low", 2
        if value < dry:
            return "low", 1
        if value > very_humid:
            return "high", 2
        if value > humid:
            return "high", 1
        return None, 0

    return classify


def assess_humidity(report: ExposureReport) -> HumidityAssessment:
    if not report.has_data:
        return HumidityAssessment(None, HEALTH_GOOD, None)
    if report.direction is None:
        dry_total = report.low_hours_24h >= PROLONGED_TOTAL_24H_HOURS
        humid_total = report.high_hours_24h >= PROLONGED_TOTAL_24H_HOURS
        if report.in_range_hours < RECOVERY_HOURS and (dry_total or humid_total):
            dry = dry_total and report.low_hours_24h >= report.high_hours_24h
            return HumidityAssessment(
                "prolonged_dry_air" if dry else "prolonged_humidity",
                HEALTH_WATCH,
                "Air humidity is recovering after a long "
                + ("dry" if dry else "humid") + " spell",
            )
        return HumidityAssessment("normal", HEALTH_GOOD, None)
    dry = report.direction == "low"
    total = report.low_hours_24h if dry else report.high_hours_24h
    if (
        report.continuous_hours >= PROLONGED_CONTINUOUS_HOURS
        or total >= PROLONGED_TOTAL_24H_HOURS
    ):
        return HumidityAssessment(
            "prolonged_dry_air" if dry else "prolonged_humidity",
            HEALTH_WATCH,
            "The air has been very dry for a long time" if dry
            else "The air has been very humid for a long time",
        )
    return HumidityAssessment(
        "dry_air" if dry else "humid_air",
        HEALTH_GOOD,
        "The air is dry at the moment" if dry else "The air is humid at the moment",
    )
