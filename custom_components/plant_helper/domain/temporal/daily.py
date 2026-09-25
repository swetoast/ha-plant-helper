"""Per-local-day summaries and the 30-day ledger (roadmap Phase 1).

Pure. The rolling observation window only spans 48 hours; multi-day judgement
(light streaks, repeated temperature stress, stuck sensors, dormancy, learned
baselines) reads these compact daily records instead. Today and yesterday are
recomputed from the rolling history on every update, which is idempotent and
restart-safe; older days are frozen once they leave the window, and the ledger
keeps LEDGER_DAYS of them.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Any, Callable, Mapping

from . import humidity as humidity_mod
from . import temperature as temperature_mod
from .baseline import light_normal
from .history import ObservationHistory
from .light import DailyLightExposure, day_bounds, daily_light, low_light_threshold

LEDGER_DAYS = 30
MAX_HOLD_HOURS = 2.0


@dataclass(frozen=True, slots=True)
class DailySummary:
    day: str
    moisture_min: float | None
    moisture_max: float | None
    moisture_mean: float | None
    moisture_coverage_hours: float
    temperature_min: float | None
    temperature_max: float | None
    temperature_mean: float | None
    temperature_low_hours: float
    temperature_high_hours: float
    humidity_min: float | None
    humidity_max: float | None
    humidity_mean: float | None
    humidity_low_hours: float
    humidity_high_hours: float
    light: DailyLightExposure | None

    def to_dict(self) -> dict[str, Any]:
        out = {
            field: getattr(self, field)
            for field in self.__dataclass_fields__
            if field != "light"
        }
        out["light"] = _light_to_dict(self.light) if self.light else None
        return out

    @classmethod
    def from_dict(cls, raw: Mapping[str, Any]) -> "DailySummary | None":
        try:
            date.fromisoformat(str(raw["day"]))
            values = {
                field: raw.get(field)
                for field in cls.__dataclass_fields__
                if field != "light"
            }
            for field, value in values.items():
                if field == "day":
                    continue
                if value is not None:
                    values[field] = float(value)
                elif field.endswith("_hours"):
                    values[field] = 0.0
            values["day"] = str(raw["day"])
            light_raw = raw.get("light")
            values["light"] = _light_from_dict(light_raw) if light_raw else None
            return cls(**values)
        except (KeyError, TypeError, ValueError):
            return None


def summarize_day(
    history: ObservationHistory,
    day: date,
    tz: tzinfo,
    now: datetime,
    *,
    placement: str,
    mean_outdoor_radiation: float | None = None,
    learned: Mapping[str, Any] | None = None,
) -> DailySummary | None:
    d0, d1 = day_bounds(day, tz)
    end = min(d1, now)
    if end <= d0:
        return None
    moisture = _stats(history, "moisture", "moisture_valid", d0, end, None)
    temperature = _stats(
        history, "soil_temperature", "soil_temperature_valid", d0, end,
        temperature_mod.classifier(placement, learned),
    )
    humidity = _stats(
        history, "humidity", "humidity_valid", d0, end,
        humidity_mod.classifier(placement, learned),
    )
    light = daily_light(
        history, day, tz, now,
        mean_outdoor_radiation=mean_outdoor_radiation,
        low_threshold=low_light_threshold(light_normal(learned, day.month)),
    )
    if moisture[4] <= 0 and temperature[4] <= 0 and humidity[4] <= 0 and light is None:
        return None
    return DailySummary(
        day=day.isoformat(),
        moisture_min=moisture[0],
        moisture_max=moisture[1],
        moisture_mean=moisture[2],
        moisture_coverage_hours=moisture[4],
        temperature_min=temperature[0],
        temperature_max=temperature[1],
        temperature_mean=temperature[2],
        temperature_low_hours=temperature[3][0],
        temperature_high_hours=temperature[3][1],
        humidity_min=humidity[0],
        humidity_max=humidity[1],
        humidity_mean=humidity[2],
        humidity_low_hours=humidity[3][0],
        humidity_high_hours=humidity[3][1],
        light=light,
    )


def update_ledger(
    ledger: Mapping[str, DailySummary],
    history: ObservationHistory,
    now: datetime,
    tz: tzinfo,
    *,
    placement: str,
    radiation_for_day: Callable[[date], float | None] | None = None,
    learned: Mapping[str, Any] | None = None,
) -> dict[str, DailySummary]:
    """Recompute today and yesterday from history; keep LEDGER_DAYS of days."""
    today = now.astimezone(tz).date()
    updated = dict(ledger)
    for day in (today - timedelta(days=1), today):
        radiation = radiation_for_day(day) if radiation_for_day else None
        previous = updated.get(day.isoformat())
        if radiation is None and previous is not None and previous.light is not None:
            # The forecast's past window rolls forward; keep the value already seen.
            radiation = previous.light.mean_outdoor_radiation
        summary = summarize_day(
            history, day, tz, now,
            placement=placement, mean_outdoor_radiation=radiation, learned=learned,
        )
        if summary is not None:
            updated[summary.day] = summary
    oldest = (today - timedelta(days=LEDGER_DAYS)).isoformat()
    return {key: value for key, value in updated.items() if key >= oldest}


def completed_days(
    ledger: Mapping[str, DailySummary], now: datetime, tz: tzinfo
) -> list[DailySummary]:
    """Days before today, oldest first."""
    today = now.astimezone(tz).date().isoformat()
    return [ledger[key] for key in sorted(ledger) if key < today]


def _stats(history, attr, valid_attr, start, end, classify):
    """(min, max, time-weighted mean, (low_hours, high_hours), covered_hours)."""
    pieces = history.segments(attr, valid_attr, start, end, max_hold_hours=MAX_HOLD_HOURS)
    covered = weighted = low_h = high_h = 0.0
    lo = hi = None
    for a, b, value, _daylight in pieces:
        if value is None:
            continue
        hours = (b - a).total_seconds() / 3600.0
        covered += hours
        weighted += value * hours
        lo = value if lo is None else min(lo, value)
        hi = value if hi is None else max(hi, value)
        if classify is not None:
            direction, _severity = classify(value)
            if direction == "low":
                low_h += hours
            elif direction == "high":
                high_h += hours
    mean = weighted / covered if covered > 0 else None
    return lo, hi, mean, (low_h, high_h), covered


def _light_to_dict(light: DailyLightExposure) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for field in light.__dataclass_fields__:
        value = getattr(light, field)
        out[field] = value.isoformat() if isinstance(value, datetime) else value
    return out


def _light_from_dict(raw: Mapping[str, Any]) -> DailyLightExposure | None:
    try:
        values = dict(raw)
        for field in ("daylight_start", "daylight_end"):
            value = values.get(field)
            values[field] = datetime.fromisoformat(value) if value else None
        return DailyLightExposure(**{f: values.get(f) for f in DailyLightExposure.__dataclass_fields__})
    except (TypeError, ValueError):
        return None
