"""Learned-baseline maths and the 14-day calibration synthesis.

Everything here is pure: it consumes already-validated daily records and
produces learned constants (or an honest "not yet" verdict). Day-by-day
collection and persistence live in the engine/storage layer; this module only
decides what can be *trusted* from what has been collected.

Shortcomings from the design review addressed here:
  * Partial calibration            -> per-metric minimum-valid-day gates;
                                      synthesis reports what is missing instead
                                      of locking confident-but-wrong constants.
  * M_max drift after calibration  -> `nudge_peak` slow EWMA correction.
  * DLI robust median / short list -> `accumulator.robust_median`.
  * K_window dawn/dusk blow-up     -> outdoor-lux floor before ratioing.
  * K_window seasonality           -> ratios bucketed by sun-elevation band.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from statistics import mean
from typing import Iterable, Sequence

from .accumulator import Sample, rolling_max_average, robust_median

# --- plant profiles -------------------------------------------------------

PROFILE_DRY_TOLERANT = "dry_tolerant"
PROFILE_BALANCED = "balanced"
PROFILE_MOISTURE_LOVING = "moisture_loving"
PROFILE_CUSTOM = "custom"

# M_dry = multiplier * M_max  (design.md appendix section 1).
DRY_MULTIPLIER: dict[str, float] = {
    PROFILE_DRY_TOLERANT: 0.25,
    PROFILE_BALANCED: 0.50,
    PROFILE_MOISTURE_LOVING: 0.70,
}
DEFAULT_DRY_MULTIPLIER = DRY_MULTIPLIER[PROFILE_BALANCED]

# --- calibration gating ---------------------------------------------------

CALIBRATION_DAYS = 14
SATURATION_WINDOW = timedelta(hours=3)

# A day only counts toward a baseline if this fraction of it had valid data.
MIN_DAY_COVERAGE = 0.60

# Minimum number of qualifying days before each learned constant is trusted.
MIN_DRYING_DAYS = 3
MIN_DLI_DAYS = 5
MIN_KWINDOW_DAYS = 5
MIN_THERMAL_DAYS = 5

# Outdoor PAR (W/m^2) below this is treated as dawn/dusk noise and excluded from
# the window-transmission ratio to avoid divide-by-near-zero blow-ups. In PAR
# units, aligned with the daylight threshold used for light-hours (10 W/m^2).
# (Was a 1000-lux floor when the outdoor reference was lux; the indoor pairing
# now uses the reliable PAR series, so the floor is in PAR units.)
OUTDOOR_REF_FLOOR = 10.0

# Sun-elevation bands (degrees) for K_window, so a coefficient learned at a low
# winter sun angle is not misapplied to a high summer sun (seasonality fix).
ELEVATION_BANDS: tuple[tuple[str, float, float], ...] = (
    ("low", 0.0, 15.0),
    ("mid", 15.0, 35.0),
    ("high", 35.0, 90.0),
)

# Post-calibration drift rate for M_max (EWMA); small so a single odd reading
# barely moves the learned peak.
PEAK_DRIFT_ALPHA = 0.05


# --- moisture baselines ---------------------------------------------------

def saturated_peak(moisture_samples: Sequence[Sample]) -> float | None:
    """M_max: peak of the rolling 3-hour average of raw moisture."""
    return rolling_max_average(moisture_samples, SATURATION_WINDOW)


def average_daily_drying(day_deltas: Iterable[float]) -> float | None:
    """Mean daily drying rate over days with net moisture loss.

    `day_deltas` are (start_of_day - end_of_day) moisture values; only positive
    deltas (actual drying days) are counted, so watering days do not dilute the
    rate.
    """
    drying = [d for d in day_deltas if d is not None and d > 0]
    if not drying:
        return None
    return mean(drying)


def dry_threshold(
    m_max: float,
    profile: str,
    *,
    custom_multiplier: float | None = None,
) -> float:
    """M_dry lower boundary = profile multiplier * M_max."""
    if profile == PROFILE_CUSTOM and custom_multiplier is not None:
        mult = custom_multiplier
    else:
        mult = DRY_MULTIPLIER.get(profile, DEFAULT_DRY_MULTIPLIER)
    return mult * m_max


def nudge_peak(current: float, observed: float, alpha: float = PEAK_DRIFT_ALPHA) -> float:
    """Slow EWMA correction of a locked M_max toward a freshly observed peak.

    Applied post-calibration so soil compaction / root growth drift is tracked
    without a manual reset. `observed` should already be a smoothed (rolling
    3-hour) peak so noise does not chase the baseline.
    """
    return current + alpha * (observed - current)


# --- light baselines ------------------------------------------------------

def dli_baseline(daily_dli: Iterable[float | None]) -> float | None:
    """Baseline DLI target from per-day DLI totals (outlier-trimmed median)."""
    return robust_median(daily_dli)


@dataclass(frozen=True, slots=True)
class WindowSample:
    """One daylight-hour observation for window-transmission calibration.

    outdoor_lux carries the outdoor radiation reference (PAR, W/m^2) — the field
    name is retained for compatibility. Only the ratio local_lux/outdoor matters,
    so the unit is arbitrary provided calibration and runtime agree (both PAR)."""

    elevation_deg: float
    local_lux: float
    outdoor_lux: float


def _band_for_elevation(elevation_deg: float) -> str | None:
    for name, lo, hi in ELEVATION_BANDS:
        if lo <= elevation_deg < hi:
            return name
    return None


def band_for_elevation(elevation_deg: float) -> str | None:
    """Public: name of the sun-elevation band an angle falls in (or None)."""
    return _band_for_elevation(elevation_deg)


def resolve_k(
    elevation_deg: float,
    k_by_band: dict[str, float] | None,
    k_scalar: float | None,
) -> float | None:
    """Best K_window for a sun elevation: banded value, else scalar fallback."""
    if k_by_band:
        band = _band_for_elevation(elevation_deg)
        if band is not None and band in k_by_band:
            return k_by_band[band]
    return k_scalar


def window_factor_by_elevation(
    observations: Iterable[WindowSample],
    *,
    outdoor_floor: float = OUTDOOR_REF_FLOOR,
) -> dict[str, float]:
    """K_window per sun-elevation band.

    Only observations with outdoor lux above the floor are used (avoids
    dawn/dusk ratio blow-up). Returning a coefficient per elevation band lets
    the light model pick the K matching the current sun angle instead of
    applying one scalar learned in a single season.
    """
    buckets: dict[str, list[float]] = {name: [] for name, _, _ in ELEVATION_BANDS}
    for obs in observations:
        if obs.outdoor_lux < outdoor_floor:
            continue
        band = _band_for_elevation(obs.elevation_deg)
        if band is None:
            continue
        buckets[band].append(obs.local_lux / obs.outdoor_lux)
    return {band: mean(ratios) for band, ratios in buckets.items() if ratios}


def window_factor_scalar(
    observations: Iterable[WindowSample],
    *,
    outdoor_floor: float = OUTDOOR_REF_FLOOR,
) -> float | None:
    """Single-scalar K_window fallback for early calibration / sparse bands."""
    ratios = [
        obs.local_lux / obs.outdoor_lux
        for obs in observations
        if obs.outdoor_lux >= outdoor_floor
    ]
    if not ratios:
        return None
    return mean(ratios)


def reduce_window_observations(
    observations: Iterable[WindowSample],
    *,
    outdoor_floor: float = OUTDOOR_REF_FLOOR,
) -> dict[str, tuple[float, int]]:
    """Reduce a day's window observations to per-band (ratio_sum, count).

    Lets a calibration day be persisted as a handful of scalars instead of raw
    samples, while still allowing the final K_window to aggregate correctly
    across days.
    """
    buckets: dict[str, tuple[float, int]] = {}
    for obs in observations:
        if obs.outdoor_lux < outdoor_floor:
            continue
        band = _band_for_elevation(obs.elevation_deg)
        if band is None:
            continue
        s, c = buckets.get(band, (0.0, 0))
        buckets[band] = (s + obs.local_lux / obs.outdoor_lux, c + 1)
    return buckets


# --- thermal baselines ----------------------------------------------------

def thermal_mean(daily_means: Iterable[float | None]) -> float | None:
    """Expected daily-mean temperature over calibration days."""
    vals = [v for v in daily_means if v is not None]
    return mean(vals) if vals else None


def diurnal_swing(daily_min_max: Iterable[tuple[float, float]]) -> float | None:
    """Average normal day-night temperature swing (max - min per day)."""
    swings = [hi - lo for lo, hi in daily_min_max if lo is not None and hi is not None]
    return mean(swings) if swings else None


# --- 14-day synthesis -----------------------------------------------------

@dataclass
class DailyRecord:
    """One calibration day's already-reduced contributions.

    The engine fills these in per day. `coverage` is the valid-data fraction of
    the day (from accumulator.coverage_ratio); a day below MIN_DAY_COVERAGE does
    not contribute a baseline even if it carries values.
    """

    day_index: int
    coverage: float = 0.0
    moisture_samples: list[Sample] = field(default_factory=list)
    moisture_delta: float | None = None          # start-of-day - end-of-day
    daily_dli: float | None = None
    window_observations: list[WindowSample] = field(default_factory=list)
    daily_temp_mean: float | None = None
    daily_temp_min_max: tuple[float, float] | None = None

    # Compact alternatives so a day can be persisted without raw sample buffers.
    day_peak: float | None = None                # pre-reduced rolling-3h peak
    window_band_ratios: dict[str, tuple[float, int]] | None = None  # band -> (sum, count)

    @property
    def is_valid(self) -> bool:
        return self.coverage >= MIN_DAY_COVERAGE


@dataclass
class CalibrationResult:
    status: str                      # "complete" | "incomplete"
    constants: dict[str, object]
    valid_days: dict[str, int]
    missing: list[str]
    days_elapsed: int


def synthesize_calibration(
    records: Sequence[DailyRecord],
    profile: str,
    *,
    custom_multiplier: float | None = None,
    placement: str = "indoor",
) -> CalibrationResult:
    """Decide which learned constants can be trusted from collected days.

    Only valid days (sufficient coverage) contribute. Each constant is gated on
    its own minimum-valid-day count; if a required constant is under-gated the
    result is `incomplete` and names what is missing, so the engine extends the
    observation window instead of locking a bad baseline. `placement` selects
    whether the light baseline is DLI (outdoor) or K_window (indoor).
    """
    valid = [r for r in records if r.is_valid]
    days_elapsed = len(records)

    # Moisture -----------------------------------------------------------
    day_peaks = [r.day_peak for r in valid if r.day_peak is not None]
    if day_peaks:
        m_max = max(day_peaks)
    else:
        all_moisture: list[Sample] = []
        for r in valid:
            all_moisture.extend(r.moisture_samples)
        m_max = saturated_peak(all_moisture)
    drying_days = [r for r in valid if r.moisture_delta is not None and r.moisture_delta > 0]
    delta_m = average_daily_drying(r.moisture_delta for r in drying_days)

    # Light --------------------------------------------------------------
    dli_days = [r for r in valid if r.daily_dli is not None]
    dli_target = dli_baseline(r.daily_dli for r in dli_days)

    # Prefer pre-reduced per-band ratio sums; fall back to raw observations.
    band_totals: dict[str, tuple[float, int]] = {}
    for r in valid:
        if r.window_band_ratios:
            for band, (s, c) in r.window_band_ratios.items():
                ts, tc = band_totals.get(band, (0.0, 0))
                band_totals[band] = (ts + s, tc + c)

    if band_totals:
        k_by_band = {b: s / c for b, (s, c) in band_totals.items() if c > 0}
        total_sum = sum(s for s, _ in band_totals.values())
        total_count = sum(c for _, c in band_totals.values())
        k_scalar = total_sum / total_count if total_count > 0 else None
        kwindow_days = [r for r in valid if r.window_band_ratios]
    else:
        window_obs: list[WindowSample] = []
        for r in valid:
            window_obs.extend(r.window_observations)
        k_by_band = window_factor_by_elevation(window_obs)
        k_scalar = window_factor_scalar(window_obs)
        kwindow_days = [r for r in valid if r.window_observations]

    # Thermal ------------------------------------------------------------
    thermal_days = [r for r in valid if r.daily_temp_mean is not None]
    t_bar = thermal_mean(r.daily_temp_mean for r in thermal_days)
    swing_pairs = [r.daily_temp_min_max for r in valid if r.daily_temp_min_max is not None]
    t_swing = diurnal_swing(swing_pairs)

    valid_days = {
        "valid_total": len(valid),
        "drying": len(drying_days),
        "dli": len(dli_days),
        "kwindow": len(kwindow_days),
        "thermal": len(thermal_days),
    }

    # Gating -------------------------------------------------------------
    missing: list[str] = []
    if m_max is None:
        missing.append("m_max (no validated saturation peak)")
    if delta_m is None or valid_days["drying"] < MIN_DRYING_DAYS:
        missing.append(f"drying_rate (need >= {MIN_DRYING_DAYS} drying days)")

    outdoor = placement == "outdoor"
    if outdoor:
        if dli_target is None or valid_days["dli"] < MIN_DLI_DAYS:
            missing.append(f"dli_target (need >= {MIN_DLI_DAYS} valid daylight days)")
    else:
        if k_scalar is None or valid_days["kwindow"] < MIN_KWINDOW_DAYS:
            missing.append(f"k_window (need >= {MIN_KWINDOW_DAYS} daylight days)")
    if t_bar is None or valid_days["thermal"] < MIN_THERMAL_DAYS:
        missing.append(f"thermal_mean (need >= {MIN_THERMAL_DAYS} valid days)")

    constants: dict[str, object] = {
        "profile": profile,
        "placement": placement,
        "custom_multiplier": (
            float(custom_multiplier)
            if profile == PROFILE_CUSTOM and custom_multiplier is not None
            else None
        ),
        "dry_multiplier": (
            float(custom_multiplier)
            if profile == PROFILE_CUSTOM and custom_multiplier is not None
            else DRY_MULTIPLIER.get(profile, DEFAULT_DRY_MULTIPLIER)
        ),
        "m_max": m_max,
        "m_dry": dry_threshold(m_max, profile, custom_multiplier=custom_multiplier)
        if m_max is not None
        else None,
        "drying_rate": delta_m,
        "dli_target": dli_target,
        "k_window_by_band": k_by_band,
        "k_window_scalar": k_scalar,
        # Reference unit for the window-transmission ratio. Baselines locked
        # before the PAR switch have no stamp (or an older one); the runtime
        # gates on this so a lux-era k is never applied to PAR pairing.
        "light_ref": "par",
        "thermal_mean": t_bar,
        "diurnal_swing": t_swing,
    }

    status = "complete" if not missing else "incomplete"
    return CalibrationResult(
        status=status,
        constants=constants,
        valid_days=valid_days,
        missing=missing,
        days_elapsed=days_elapsed,
    )
