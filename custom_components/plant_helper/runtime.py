"""Runtime helpers between the persisted sample buffers and the engine.

Pure logic (no Home Assistant): day-close reduction, calibration advancement,
dormancy advancement, indoor-observation pairing, and EngineInputs assembly. The
coordinator (HA) polls sensors, persists rolling series, then calls these at the
right cadence.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Sequence

from .engine.accumulator import (
    Sample,
    nearest_value,
    complete_day_dli,
    coverage_ratio,
    extent,
    rolling_max_average,
    time_weighted_mean,
    window,
)
from .engine.util import parse_iso
from .engine import calibration_math as cal
from .engine import dormancy as dorm
from .engine.engine import EngineInputs
from .engine.light_model import IndoorLightObservation
from . import learned_store as ls

DAY = timedelta(hours=24)
SATURATION_WINDOW = timedelta(hours=3)


# --- day-close reduction --------------------------------------------------

def reduce_day(
    *,
    day_index: int,
    now: datetime,
    placement: str,
    moisture: Sequence[Sample],
    soil_temp: Sequence[Sample],
    par: Sequence[Sample],
    window_obs: Sequence[cal.WindowSample],
    max_gap: timedelta,
) -> cal.DailyRecord:
    """Reduce one day of samples to a compact calibration record (no raw buffers)."""
    m_win = window(moisture, now, DAY)
    coverage = coverage_ratio(moisture, now, DAY, max_gap)
    day_peak = rolling_max_average(m_win, SATURATION_WINDOW)

    usable_m = [s for s in m_win if s.usable]
    moisture_delta = (
        usable_m[0].value - usable_m[-1].value if len(usable_m) >= 2 else None
    )

    dli = None
    if placement == "outdoor":
        # Most recent complete STRÅNG calendar day (stable across local midnight).
        dli = complete_day_dli(par, max_gap)

    band_ratios = (
        cal.reduce_window_observations(window_obs)
        if placement == "indoor" and window_obs
        else None
    )

    st_win = window(soil_temp, now, DAY)
    tmean = time_weighted_mean(st_win, max_gap)
    lo, hi = extent(st_win)
    minmax = (lo, hi) if (lo is not None and hi is not None) else None

    return cal.DailyRecord(
        day_index=day_index,
        coverage=coverage,
        day_peak=day_peak,
        moisture_delta=moisture_delta,
        daily_dli=dli,
        window_band_ratios=band_ratios,
        daily_temp_mean=tmean,
        daily_temp_min_max=minmax,
    )


# --- (de)serialization of compact records --------------------------------

def serialize_day_record(record: cal.DailyRecord) -> dict[str, Any]:
    bands = None
    if record.window_band_ratios:
        bands = {b: [s, c] for b, (s, c) in record.window_band_ratios.items()}
    return {
        "day_index": record.day_index,
        "coverage": record.coverage,
        "day_peak": record.day_peak,
        "moisture_delta": record.moisture_delta,
        "daily_dli": record.daily_dli,
        "window_band_ratios": bands,
        "daily_temp_mean": record.daily_temp_mean,
        "daily_temp_min_max": list(record.daily_temp_min_max)
        if record.daily_temp_min_max
        else None,
    }


def deserialize_day_record(d: dict[str, Any]) -> cal.DailyRecord:
    bands = d.get("window_band_ratios")
    band_map = (
        {b: (float(v[0]), int(v[1])) for b, v in bands.items()} if bands else None
    )
    mm = d.get("daily_temp_min_max")
    return cal.DailyRecord(
        day_index=d.get("day_index", 0),
        coverage=d.get("coverage", 0.0),
        day_peak=d.get("day_peak"),
        moisture_delta=d.get("moisture_delta"),
        daily_dli=d.get("daily_dli"),
        window_band_ratios=band_map,
        daily_temp_mean=d.get("daily_temp_mean"),
        daily_temp_min_max=(tuple(mm) if mm else None),
    )


# --- calibration advancement ---------------------------------------------

def advance_calibration(
    data: dict[str, Any],
    plant_id: str,
    placement: str,
    day_record: cal.DailyRecord,
    profile: str,
    *,
    now_iso: str,
    custom_multiplier: float | None = None,
    calibration_days: int = cal.CALIBRATION_DAYS,
) -> tuple[bool, cal.CalibrationResult]:
    """Append a day, synthesise, and lock the baseline when ready.

    A baseline is locked once at least `calibration_days` have elapsed AND every
    required constant is gated (synthesis complete). If day 14 arrives still
    incomplete, calibration stays open (status 'extending') rather than locking a
    bad baseline — the partial-calibration rule.
    """
    prog = ls.get_calibration(data, plant_id, placement) or {
        "status": "calibrating",
        "day_records": [],
    }
    prog.setdefault("day_records", []).append(serialize_day_record(day_record))

    records = [deserialize_day_record(d) for d in prog["day_records"]]
    result = cal.synthesize_calibration(
        records, profile, custom_multiplier=custom_multiplier, placement=placement
    )
    days_elapsed = len(records)

    locked = False
    if days_elapsed >= calibration_days and result.status == "complete":
        ls.set_baseline(
            data, plant_id, placement, result.constants,
            status="complete", locked_at=now_iso,
        )
        prog["status"] = "complete"
        locked = True
    else:
        prog["status"] = (
            result.status if days_elapsed < calibration_days else "extending"
        )
    ls.set_calibration(data, plant_id, placement, prog)
    return locked, result



def adapt_locked_baseline(
    data: dict[str, Any],
    plant_id: str,
    placement: str,
    day_record: cal.DailyRecord,
    *,
    now_iso: str,
) -> bool:
    """Slowly adapt a locked baseline from qualified post-lock evidence.

    Phase H deliberately adapts only M_max. A candidate must come from a
    well-covered day and exceed the current peak, which represents a validated
    new saturation observation rather than ordinary drying noise. Drying rate,
    DLI, window transmission, and thermal constants remain calibration-locked
    until each receives its own bounded multi-day policy.
    """
    baseline = ls.active_baseline(data, plant_id, placement)
    if not baseline or baseline.get("status") != "complete":
        return False
    candidate = day_record.day_peak
    current = baseline.get("m_max")
    if (
        candidate is None
        or current is None
        or day_record.coverage < cal.MIN_DAY_COVERAGE
        or candidate <= current
    ):
        return False
    updated = cal.nudge_peak(float(current), float(candidate))
    if updated <= float(current):
        return False
    old_dry = baseline.get("m_dry")
    baseline["m_max"] = updated
    profile = baseline.get("profile")
    custom_multiplier = baseline.get("custom_multiplier")
    dry_multiplier = baseline.get("dry_multiplier")
    if profile in cal.DRY_MULTIPLIER:
        baseline["m_dry"] = cal.dry_threshold(updated, profile)
    elif profile == cal.PROFILE_CUSTOM and custom_multiplier is not None:
        baseline["m_dry"] = cal.dry_threshold(
            updated, profile, custom_multiplier=float(custom_multiplier)
        )
    elif dry_multiplier is not None:
        baseline["m_dry"] = updated * float(dry_multiplier)
    elif old_dry is not None and float(current) > 0:
        # Migration-safe fallback for pre-policy baselines.
        baseline["m_dry"] = updated * (float(old_dry) / float(current))
    baseline["adapted_at"] = now_iso
    baseline["adaptation"] = "m_max_only"
    return True

def is_calibrating(data: dict[str, Any], plant_id: str, placement: str) -> bool:
    """True until a complete baseline exists for the active placement."""
    return not ls.has_baseline(data, plant_id, placement)


# --- dormancy advancement (once per day) ---------------------------------

def advance_dormancy(
    data: dict[str, Any],
    plant_id: str,
    *,
    par_slope_30d: float | None,
    soil_temp_slope_30d: float | None,
    now_iso: str,
) -> dorm.DormancyResult:
    """Evaluate dormancy and update the persisted day counter with hysteresis."""
    d = ls.get_dormancy(data, plant_id)
    result = dorm.evaluate_dormancy(
        currently_dormant=d["dormant"],
        days_in_state=d["days_in_state"],
        par_slope_30d=par_slope_30d,
        soil_temp_slope_30d=soil_temp_slope_30d,
    )
    new_days = 0 if result.changed else d["days_in_state"] + 1
    ls.set_dormancy(
        data, plant_id,
        dormant=result.dormant, days_in_state=new_days,
        changed_at=(now_iso if result.changed else d.get("changed_at")),
    )
    return result


# --- indoor observation pairing (handles STRÅNG lag) ---------------------

def build_indoor_observations(
    local_lux: Sequence[Sample],
    outdoor_lux: Sequence[Sample],
    elevation: Sequence[Sample],
    max_gap: timedelta,
) -> list[IndoorLightObservation]:
    """Pair indoor lux to concurrent outdoor lux + sun elevation.

    Iterates over the (lagged) STRÅNG outdoor samples and pairs each to the local
    lux and elevation from that same past moment, so obstruction is judged on
    genuinely concurrent data despite STRÅNG's ~1-day publish lag.
    """
    obs: list[IndoorLightObservation] = []
    for o in outdoor_lux:
        if not o.usable:
            continue
        lux = nearest_value(local_lux, o.ts, max_gap)
        elev = nearest_value(elevation, o.ts, max_gap)
        if lux is None or elev is None:
            continue
        obs.append(IndoorLightObservation(o.ts, elev, lux, o.value))
    return obs


# --- Tier-2 long-horizon trend math --------------------------------------

def _slope_per_day(values: Sequence[float]) -> float | None:
    """Least-squares slope (units per day) of an evenly-spaced daily series."""
    n = len(values)
    if n < 2:
        return None
    xs = list(range(n))
    mx = sum(xs) / n
    my = sum(values) / n
    denom = sum((x - mx) ** 2 for x in xs)
    if denom == 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, values)) / denom


def daily_field_slope(
    daily_history: Sequence[dict[str, Any]],
    field: str,
    *,
    days: int = 30,
) -> float | None:
    """Slope-per-day of a daily-summary field over the trailing `days`."""
    recent = [h for h in daily_history[-days:] if h.get(field) is not None]
    values = [float(h[field]) for h in recent]
    return _slope_per_day(values)


def recent_dli_means(
    daily_history: Sequence[dict[str, Any]],
) -> tuple[float | None, float | None]:
    """(3-day mean, 7-day mean) of daily DLI from the history (None if absent)."""

    def _mean(n: int) -> float | None:
        vals = [
            float(h["daily_dli"])
            for h in daily_history[-n:]
            if h.get("daily_dli") is not None
        ]
        return sum(vals) / len(vals) if vals else None

    return _mean(3), _mean(7)


# --- reboot-safe condition timers ----------------------------------------

TIMER_KEYS = ("dry", "wet", "cold", "warm")


def timer_duration(
    data: dict[str, Any],
    plant_id: str,
    key: str,
    now: datetime,
) -> float:
    """Minutes a condition has been continuously active, from its persisted
    "since" stamp. Returns 0 when inactive.

    Because it reads a persisted timestamp rather than walking the sample buffer,
    the duration is immune to sample retention limits AND to restarts/downtime: a
    plant that has been dry for five days still reads five days after a reboot or
    a day of Home Assistant being offline.
    """
    since = parse_iso(ls.get_timer(data, plant_id, key))
    if since is None:
        return 0.0
    return max(0.0, (now - since).total_seconds() / 60.0)


def update_timer(
    data: dict[str, Any],
    plant_id: str,
    key: str,
    *,
    active: bool,
    now: datetime,
) -> None:
    """Stamp a condition's start when it becomes active, clear it when it ends.

    Idempotent while a condition persists (the original "since" is preserved), so
    the accumulated duration keeps growing across cycles and reboots.
    """
    current = ls.get_timer(data, plant_id, key)
    if active:
        if current is None:
            ls.set_timer(data, plant_id, key, now.isoformat())
    elif current is not None:
        ls.set_timer(data, plant_id, key, None)


# --- EngineInputs assembly ------------------------------------------------

def build_engine_inputs(
    *,
    now: datetime,
    config: dict[str, Any],
    baseline: dict[str, Any] | None,
    dormancy: dict[str, Any],
    series: dict[str, list[Sample]],
    indoor_obs: Sequence[IndoorLightObservation],
    forecast: list[Any],
    diffuse_irradiance: float | None,
    global_irradiance: float | None,
    par_slope_30d: float | None,
    soil_temp_slope_30d: float | None,
    calibrating: bool,
    local_gap: timedelta | None = None,
    macro_gap: timedelta | None = None,
) -> EngineInputs:
    """Assemble EngineInputs from config, learned baseline, and persisted series.

    `series` provides RawReading-style already-validated Sample lists is not
    required here; the engine validates raw readings, so we pass raw readings via
    the *_raw fields. This helper focuses on stitching learned constants and
    context together; the coordinator supplies the raw reading lists.
    """
    b = baseline or {}
    placement = config.get("placement", "indoor")
    kwargs: dict[str, Any] = dict(
        now=now,
        placement=placement,
        profile=config.get("profile", "balanced"),
        calibrating=calibrating,
        m_max=b.get("m_max"),
        m_dry=b.get("m_dry"),
        drying_rate=b.get("drying_rate"),
        dli_target=b.get("dli_target"),
        k_by_band=b.get("k_window_by_band"),
        k_scalar=b.get("k_window_scalar"),
        thermal_mean=b.get("thermal_mean"),
        diurnal_swing=b.get("diurnal_swing"),
        indoor_light_obs=list(indoor_obs),
        diffuse_irradiance=diffuse_irradiance,
        global_irradiance=global_irradiance,
        forecast=list(forecast),
        profile_rain_limit_mm=config.get("rain_limit_mm", 1.0),
        currently_dormant=dormancy.get("dormant", False),
        days_in_dormancy_state=dormancy.get("days_in_state", 999),
        par_slope_30d=par_slope_30d,
        soil_temp_slope_30d=soil_temp_slope_30d,
    )
    if local_gap is not None:
        kwargs["local_gap"] = local_gap
    if macro_gap is not None:
        kwargs["macro_gap"] = macro_gap
    return EngineInputs(**kwargs)
