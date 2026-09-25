"""Temperature exposure interpretation (roadmap Phase 3).

Pure. Conditions: normal, cool, cold, warm, hot, rapid_change, prolonged_cold,
prolonged_heat. A brief excursion changes the current condition (and summary)
but not health; only persistent exposure moves health to watch, and a persistent
extreme (cold or hot band) to stressed. Recovery clears a prolonged condition
once the reading has been back in range for RECOVERY_HOURS.

Bands are placement-relative: an outdoor plant sees cool nights as normal, so
its comfort range is wider than a room's. Every constant is a starting value to
tune against fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .exposure import ExposureReport
from .status import HEALTH_GOOD, HEALTH_STRESSED, HEALTH_WATCH, TOO_COLD, TOO_HOT

# (cool below, cold below, warm above, hot above) in Celsius.
BANDS = {
    "indoor": (18.0, 12.0, 27.0, 32.0),
    "outdoor": (5.0, 0.0, 30.0, 35.0),
}
PROLONGED_CONTINUOUS_HOURS = 8.0
PROLONGED_TOTAL_24H_HOURS = 12.0
RECOVERY_HOURS = 3.0
EXTREME_STATUS_HOURS = 1.0
RAPID_CHANGE_PER_HOUR = 4.0
REPEATED_DAYS = 3


@dataclass(frozen=True, slots=True)
class TemperatureAssessment:
    condition: str | None
    status: str | None
    health: str
    attention: bool
    reason: str | None
    summary: str | None
    since: datetime | None


def classifier(placement: str, learned=None):
    """Band classifier; learned normals widen the mild bands, never the extremes."""
    cool, cold, warm, hot = BANDS.get(placement, BANDS["indoor"])
    learned = learned or {}
    if learned.get("temperature_low") is not None:
        cool = min(cool, max(cold + 1.0, float(learned["temperature_low"]) - 1.0))
    if learned.get("temperature_high") is not None:
        warm = max(warm, min(hot - 1.0, float(learned["temperature_high"]) + 1.0))

    def classify(value: float) -> tuple[str | None, int]:
        if value < cold:
            return "low", 2
        if value < cool:
            return "low", 1
        if value > hot:
            return "high", 2
        if value > warm:
            return "high", 1
        return None, 0

    return classify


def assess_temperature(
    report: ExposureReport, *, repeated_days: int = 0
) -> TemperatureAssessment:
    """Interpret one temperature exposure report.

    ``repeated_days`` is how many of the recent completed days carried
    prolonged exposure (from the daily summaries); it lets a condition that
    recurs every day raise attention even when each day's run is moderate.
    """
    if not report.has_data:
        return TemperatureAssessment(None, None, HEALTH_GOOD, False, None, None, None)

    direction = report.direction
    if direction is None:
        low_total = report.low_hours_24h >= PROLONGED_TOTAL_24H_HOURS
        high_total = report.high_hours_24h >= PROLONGED_TOTAL_24H_HOURS
        recovering = report.in_range_hours < RECOVERY_HOURS and (low_total or high_total)
        if recovering:
            cold = low_total and report.low_hours_24h >= report.high_hours_24h
            return TemperatureAssessment(
                "prolonged_cold" if cold else "prolonged_heat",
                None,
                HEALTH_WATCH,
                False,
                "temperature_recovering",
                "Temperature is back in range after a long "
                + ("cold" if cold else "hot")
                + " spell",
                None,
            )
        if report.rate_per_hour is not None and abs(report.rate_per_hour) >= RAPID_CHANGE_PER_HOUR:
            return TemperatureAssessment(
                "rapid_change", None, HEALTH_GOOD, False, "rapid_temperature_change",
                "Temperature is changing quickly", None,
            )
        return TemperatureAssessment("normal", None, HEALTH_GOOD, False, None, None, None)

    low = direction == "low"
    total = report.low_hours_24h if low else report.high_hours_24h
    prolonged = (
        report.continuous_hours >= PROLONGED_CONTINUOUS_HOURS
        or total >= PROLONGED_TOTAL_24H_HOURS
    )
    extreme = report.severity >= 2
    status_code = TOO_COLD if low else TOO_HOT
    if prolonged:
        condition = "prolonged_cold" if low else "prolonged_heat"
        health = HEALTH_STRESSED if extreme else HEALTH_WATCH
        attention = extreme or repeated_days >= REPEATED_DAYS
        return TemperatureAssessment(
            condition,
            status_code,
            health,
            attention,
            "prolonged_temperature_stress",
            ("It has been too cold for this plant for a long time" if low
             else "It has been too hot for this plant for a long time"),
            report.run_since,
        )
    if extreme and report.continuous_hours >= EXTREME_STATUS_HOURS:
        return TemperatureAssessment(
            "cold" if low else "hot",
            status_code,
            HEALTH_GOOD,
            False,
            "cold_exposure" if low else "heat_exposure",
            "It is currently too cold for this plant" if low
            else "It is currently too hot for this plant",
            report.run_since,
        )
    if report.rate_per_hour is not None and abs(report.rate_per_hour) >= RAPID_CHANGE_PER_HOUR:
        return TemperatureAssessment(
            "rapid_change", None, HEALTH_GOOD, False, "rapid_temperature_change",
            "Temperature is changing quickly", None,
        )
    mild = ("cold" if extreme else "cool") if low else ("hot" if extreme else "warm")
    return TemperatureAssessment(
        mild, None, HEALTH_GOOD, False, None,
        "It is " + mild + " around the plant at the moment", report.run_since,
    )
