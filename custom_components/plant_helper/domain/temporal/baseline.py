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

from .history import ObservationHistory

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

    def to_dict(self) -> dict:
        return {
            "troughs": list(self.troughs),
            "peaks": list(self.peaks),
            "cycle_low": self.cycle_low,
            "cycle_high": self.cycle_high,
            "last_watering": _iso(self.last_watering),
            "first_seen": _iso(self.first_seen),
            "last_seen": _iso(self.last_seen),
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
        )


def update_samples(
    samples: BaselineSamples, history: ObservationHistory, now: datetime
) -> BaselineSamples:
    """Fold the latest reading and any completed cycle into the accumulator."""
    latest = history.latest_valid()
    if latest is None:
        return samples
    moisture = float(latest.moisture)
    first_seen = samples.first_seen or now
    cycle_low = moisture if samples.cycle_low is None else min(samples.cycle_low, moisture)
    cycle_high = moisture if samples.cycle_high is None else max(samples.cycle_high, moisture)
    troughs = samples.troughs
    peaks = samples.peaks
    last_watering = samples.last_watering

    watering = history.detect_watering(now)
    if watering is not None and watering != samples.last_watering:
        # A watering closes the cycle that was drying down: its low is a trough,
        # its high the post-water peak. The next cycle starts at the fresh level.
        troughs = troughs + (cycle_low,)
        peaks = peaks + (cycle_high,)
        cycle_low = moisture
        cycle_high = moisture
        last_watering = watering

    return BaselineSamples(
        troughs=troughs,
        peaks=peaks,
        cycle_low=cycle_low,
        cycle_high=cycle_high,
        last_watering=last_watering,
        first_seen=first_seen,
        last_seen=now,
    )


def derive_band(
    samples: BaselineSamples, confidence: str, now: datetime
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
    if high - low < MIN_BAND_GAP:
        return None
    return (low, high)


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
