"""Rolling observation history for one plant. Pure, no I/O, no clock.

Responsibilities: deduplicate samples without losing analytical value, keep a
bounded rolling window, and answer the temporal questions the engines ask
(latest valid value, moisture slope, coverage confidence, watering detection,
run durations, point series and time-weighted segments). Every method takes the
caller's ``now`` so the same history replays identically in any environment.

Deduplication follows roadmap Phase 1: a sample is dropped only when nothing
material changed on ANY signal, or when it arrives too soon after the previous
one to add value. Validity flips, daylight transitions and sharp moisture rises
are always kept, and a heartbeat sample is kept every HEARTBEAT_MINUTES so a
steady plant still accumulates coverage.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from .observation import PlantObservation

# Rolling-window retention and hard cap on stored observations.
RETENTION_HOURS = 48.0
MAX_OBSERVATIONS = 700

# Deduplication tuning.
MIN_SPACING_MINUTES = 5.0
HEARTBEAT_MINUTES = 30.0
SHARP_RISE = 2.5
MOISTURE_DELTA = 0.5
TEMPERATURE_DELTA = 0.3
HUMIDITY_DELTA = 2.0
LIGHT_DELTA_LUX = 10.0
LIGHT_DELTA_RATIO = 0.15

# Confidence thresholds over the trailing 24 hours.
CONFIDENCE_WINDOW_HOURS = 24.0
HIGH_COVERAGE_HOURS = 18.0
MEDIUM_COVERAGE_HOURS = 8.0
MAX_GAP_RATIO = 0.25

# Watering detection defaults. Live recorder data showed probe noise and the
# day/night swing reaching 5-6 points within 90 minutes, and slow soaks that
# rise under 5 points in 90 minutes but 18 over a few hours. So the window is
# six hours and the rise threshold scales with each sensor's own daily swing
# (moisture.watering_rise_threshold); this default applies until that is known.
WATERING_RISE = 8.0
WATERING_WINDOW_MINUTES = 360.0

# Slope window for trend detection.
SLOPE_WINDOW_HOURS = 6.0

_VALIDITY = (
    "moisture_valid",
    "soil_temperature_valid",
    "light_valid",
    "humidity_valid",
)


def _changed(prev: PlantObservation, obs: PlantObservation) -> bool:
    """True when any valid signal moved by a material amount."""
    def moved(attr: str, valid: str, delta: float) -> bool:
        if not getattr(obs, valid):
            return False
        return abs(float(getattr(obs, attr)) - float(getattr(prev, attr))) >= delta

    if moved("moisture", "moisture_valid", MOISTURE_DELTA):
        return True
    if moved("soil_temperature", "soil_temperature_valid", TEMPERATURE_DELTA):
        return True
    if moved("humidity", "humidity_valid", HUMIDITY_DELTA):
        return True
    if obs.light_valid:
        a, b = float(prev.light), float(obs.light)
        if abs(a - b) >= max(LIGHT_DELTA_LUX, LIGHT_DELTA_RATIO * max(a, b)):
            return True
    return False


# A later rise only counts as a new watering once the soil has dried back at
# least this far from its peak since the previous one; a soak that is still
# climbing (bottom watering can take most of a day) is the same watering.
REFILL_DRYDOWN = 3.0


def same_watering(
    detected: datetime | None,
    previous: datetime | None,
    history: "ObservationHistory | None" = None,
) -> datetime | None:
    """Collapse a watering episode into one event.

    During a slow soak the lowest reading in the detection window keeps rising
    as the window slides, so the detected crossing moves forward with every
    reading. A detection belongs to the previously recorded watering when it
    falls within the detection window of it, or when the soil has not dried back
    by REFILL_DRYDOWN since; only a genuinely separate watering is a new event.
    """
    if detected is None:
        return previous
    if previous is None or detected <= previous:
        return previous or detected
    if detected - previous < timedelta(minutes=WATERING_WINDOW_MINUTES):
        return previous
    if history is not None:
        peak = None
        for t, value in history.points("moisture", "moisture_valid", previous):
            if t > detected:
                break
            peak = value if peak is None else max(peak, value)
            if peak - value >= REFILL_DRYDOWN:
                return detected
        return previous
    return detected


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
        for valid in _VALIDITY:
            if getattr(prev, valid) != getattr(obs, valid):
                return False
        if prev.is_daylight != obs.is_daylight:
            return False
        if (
            prev.moisture_valid
            and obs.moisture_valid
            and float(obs.moisture) - float(prev.moisture) >= SHARP_RISE
        ):
            return False
        gap_minutes = (obs.observed_at - prev.observed_at).total_seconds() / 60.0
        if gap_minutes < MIN_SPACING_MINUTES:
            return True
        if gap_minutes >= HEARTBEAT_MINUTES:
            return False
        return not _changed(prev, obs)

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
        self,
        now: datetime,
        *,
        window_hours: float = SLOPE_WINDOW_HOURS,
        since: datetime | None = None,
        min_span_hours: float = 0.0,
    ) -> float | None:
        """Least-squares moisture slope in percent per hour, or None.

        ``since`` starts the window no earlier than that moment (for example the
        last watering, so the watering spike does not mask the decline after
        it). ``min_span_hours`` requires the points to cover at least that long,
        which keeps whole-percent sensors from producing a slope out of noise.
        """
        cutoff = now - timedelta(hours=window_hours)
        if since is not None and since > cutoff:
            cutoff = since
        pts = [(o.observed_at, o.moisture) for o in self.valid() if o.observed_at >= cutoff]
        if len(pts) < 2:
            return None
        if (pts[-1][0] - pts[0][0]).total_seconds() / 3600.0 < min_span_hours:
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
        if base.observed_at >= newest.observed_at or (
            newest.moisture - base.moisture
        ) < rise:
            return None
        # Report the first reading that cleared the rise, not the newest one.
        # The newest reading moves forward on every update, which would re-stamp
        # one watering as many for the whole window and close a fresh learning
        # cycle on each reading. The first crossing is stable across updates.
        crossing = next(
            o
            for o in recent
            if o.observed_at > base.observed_at and (o.moisture - base.moisture) >= rise
        )
        return crossing.observed_at

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

    def rolling_mean(
        self,
        now: datetime,
        attr: str,
        valid_attr: str,
        *,
        window_hours: float,
        min_samples: int = 3,
    ) -> float | None:
        """Mean of a numeric field (light, humidity) over its valid readings.

        Generic over the observation field so light and humidity share one code
        path. Returns None when too few valid samples fall in the window, so a
        sparse signal never drives a verdict.
        """
        cutoff = now - timedelta(hours=window_hours)
        values = [
            float(getattr(obs, attr))
            for obs in self._obs
            if obs.observed_at >= cutoff
            and getattr(obs, valid_attr)
            and getattr(obs, attr) is not None
        ]
        if len(values) < min_samples:
            return None
        return sum(values) / len(values)

    def points(
        self, attr: str, valid_attr: str, since: datetime | None = None
    ) -> list[tuple[datetime, float]]:
        """Valid (time, value) pairs for one signal, oldest first."""
        return [
            (obs.observed_at, float(getattr(obs, attr)))
            for obs in self._obs
            if getattr(obs, valid_attr)
            and getattr(obs, attr) is not None
            and (since is None or obs.observed_at >= since)
        ]

    def segments(
        self,
        attr: str,
        valid_attr: str,
        start: datetime,
        end: datetime,
        *,
        max_hold_hours: float,
    ) -> list[tuple[datetime, datetime, float | None, bool | None]]:
        """Time-weighted pieces (t0, t1, value, is_daylight) covering [start, end].

        Each observation holds its value until the next observation, for at most
        ``max_hold_hours``; beyond that the time is uncovered (not returned).
        An invalid reading yields a piece with value None, so callers can count
        it as a gap rather than a zero.
        """
        hold = timedelta(hours=max_hold_hours)
        pieces: list[tuple[datetime, datetime, float | None, bool | None]] = []
        obs = self._obs
        for index, current in enumerate(obs):
            t0 = current.observed_at
            t1 = obs[index + 1].observed_at if index + 1 < len(obs) else end
            t1 = min(t1, t0 + hold)
            a, b = max(t0, start), min(t1, end)
            if b <= a:
                continue
            valid = getattr(current, valid_attr) and getattr(current, attr) is not None
            value = float(getattr(current, attr)) if valid else None
            pieces.append((a, b, value, current.is_daylight))
        return pieces
