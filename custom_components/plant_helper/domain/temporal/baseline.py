"""Learn each plant's own comfortable moisture band from its watering cycles.

Pure and testable. The static profile band is a generic guess; a plant reveals
its real range by how it behaves - the trough it is allowed to reach before it is
watered, and the peak it reaches just after. This module accumulates those
troughs and peaks across watering cycles (surviving the rolling observation
window, which is far shorter than the weeks calibration takes) and, once enough
evidence exists at high confidence, derives the learned (low, high) band.

Persistence of the accumulated samples and the finished baseline is the caller's
job, via the existing PlantHelperStorage learned / active_samples layer. This
module only computes; every constant is a starting value to tune against fixtures.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from statistics import median

from .history import WATERING_RISE, ObservationHistory, same_watering

# Per-cycle metrics kept for the typical-cycle baseline (roadmap Phase 6).
MAX_CYCLE_HISTORY = 10
# Daily-summary learning needs at least this many qualifying days.
LEARNING_MIN_DAYS = 7
MONTH_MIN_DAYS = 5
# Learned band may move this far from the selected care profile, no further.
PROFILE_LOW_BELOW = 10.0
PROFILE_LOW_ABOVE = 15.0
PROFILE_HIGH_BELOW = 15.0
PROFILE_HIGH_ABOVE = 10.0

# Calibration gate.
CALIBRATION_DAYS = 14.0
MIN_CYCLES = 2

# Sanity clamp on a learned band, so a stuck or noisy sensor cannot teach a
# nonsense range. A degenerate band (gap too small) is rejected, not stored.
MIN_LOW = 5.0
MAX_HIGH = 100.0
MIN_BAND_GAP = 10.0


@dataclass(frozen=True, slots=True)
class BaselineSamples:
    troughs: tuple[float, ...] = ()
    peaks: tuple[float, ...] = ()
    cycle_low: float | None = None
    cycle_high: float | None = None
    last_watering: datetime | None = None
    first_seen: datetime | None = None
    last_seen: datetime | None = None
    rises: tuple[float, ...] = ()
    slopes: tuple[float, ...] = ()
    recovery_hours: tuple[float, ...] = ()
    back_in_range_at: datetime | None = None

    def to_dict(self) -> dict:
        return {
            "troughs": list(self.troughs),
            "peaks": list(self.peaks),
            "cycle_low": self.cycle_low,
            "cycle_high": self.cycle_high,
            "last_watering": _iso(self.last_watering),
            "first_seen": _iso(self.first_seen),
            "last_seen": _iso(self.last_seen),
            "rises": list(self.rises),
            "slopes": list(self.slopes),
            "recovery_hours": list(self.recovery_hours),
            "back_in_range_at": _iso(self.back_in_range_at),
        }

    @classmethod
    def from_dict(cls, raw: object) -> "BaselineSamples":
        if not isinstance(raw, dict):
            return cls()
        return cls(
            troughs=tuple(_floats(raw.get("troughs"))),
            peaks=tuple(_floats(raw.get("peaks"))),
            cycle_low=_as_float(raw.get("cycle_low")),
            cycle_high=_as_float(raw.get("cycle_high")),
            last_watering=_parse(raw.get("last_watering")),
            first_seen=_parse(raw.get("first_seen")),
            last_seen=_parse(raw.get("last_seen")),
            rises=tuple(_floats(raw.get("rises"))),
            slopes=tuple(_floats(raw.get("slopes"))),
            recovery_hours=tuple(_floats(raw.get("recovery_hours"))),
            back_in_range_at=_parse(raw.get("back_in_range_at")),
        )


def update_samples(
    samples: BaselineSamples,
    history: ObservationHistory,
    now: datetime,
    *,
    band_high: float | None = None,
    learnable: bool = True,
    watering_rise: float = WATERING_RISE,
) -> BaselineSamples:
    """Fold the latest reading and any completed cycle into the accumulator.

    ``learnable`` is False while the plant is in an abnormal state (waterlogged,
    parched, sensor fault); readings then do not shape the learned range, per
    the roadmap's "do not learn temporary abnormal states as normal".
    """
    latest = history.latest_valid()
    if latest is None:
        return samples
    moisture = float(latest.moisture)
    first_seen = samples.first_seen or now
    cycle_low, cycle_high = samples.cycle_low, samples.cycle_high
    if learnable:
        cycle_low = moisture if cycle_low is None else min(cycle_low, moisture)
        cycle_high = moisture if cycle_high is None else max(cycle_high, moisture)
    troughs, peaks = samples.troughs, samples.peaks
    rises, slopes, recovery = samples.rises, samples.slopes, samples.recovery_hours
    last_watering = samples.last_watering
    back_in_range = samples.back_in_range_at
    if (
        band_high is not None
        and last_watering is not None
        and back_in_range is None
        and now > last_watering
        and moisture <= band_high
    ):
        back_in_range = now

    watering = same_watering(
        history.detect_watering(now, rise=watering_rise), samples.last_watering, history
    )
    if watering is not None and watering != samples.last_watering:
        # A watering closes the cycle that was drying down: its low is a trough,
        # its high the post-water peak. The next cycle starts at the fresh level.
        if cycle_low is not None and cycle_high is not None:
            # The low before this watering is always a genuine trough. The high
            # is a post-watering peak only if the closing cycle itself began at a
            # watering; the span before the first watering ever seen did not.
            if last_watering is not None:
                if troughs:
                    rises = _cap(rises + (max(0.0, cycle_high - troughs[-1]),))
                peaks = _cap(peaks + (cycle_high,))
            troughs = _cap(troughs + (cycle_low,))
            if last_watering is not None and watering > last_watering:
                hours = (watering - last_watering).total_seconds() / 3600.0
                slopes = _cap(slopes + ((cycle_high - cycle_low) / hours,))
                if back_in_range is not None:
                    recovery = _cap(
                        recovery
                        + ((back_in_range - last_watering).total_seconds() / 3600.0,)
                    )
        cycle_low = moisture
        cycle_high = moisture
        last_watering = watering
        back_in_range = None

    return BaselineSamples(
        troughs=troughs,
        peaks=peaks,
        cycle_low=cycle_low,
        cycle_high=cycle_high,
        last_watering=last_watering,
        first_seen=first_seen,
        last_seen=now,
        rises=rises,
        slopes=slopes,
        recovery_hours=recovery,
        back_in_range_at=back_in_range,
    )


def derive_band(
    samples: BaselineSamples,
    confidence: str,
    now: datetime,
    profile_band: tuple[float, float] | None = None,
) -> tuple[float, float] | None:
    """Return the learned (low, high) band once the gate passes, else None."""
    if samples.first_seen is None or samples.last_seen is None:
        return None
    coverage_days = (samples.last_seen - samples.first_seen) / timedelta(days=1)
    if coverage_days < CALIBRATION_DAYS:
        return None
    if len(samples.troughs) < MIN_CYCLES or len(samples.peaks) < MIN_CYCLES:
        return None
    if confidence != "high":
        return None
    low = max(MIN_LOW, float(median(samples.troughs)))
    high = min(MAX_HIGH, float(median(samples.peaks)))
    if profile_band is not None:
        p_low, p_high = profile_band
        low = min(max(low, max(MIN_LOW, p_low - PROFILE_LOW_BELOW)), p_low + PROFILE_LOW_ABOVE)
        high = min(max(high, p_high - PROFILE_HIGH_BELOW), min(MAX_HIGH, p_high + PROFILE_HIGH_ABOVE))
    if high - low < MIN_BAND_GAP:
        return None
    return (low, high)


def cycle_baseline(samples: BaselineSamples) -> dict:
    """Typical watering rise, peak, drying slope and recovery time (medians)."""
    out: dict = {}
    for key, values in (
        ("rise", samples.rises),
        ("peak", samples.peaks),
        ("slope", samples.slopes),
        ("recovery_hours", samples.recovery_hours),
    ):
        if len(values) >= MIN_CYCLES:
            out[key] = float(median(values))
    return out


def daily_baseline(days) -> dict:
    """Normal light, supplemental pattern, temperature and humidity ranges.

    ``days`` are completed DailySummary records. Only judged light days and days
    with real coverage count, so gaps and faults are not learned as normal.
    """
    out: dict = {}
    lights = [d.light for d in days if d.light is not None and d.light.judged]
    if len(lights) >= LEARNING_MIN_DAYS:
        out["light_natural"] = float(median(x.natural_light_exposure for x in lights))
        out["light_effective"] = float(median(x.effective_light_exposure for x in lights))
        with_sessions = [x for x in lights if x.artificial_light_exposure > 0]
        out["supplemental_share"] = len(with_sessions) / len(lights)
        if with_sessions:
            out["light_supplemental"] = float(
                median(x.artificial_light_exposure for x in with_sessions)
            )
    temps = [d for d in days if d.temperature_min is not None and d.temperature_max is not None]
    if len(temps) >= LEARNING_MIN_DAYS:
        out["temperature_low"] = float(median(d.temperature_min for d in temps))
        out["temperature_high"] = float(median(d.temperature_max for d in temps))
    hums = [d for d in days if d.humidity_min is not None and d.humidity_max is not None]
    if len(hums) >= LEARNING_MIN_DAYS:
        out["humidity_low"] = float(median(d.humidity_min for d in hums))
        out["humidity_high"] = float(median(d.humidity_max for d in hums))
    return out


def monthly_baseline(existing: dict | None, days) -> dict:
    """Seasonal variation: per-month typical light and temperature, merged."""
    monthly = dict(existing or {})
    buckets: dict[str, list] = {}
    for d in days:
        buckets.setdefault(d.day[5:7], []).append(d)
    for month, group in buckets.items():
        lights = [x.light.effective_light_exposure for x in group if x.light is not None and x.light.judged]
        temps = [x.temperature_mean for x in group if x.temperature_mean is not None]
        entry = dict(monthly.get(month, {}))
        if len(lights) >= MONTH_MIN_DAYS:
            entry["light"] = float(median(lights))
        if len(temps) >= MONTH_MIN_DAYS:
            entry["temperature"] = float(median(temps))
        if entry:
            monthly[month] = entry
    return monthly


def light_normal(learned, month: int) -> float | None:
    """This plant's normal daily light: the month's own value when learned."""
    if not learned:
        return None
    monthly = learned.get("monthly") or {}
    entry = monthly.get(f"{month:02d}") or {}
    value = entry.get("light", learned.get("light_effective"))
    return float(value) if value is not None else None


def _cap(values: tuple[float, ...]) -> tuple[float, ...]:
    return values[-MAX_CYCLE_HISTORY:]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _parse(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


def _as_float(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _floats(value: object) -> list[float]:
    if not isinstance(value, (list, tuple)):
        return []
    out = []
    for item in value:
        parsed = _as_float(item)
        if parsed is not None:
            out.append(parsed)
    return out
