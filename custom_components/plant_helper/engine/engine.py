"""Engine orchestrator — one compute cycle across every model.

Pure and HA-free: it takes already-assembled inputs (raw series + learned
constants + forecast + config) and returns a full assessment. The HA layer is
responsible only for reading entity states into these inputs and rendering the
result; all decision logic lives here and in the per-model modules, so the whole
pipeline is unit-testable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from . import moisture_model as mm
from . import light_model as lm
from . import thermal_model as th
from . import dormancy as dorm
from . import air_quality as aq
from . import health as hp
from . import precedence as prec
from .light_model import IndoorLightObservation
from .thermal_model import ForecastHour
from .timeseries import current_run_minutes, min_max, windowed_mean
from .validation import (
    LUX_SPEC,
    MOISTURE_SPEC,
    PAR_SPEC,
    SOIL_TEMP_SPEC,
    RawReading,
    battery_status,
    care_gate,
    validate_series,
)

DEFAULT_LOCAL_GAP = timedelta(minutes=25)   # ~2.5x a 10-min local cadence
DEFAULT_MACRO_GAP = timedelta(minutes=90)   # SMHI/PAR hourly cadence

# PAR (W/m^2) at/above which light counts as photosynthetically useful, for the
# weather-aware "light hours today" figure (roughly the light-compensation band).
LIGHT_HOURS_PAR_THRESHOLD = 10.0
DAY = timedelta(hours=24)


@dataclass(slots=True)
class EngineInputs:
    now: datetime
    placement: str = "indoor"
    profile: str = "balanced"
    calibrating: bool = False

    # Learned constants (absent while calibrating).
    m_max: float | None = None
    m_dry: float | None = None
    drying_rate: float | None = None
    dli_target: float | None = None
    dli_mean_3d: float | None = None
    dli_mean_7d: float | None = None
    k_by_band: dict[str, float] | None = None
    k_scalar: float | None = None
    thermal_mean: float | None = None
    diurnal_swing: float | None = None
    indoor_adequacy_3d: float | None = None
    indoor_adequacy_7d: float | None = None

    # Raw local telemetry.
    moisture_raw: list[RawReading] = field(default_factory=list)
    soil_temp_raw: list[RawReading] = field(default_factory=list)
    lux_raw: list[RawReading] = field(default_factory=list)
    battery_pct: float | str | None = None

    # Macro / external.
    par_raw: list[RawReading] = field(default_factory=list)
    indoor_light_obs: list[IndoorLightObservation] = field(default_factory=list)
    diffuse_irradiance: float | None = None
    global_irradiance: float | None = None
    forecast: list[ForecastHour] = field(default_factory=list)
    profile_rain_limit_mm: float = 1.0
    ozone_ugm3: float | None = None      # optional outdoor air-quality advisory
    daylight_hours: float | None = None  # from sun.sun (astronomical day length)

    # Dormancy tracking (persisted between cycles).
    currently_dormant: bool = False
    days_in_dormancy_state: int = 999
    par_slope_30d: float | None = None
    soil_temp_slope_30d: float | None = None

    local_gap: timedelta = DEFAULT_LOCAL_GAP
    macro_gap: timedelta = DEFAULT_MACRO_GAP

    # Persisted, reboot-safe run durations (minutes). When provided by the
    # coordinator these override the sample-walk timers, so long "too-long"
    # counters survive restarts and downtime gaps. None -> compute from samples.
    dry_run_minutes: float | None = None
    wet_run_minutes: float | None = None
    cold_run_minutes: float | None = None
    warm_run_minutes: float | None = None


@dataclass(slots=True)
class EngineResult:
    care_ok: bool
    care_reason: str
    calibrating: bool
    dormant: bool
    dormancy_changed: bool
    moisture: mm.MoistureAssessment | None
    light: lm.LightAssessment | None
    thermal: th.ThermalAssessment | None
    health: hp.HealthResult
    precedence: prec.Precedence
    run_minutes: dict[str, float] = field(default_factory=dict)
    battery_level: str | None = None
    battery_percent: float | None = None
    air_quality: aq.AirQualityAssessment | None = None
    light_hours_today: float | None = None
    daylight_hours: float | None = None
    learned_watering_interval_days: float | None = None

    def summary(self) -> dict[str, object]:
        """Flat dict for entity attributes / debugging."""
        out: dict[str, object] = {
            "care_ok": self.care_ok,
            "care_reason": self.care_reason,
            "calibrating": self.calibrating,
            "dormant": self.dormant,
            "primary_issue": self.precedence.primary_issue,
            "care_action": self.precedence.care_action,
            "reason": self.precedence.reason,
            "severity": self.precedence.severity,
            "health_score": self.health.score,
            "health_state": self.health.state,
        }
        if self.air_quality is not None and self.air_quality.advisory not in ("none", "not_applicable"):
            out["ozone_advisory"] = self.air_quality.advisory
            out["ozone_ugm3"] = self.air_quality.ozone_ugm3
        if self.run_minutes:
            out["run_days"] = {k: round(v / 1440.0, 2) for k, v in self.run_minutes.items() if v}
        if self.moisture is not None:
            out["moisture_state"] = self.moisture.state
            out["watering_urgency"] = self.moisture.urgency
            out["calculated_moisture"] = self.moisture.calculated_moisture
            out["days_until_dry"] = self.moisture.days_until_dry
            out["suppressed_by_rain"] = self.moisture.suppressed
        if self.light is not None:
            out["light_state"] = self.light.state
            out["light_score"] = self.light.score
            out["light_obstruction"] = self.light.obstruction
        if self.thermal is not None:
            out["thermal_state"] = self.thermal.state
            out["drying_modifier"] = self.thermal.drying_modifier
            out["hazard"] = self.thermal.hazard
        return out


def _latest(samples) -> float | None:
    usable = [s.value for s in samples if s.usable]
    return usable[-1] if usable else None


def compute(inp: EngineInputs) -> EngineResult:
    """Run a full assessment cycle."""
    moisture_s = validate_series(inp.moisture_raw, MOISTURE_SPEC)
    soil_temp_s = validate_series(inp.soil_temp_raw, SOIL_TEMP_SPEC)
    lux_s = validate_series(inp.lux_raw, LUX_SPEC)
    par_s = validate_series(inp.par_raw, PAR_SPEC)
    battery = battery_status(inp.battery_pct) if inp.battery_pct is not None else None

    # Weather-aware effective light hours from the same complete PAR day the DLI
    # uses; computed early so it's available even under a care halt.
    from .accumulator import complete_day_light_hours
    light_hours_today = complete_day_light_hours(
        par_s, LIGHT_HOURS_PAR_THRESHOLD, inp.macro_gap
    )

    # The plant's own full->dry interval (days), once calibration has locked the
    # baseline: span between wet and dry thresholds over the learned drying rate.
    # Uses the raw learned rate (species-natural cycle), not today's thermal-
    # adjusted rate. None while calibrating. Consumed only by the read-only
    # species-insight layer, never by care decisions.
    learned_watering_interval_days = None
    if (not inp.calibrating and inp.m_max is not None and inp.m_dry is not None
            and inp.drying_rate and inp.drying_rate > 0):
        span = inp.m_max - inp.m_dry
        if span > 0:
            learned_watering_interval_days = round(span / inp.drying_rate, 1)

    have_valid = any(s.usable for s in (moisture_s + soil_temp_s + lux_s))
    gate = care_gate(battery=battery, have_any_valid_sensor=have_valid)

    # Dormancy is evaluated even under a care halt (it's a slow seasonal signal).
    dorm_res = dorm.evaluate_dormancy(
        currently_dormant=inp.currently_dormant,
        days_in_state=inp.days_in_dormancy_state,
        par_slope_30d=inp.par_slope_30d,
        soil_temp_slope_30d=inp.soil_temp_slope_30d,
    )

    air_quality = aq.assess_air_quality(
        ozone_ugm3=inp.ozone_ugm3, placement=inp.placement
    )

    if not gate.care_ok:
        # Describe the fault; do not emit a possibly-false plant status.
        precedence = prec.resolve_precedence(
            care_ok=False, care_reason=gate.reason,
            moisture_state=mm.NORMAL, light_state=lm.UNKNOWN,
            light_obstruction=False, thermal_state=th.UNKNOWN,
            dormant=dorm_res.dormant,
        )
        return EngineResult(
            care_ok=False, care_reason=gate.reason, calibrating=inp.calibrating,
            dormant=dorm_res.dormant, dormancy_changed=dorm_res.changed,
            moisture=None, light=None, thermal=None,
            health=hp.HealthResult(None, hp.UNAVAILABLE, {}),
            precedence=precedence,
            battery_level=(battery.level if battery else None),
            battery_percent=(battery.percent if battery else None),
            air_quality=air_quality,
            light_hours_today=light_hours_today,
            daylight_hours=inp.daylight_hours,
            learned_watering_interval_days=learned_watering_interval_days,
        )

    # --- Thermal (also yields the drying modifier moisture consumes) -------
    cloud = th.cloud_factor(inp.diffuse_irradiance, inp.global_irradiance)
    hazard, hazard_type = th.detect_hazard(inp.forecast, placement=inp.placement)
    next24 = [
        fh.condition for fh in inp.forecast if 0 <= fh.hours_ahead <= 24
    ]
    current_temp = _latest(soil_temp_s)
    mean_24h = windowed_mean(soil_temp_s, inp.now, DAY, inp.local_gap)
    lo, hi = min_max(soil_temp_s, inp.now, DAY)
    swing_today = (hi - lo) if (lo is not None and hi is not None) else None

    cold_run = warm_run = 0.0
    if inp.thermal_mean is not None:
        cold_line = inp.thermal_mean - th.DEVIATION_C
        warm_line = inp.thermal_mean + th.DEVIATION_C
        cold_run = (
            inp.cold_run_minutes if inp.cold_run_minutes is not None
            else current_run_minutes(soil_temp_s, inp.local_gap, lambda t: t < cold_line)
        )
        warm_run = (
            inp.warm_run_minutes if inp.warm_run_minutes is not None
            else current_run_minutes(soil_temp_s, inp.local_gap, lambda t: t > warm_line)
        )

    thermal = th.evaluate_thermal(
        current_temp=current_temp, mean_24h=mean_24h, thermal_mean=inp.thermal_mean,
        swing_today=swing_today, learned_swing=inp.diurnal_swing,
        cold_run_minutes=cold_run, warm_run_minutes=warm_run,
        cloud=cloud, forecast_next24=next24, hazard=hazard, hazard_type=hazard_type,
    )

    # --- Moisture (drying rate pre-modulated by cloud/forecast) ------------
    compensated = mm.temperature_compensate(moisture_s, soil_temp_s)
    effective_drying = (
        inp.drying_rate * thermal.drying_modifier if inp.drying_rate else inp.drying_rate
    )
    precip48 = th.aggregate_forecast_precip(inp.forecast, horizon_hours=48.0)
    moisture = mm.evaluate_moisture(
        now=inp.now, compensated=compensated, max_gap=inp.local_gap,
        m_dry=inp.m_dry, m_max=inp.m_max, drying_rate=effective_drying,
        placement=inp.placement, forecast_precip_mm=precip48,
        profile_rain_limit_mm=inp.profile_rain_limit_mm, dormant=dorm_res.dormant,
        dry_run_minutes=inp.dry_run_minutes, wet_run_minutes=inp.wet_run_minutes,
    )

    # --- Light -------------------------------------------------------------
    if inp.placement == "outdoor":
        today_dli = th_daily_dli(par_s, inp.now, inp.macro_gap)
        light = lm.evaluate_light_outdoor(
            today_dli=today_dli, dli_target=inp.dli_target,
            dli_mean_3d=inp.dli_mean_3d, dli_mean_7d=inp.dli_mean_7d,
        )
    else:
        light = lm.evaluate_light_indoor(
            observations=inp.indoor_light_obs, k_by_band=inp.k_by_band,
            k_scalar=inp.k_scalar, max_gap=inp.macro_gap,
            adequacy_3d=inp.indoor_adequacy_3d, adequacy_7d=inp.indoor_adequacy_7d,
        )

    # --- Health + precedence ----------------------------------------------
    moisture_score = max(0.0, min(100.0, 100.0 - moisture.urgency))
    thermal_score = thermal.score
    health = hp.evaluate_health(
        moisture_score=moisture_score, light_score=light.score,
        thermal_score=thermal_score, calibrating=inp.calibrating,
        dormant=dorm_res.dormant,
    )
    precedence = prec.resolve_precedence(
        care_ok=True, care_reason="ok",
        moisture_state=moisture.state, light_state=light.state,
        light_obstruction=light.obstruction, thermal_state=thermal.state,
        dormant=dorm_res.dormant,
    )

    run_minutes = {
        k: v
        for k, v in (
            ("dry", inp.dry_run_minutes),
            ("wet", inp.wet_run_minutes),
            ("cold", inp.cold_run_minutes),
            ("warm", inp.warm_run_minutes),
        )
        if v
    }

    return EngineResult(
        care_ok=True, care_reason="ok", calibrating=inp.calibrating,
        dormant=dorm_res.dormant, dormancy_changed=dorm_res.changed,
        moisture=moisture, light=light, thermal=thermal,
        health=health, precedence=precedence, run_minutes=run_minutes,
        battery_level=(battery.level if battery else None),
        battery_percent=(battery.percent if battery else None),
        air_quality=air_quality,
        light_hours_today=light_hours_today,
        daylight_hours=inp.daylight_hours,
        learned_watering_interval_days=learned_watering_interval_days,
    )


def th_daily_dli(par_samples, now: datetime, macro_gap: timedelta) -> float | None:
    """DLI of the most recent complete STRÅNG calendar day (None if none).

    STRÅNG publishes hourly data for a full calendar day, ~a day behind. Using the
    most recent *complete* day (rather than a rolling 24h window) gives a stable
    daily light integral that does not dip or jump across local midnight or when
    STRÅNG begins publishing a new date.
    """
    from .accumulator import complete_day_dli

    return complete_day_dli(par_samples, macro_gap)
