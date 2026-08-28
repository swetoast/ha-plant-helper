"""Sensor and API sanity checks (design.md section 6).

Turns raw readings into `Sample`s carrying a `valid` flag, which the
accumulator already honours (invalid samples become holes, never extrapolated
across). Detects: missing values, out-of-range values, single-reading spikes
(glitches), flatlined/stuck sensors, and — separately, for the live value —
staleness and critical battery.

Design choices worth stating:
  * Spike vs step. Moisture *steps* up on watering and must be preserved for
    watering detection, so we only invalidate a reading that jumps away from
    the previous value AND immediately reverts (a lone glitch), never a
    sustained step.
  * Flatline is opt-in per quantity and skips readings sitting at a physical
    extreme (e.g. lux = 0 overnight is legitimately flat, not stuck).
  * Battery critical is a *hard* care-halt at the plant level, not just a
    per-sample flag — low voltage causes sensor drift, so care logic pauses
    rather than acting on drifting numbers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Sequence

from .accumulator import Sample
from .util import to_float


@dataclass(frozen=True, slots=True)
class ValidationSpec:
    """Per-quantity sanity bounds."""

    lo: float
    hi: float
    # Absolute jump between consecutive readings above which a *reverting*
    # reading is treated as a glitch. None disables spike detection.
    max_jump: float | None = None
    # A run of near-identical readings persisting longer than this is a stuck
    # sensor. None disables flatline detection (e.g. lux, which holds at 0).
    flatline_after: timedelta | None = None
    flatline_epsilon: float = 1e-6
    # The live value is stale if the newest reading is older than this.
    stale_after: timedelta | None = None


# Default physical specs. Tunable per install later via options.
MOISTURE_SPEC = ValidationSpec(
    lo=0.0, hi=100.0, max_jump=40.0,
    flatline_after=timedelta(hours=12), stale_after=timedelta(hours=2),
)
SOIL_TEMP_SPEC = ValidationSpec(
    lo=-20.0, hi=60.0, max_jump=8.0,
    flatline_after=timedelta(hours=24), stale_after=timedelta(hours=2),
)
LUX_SPEC = ValidationSpec(
    lo=0.0, hi=200_000.0, max_jump=None,
    flatline_after=None, stale_after=timedelta(hours=2),
)
PAR_SPEC = ValidationSpec(
    lo=0.0, hi=2_000.0, max_jump=None,
    flatline_after=None, stale_after=timedelta(hours=3),
)
BATTERY_SPEC = ValidationSpec(lo=0.0, hi=100.0)

CRITICAL_BATTERY_PCT = 15.0

# Categorical battery states (e.g. Xiaomi/BLE soil sensors report high/middle/low
# instead of a percentage). Anything in the critical set halts care; anything in
# the ok set is fine; anything else is treated as unknown (not a false halt).
_BATTERY_CRITICAL_WORDS = {"low", "empty", "critical", "depleted", "very_low", "verylow"}
_BATTERY_OK_WORDS = {"high", "middle", "medium", "normal", "full", "ok", "good"}


@dataclass(frozen=True, slots=True)
class RawReading:
    ts: datetime
    value: float | None


def _in_range(value: float | None, spec: ValidationSpec) -> bool:
    return value is not None and spec.lo <= value <= spec.hi


def _mark_spikes(samples: list[Sample], max_jump: float) -> list[Sample]:
    """Invalidate lone reverting glitches; preserve sustained steps."""
    if len(samples) < 3:
        return samples
    out = list(samples)
    for i in range(1, len(out) - 1):
        prev, cur, nxt = out[i - 1], out[i], out[i + 1]
        if not (prev.usable and cur.usable and nxt.usable):
            continue
        up = cur.value - prev.value
        down = nxt.value - cur.value
        # Big move away then a big move back (opposite sign) = glitch.
        if abs(up) > max_jump and abs(down) > max_jump and (up > 0) != (down > 0):
            out[i] = Sample(cur.ts, cur.value, valid=False)
    return out


def _mark_flatline(samples: list[Sample], spec: ValidationSpec) -> list[Sample]:
    """Invalidate runs of identical values that persist too long."""
    if spec.flatline_after is None:
        return samples
    out = list(samples)
    n = len(out)
    i = 0
    while i < n:
        if not out[i].usable:
            i += 1
            continue
        j = i + 1
        while (
            j < n
            and out[j].usable
            and abs(out[j].value - out[i].value) <= spec.flatline_epsilon
        ):
            j += 1
        run = out[i:j]
        duration = run[-1].ts - run[0].ts
        at_extreme = (
            abs(run[0].value - spec.lo) <= spec.flatline_epsilon
            or abs(run[0].value - spec.hi) <= spec.flatline_epsilon
        )
        if duration > spec.flatline_after and not at_extreme:
            for k in range(i, j):
                out[k] = Sample(out[k].ts, out[k].value, valid=False)
        i = j
    return out


def validate_series(
    readings: Sequence[RawReading],
    spec: ValidationSpec,
) -> list[Sample]:
    """Validate a historical series into gap-aware Samples.

    Applies range, then spike, then flatline checks. Staleness is intentionally
    NOT applied here — old timestamps are fine as historical data points; it is
    only the *current* live value whose age matters (see `current_reading_stale`).
    """
    ordered = sorted(readings, key=lambda r: r.ts)
    samples = [
        Sample(r.ts, r.value, valid=_in_range(r.value, spec)) for r in ordered
    ]
    if spec.max_jump is not None:
        samples = _mark_spikes(samples, spec.max_jump)
    samples = _mark_flatline(samples, spec)
    return samples


def current_reading_stale(
    latest_ts: datetime | None,
    now: datetime,
    spec: ValidationSpec,
) -> bool:
    """True if the newest reading is too old to trust as the live value."""
    if latest_ts is None or spec.stale_after is None:
        return True
    return (now - latest_ts) > spec.stale_after


@dataclass(frozen=True, slots=True)
class BatteryStatus:
    percent: float | None
    valid: bool
    critical: bool
    level: str | None = None       # categorical level when not numeric


def battery_status(
    value: float | int | str | None,
    *,
    critical_pct: float = CRITICAL_BATTERY_PCT,
) -> BatteryStatus:
    """Battery reading -> (valid, critical), for numeric OR categorical batteries.

    Accepts a percentage (0-100, critical at/below `critical_pct`) or a word like
    high/middle/low. An unrecognised value is treated as unknown — valid=False,
    critical=False — so a battery we can't read never falsely halts care.
    """
    if value is None:
        return BatteryStatus(None, False, False, None)

    numeric_value = value
    if isinstance(value, str):
        numeric_value = value.strip()
        if numeric_value.endswith("%"):
            numeric_value = numeric_value[:-1].strip()
    numeric = to_float(numeric_value)
    if numeric is not None:
        valid = BATTERY_SPEC.lo <= numeric <= BATTERY_SPEC.hi
        critical = valid and numeric <= critical_pct
        return BatteryStatus(numeric, valid, bool(critical), None)

    level = str(value).strip().lower()
    if level in _BATTERY_CRITICAL_WORDS:
        return BatteryStatus(None, True, True, level)
    if level in _BATTERY_OK_WORDS:
        return BatteryStatus(None, True, False, level)
    return BatteryStatus(None, False, False, level)


@dataclass(frozen=True, slots=True)
class CareGate:
    """Plant-level go/no-go for running care logic this cycle."""

    care_ok: bool
    reason: str


def care_gate(
    *,
    battery: BatteryStatus | None,
    have_any_valid_sensor: bool,
) -> CareGate:
    """Decide whether care logic may run, or must describe a fault instead.

    Care halts on critical battery (drifting readings) or when no linked sensor
    is currently usable. In those cases the engine reports the sensor condition
    directly rather than emitting a false plant status (design.md section 6).
    """
    if battery is not None and battery.critical:
        return CareGate(False, "battery_critical")
    if not have_any_valid_sensor:
        return CareGate(False, "no_valid_sensors")
    return CareGate(True, "ok")
