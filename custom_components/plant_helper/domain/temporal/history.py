"""Rolling observation history for one plant. Pure, no I/O, no clock.

Responsibilities: deduplicate near-identical samples, keep a bounded rolling
window, and answer the temporal questions the engine asks (latest valid value,
moisture slope, coverage confidence, watering detection, and how long moisture
has stayed above or below a threshold). Every method takes the caller's ``now``
so the same history replays identically in any environment.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .observation import PlantObservation

# Rolling-window retention and hard cap on stored observations.
RETENTION_HOURS = 48.0
MAX_OBSERVATIONS = 500

# Deduplication: drop a sample only when it barely moved, arrived soon after the
# previous one, and did not change validity. Validity flips and sharp rises are
# always kept so watering and sensor dropouts are never smoothed away.
DEDUP_DELTA = 0.5
DEDUP_WINDOW_MINUTES = 10.0

# Confidence thresholds over the trailing 24 hours.
CONFIDENCE_WINDOW_HOURS = 24.0
HIGH_COVERAGE_HOURS = 18.0
MEDIUM_COVERAGE_HOURS = 8.0
MAX_GAP_RATIO = 0.25

# Watering detection defaults.
WATERING_RISE = 5.0
WATERING_WINDOW_MINUTES = 90.0

# Slope window for trend detection.
SLOPE_WINDOW_HOURS = 6.0


class ObservationHistory:
    """A bounded, deduplicated series of observations for a single plant."""

    def __init__(
        self,
        observations: list[PlantObservation] | None = None,
        *,
        retention_hours: float = RETENTION_HOURS,
        max_observations: int = MAX_OBSERVATIONS,
    ) -> None:
        self._obs: list[PlantObservation] = list(observations or [])
        self._retention = timedelta(hours=retention_hours)
        self._cap = max_observations

    @property
    def observations(self) -> tuple[PlantObservation, ...]:
        return tuple(self._obs)

    def __len__(self) -> int:
        return len(self._obs)

    def append(self, obs: PlantObservation) -> bool:
        """Add an observation unless it is a duplicate. Returns True if stored."""
        prev = self._obs[-1] if self._obs else None
        if prev is not None and self._is_duplicate(prev, obs):
            return False
        self._obs.append(obs)
        self._prune(obs.observed_at)
        return True

    def _is_duplicate(self, prev: PlantObservation, obs: PlantObservation) -> bool:
        if prev.moisture_valid != obs.moisture_valid:
            return False
        gap_minutes = (obs.observed_at - prev.observed_at).total_seconds() / 60.0
        if gap_minutes >= DEDUP_WINDOW_MINUTES:
            return False
        if not (prev.moisture_valid and obs.moisture_valid):
            return True
        delta = abs((obs.moisture or 0.0) - (prev.moisture or 0.0))
        return delta < DEDUP_DELTA

    def _prune(self, now: datetime) -> None:
        cutoff = now - self._retention
        self._obs = [o for o in self._obs if o.observed_at >= cutoff]
        if len(self._obs) > self._cap:
            self._obs = self._obs[-self._cap :]

    def valid(self) -> list[PlantObservation]:
        return [o for o in self._obs if o.moisture_valid and o.moisture is not None]

    def latest_valid(self) -> PlantObservation | None:
        for obs in reversed(self._obs):
            if obs.moisture_valid and obs.moisture is not None:
                return obs
        return None

    def moisture_slope(
        self, now: datetime, *, window_hours: float = SLOPE_WINDOW_HOURS
    ) -> float | None:
        """Least-squares moisture slope in percent per hour, or None."""
        cutoff = now - timedelta(hours=window_hours)
        pts = [(o.observed_at, o.moisture) for o in self.valid() if o.observed_at >= cutoff]
        if len(pts) < 2:
            return None
        origin = pts[0][0]
        xs = [(t - origin).total_seconds() / 3600.0 for t, _ in pts]
        ys = [float(m) for _, m in pts]
        n = len(xs)
        sx = sum(xs)
        sy = sum(ys)
        sxx = sum(x * x for x in xs)
        sxy = sum(x * y for x, y in zip(xs, ys))
        denom = n * sxx - sx * sx
        if denom == 0:
            return None
        return (n * sxy - sx * sy) / denom

    def confidence(self, now: datetime) -> str:
        """'high', 'medium', or 'low' from coverage and gaps over 24 h."""
        cutoff = now - timedelta(hours=CONFIDENCE_WINDOW_HOURS)
        times = sorted(o.observed_at for o in self.valid() if o.observed_at >= cutoff)
        if len(times) < 2:
            return "low"
        coverage = (times[-1] - times[0]).total_seconds() / 3600.0
        gaps = [
            (times[i + 1] - times[i]).total_seconds() / 3600.0
            for i in range(len(times) - 1)
        ]
        gaps.append((now - times[-1]).total_seconds() / 3600.0)
        gap_ratio = max(gaps) / CONFIDENCE_WINDOW_HOURS
        if coverage >= HIGH_COVERAGE_HOURS and gap_ratio < MAX_GAP_RATIO:
            return "high"
        if coverage >= MEDIUM_COVERAGE_HOURS:
            return "medium"
        return "low"

    def detect_watering(
        self,
        now: datetime,
        *,
        rise: float = WATERING_RISE,
        window_minutes: float = WATERING_WINDOW_MINUTES,
    ) -> datetime | None:
        """Time of the most recent probable watering, or None.

        A watering is a rise of at least ``rise`` points from the lowest valid
        reading in the trailing window up to the newest reading. Comparing to
        the window minimum means small reversals never cancel a real rise.
        """
        window = timedelta(minutes=window_minutes)
        recent = [o for o in self.valid() if (now - o.observed_at) <= window]
        if len(recent) < 2:
            return None
        newest = recent[-1]
        base = min(recent[:-1], key=lambda o: o.moisture)
        if base.observed_at < newest.observed_at and (
            newest.moisture - base.moisture
        ) >= rise:
            return newest.observed_at
        return None

    def duration_above(self, threshold: float, now: datetime) -> timedelta | None:
        """How long the newest run of valid readings has stayed > threshold."""
        return self._run_duration(threshold, now, above=True)

    def duration_below(self, threshold: float, now: datetime) -> timedelta | None:
        """How long the newest run of valid readings has stayed < threshold."""
        return self._run_duration(threshold, now, above=False)

    def _run_duration(
        self, threshold: float, now: datetime, *, above: bool
    ) -> timedelta | None:
        valid = self.valid()
        if not valid:
            return None
        latest = valid[-1].moisture
        if above and not latest > threshold:
            return None
        if not above and not latest < threshold:
            return None
        start = valid[-1].observed_at
        for obs in reversed(valid):
            crosses = obs.moisture > threshold if above else obs.moisture < threshold
            if crosses:
                start = obs.observed_at
            else:
                break
        return now - start

    def peak_since(self, moment: datetime | None) -> float | None:
        """Highest valid moisture at or after ``moment`` (or overall if None)."""
        values = [
            o.moisture
            for o in self.valid()
            if moment is None or o.observed_at >= moment
        ]
        return max(values) if values else None
