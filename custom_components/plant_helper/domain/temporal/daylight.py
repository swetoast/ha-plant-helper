"""Daylight classification with the roadmap's fallback chain.

Pure. The chain (roadmap sections 3 and 8) is:

1. Open-Meteo Forecast sunrise and sunset (a fresh snapshot)
2. Cached Forecast ephemeris, valid for up to 48 hours after it was fetched
3. Home Assistant location and Astral calculation (supplied by the caller)
4. Uncertainty hold: ``is_daylight`` is None

An unknown classification must never be treated as nighttime. The Air Quality
collector has no input here, so its failures cannot affect daylight.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Iterable, Mapping

EPHEMERIS_MAX_AGE = timedelta(hours=48)
# How far a known sunrise or sunset may be from ``now`` for the night between
# them to count as known darkness.
_NIGHT_SPAN = timedelta(hours=20)

SOURCE_FORECAST = "forecast"
SOURCE_CACHE = "cache"
SOURCE_ASTRAL = "astral"
SOURCE_UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class DaylightWindow:
    sunrise: datetime
    sunset: datetime


@dataclass(frozen=True, slots=True)
class DaylightState:
    is_daylight: bool | None
    source: str


def parse_daily_windows(daily: Any) -> tuple[DaylightWindow, ...]:
    """Read Open-Meteo daily sunrise/sunset (UTC, requested with timezone=UTC)."""
    if not isinstance(daily, Mapping):
        return ()
    rises = daily.get("sunrise")
    sets = daily.get("sunset")
    if not isinstance(rises, list) or not isinstance(sets, list):
        return ()
    windows: list[DaylightWindow] = []
    for rise, fall in zip(rises, sets):
        sunrise, sunset = _parse_utc(rise), _parse_utc(fall)
        if sunrise is not None and sunset is not None and sunset > sunrise:
            windows.append(DaylightWindow(sunrise, sunset))
    return tuple(sorted(windows, key=lambda w: w.sunrise))


def classify(now: datetime, windows: Iterable[DaylightWindow]) -> bool | None:
    """True inside a window, False in a known night, None when not covered."""
    ordered = sorted(windows, key=lambda w: w.sunrise)
    if not ordered:
        return None
    for window in ordered:
        if window.sunrise <= now < window.sunset:
            return True
    before = [w for w in ordered if w.sunset <= now]
    after = [w for w in ordered if w.sunrise > now]
    if before and now - before[-1].sunset <= _NIGHT_SPAN:
        return False
    if after and after[0].sunrise - now <= _NIGHT_SPAN:
        return False
    return None


def resolve_daylight(
    now: datetime,
    *,
    forecast_windows: Iterable[DaylightWindow] = (),
    forecast_fetched_at: datetime | None = None,
    forecast_stale: bool = False,
    astral: Callable[[datetime], Iterable[DaylightWindow] | None] | None = None,
) -> DaylightState:
    """Classify ``now`` using the first source in the chain that can answer."""
    windows = tuple(forecast_windows)
    fresh_enough = (
        forecast_fetched_at is not None
        and now - forecast_fetched_at <= EPHEMERIS_MAX_AGE
    )
    if windows and fresh_enough:
        verdict = classify(now, windows)
        if verdict is not None:
            return DaylightState(
                verdict, SOURCE_CACHE if forecast_stale else SOURCE_FORECAST
            )
    if astral is not None:
        try:
            astral_windows = tuple(astral(now) or ())
        except Exception:
            astral_windows = ()
        verdict = classify(now, astral_windows)
        if verdict is not None:
            return DaylightState(verdict, SOURCE_ASTRAL)
    return DaylightState(None, SOURCE_UNKNOWN)


def _parse_utc(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed
