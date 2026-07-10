"""Tier-1 runtime sample store: short-horizon raw rolling buffers.

Generalises the 3.3.0 sample-persistence pattern to arbitrary keyed signals
(per-plant moisture/soil_temp/lux and shared global par/outdoor_lux/elevation).
Holds raw (timestamp, value) pairs for a few days — enough for the engine's 24h
windows, stress timers, and day-close reduction. Long-horizon trends (30-day
dormancy slopes, weekly light) use the Tier-2 daily-aggregate history instead, so
this buffer never has to hold weeks of high-resolution samples.

Pure buffer operations are unit-tested; `SampleStore` is the thin Home Assistant
wrapper (Store + debounced save).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .engine.validation import RawReading
from .engine.util import parse_iso

RETENTION = timedelta(days=3)
MAX_PER_SERIES = 800


def empty_data() -> dict[str, Any]:
    return {"series": {}}


def append_reading(
    data: dict[str, Any],
    key: str,
    ts: datetime,
    value: float | None,
    now: datetime,
    *,
    retention: timedelta = RETENTION,
    max_per_series: int = MAX_PER_SERIES,
    dedupe: bool = True,
) -> None:
    """Append one reading to a keyed series and prune it.

    `dedupe` skips a reading whose timestamp matches the last stored one (useful
    for lagged sources like STRÅNG that repeat the same selected hour until new
    data publishes).
    """
    series = data.setdefault("series", {}).setdefault(key, [])
    iso = ts.isoformat()
    if dedupe and series and series[-1][0] == iso:
        return
    series.append([iso, value])
    prune_series(series, now, retention=retention, max_per_series=max_per_series)


def prune_series(
    series: list[list[Any]],
    now: datetime,
    *,
    retention: timedelta = RETENTION,
    max_per_series: int = MAX_PER_SERIES,
) -> None:
    """Drop readings older than retention and cap the count (in place)."""
    cutoff = now - retention
    kept = [r for r in series if (parse_iso(r[0]) or cutoff) >= cutoff]
    if len(kept) > max_per_series:
        kept = kept[-max_per_series:]
    series[:] = kept


def raw_readings(data: dict[str, Any], key: str) -> list[RawReading]:
    """Reconstruct a series as RawReading objects for the engine/validation."""
    out: list[RawReading] = []
    for row in data.get("series", {}).get(key, []):
        ts = parse_iso(row[0])
        if ts is None:
            continue
        out.append(RawReading(ts, row[1]))
    return out


def latest(data: dict[str, Any], key: str) -> float | None:
    series = data.get("series", {}).get(key, [])
    return series[-1][1] if series else None


def clear_key_prefix(data: dict[str, Any], prefix: str) -> None:
    series = data.get("series", {})
    for k in [k for k in series if k.startswith(prefix)]:
        series.pop(k, None)


class SampleStore:
    """Thin Home Assistant wrapper around the pure buffer operations."""

    def __init__(self, hass: Any, key: str = "plant_helper.samples", version: int = 1) -> None:
        from homeassistant.helpers.storage import Store

        self._store = Store(hass, version, key)
        self._data: dict[str, Any] = empty_data()
        self._loaded = False

    async def async_load(self) -> dict[str, Any]:
        if self._loaded:
            return self._data
        self._loaded = True
        try:
            raw = await self._store.async_load()
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception("Failed to load sample store")
            raw = None
        self._data = raw if isinstance(raw, dict) and "series" in raw else empty_data()
        return self._data

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    def schedule_save(self) -> None:
        if not self._loaded:
            return
        self._store.async_delay_save(lambda: self._data, 30.0)

    async def async_save(self) -> None:
        if not self._loaded:
            return
        try:
            await self._store.async_save(self._data)
        except Exception:  # noqa: BLE001
            import logging

            logging.getLogger(__name__).exception("Failed to save sample store")
