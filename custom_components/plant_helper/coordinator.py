"""Plant Helper coordinator (Home Assistant glue).

One `DataUpdateCoordinator` drives the whole integration each interval:

  1. Read the shared macro sources (STRÅNG, forecast, sun elevation) and each
     plant's local sensors, appending them to the Tier-1 sample store. STRÅNG
     samples are timestamped by their `selected_data_time` so DLI integrates on
     the correct (lagged) axis.
  2. On a local-day rollover, reduce the completed day to a compact record,
     advance calibration (locking a baseline at day 14 when complete), append the
     Tier-2 daily aggregate, and advance dormancy from the 30-day trends.
  3. Assemble EngineInputs from persisted series + learned baseline + context and
     run `engine.compute`, exposing one EngineResult per plant.

All decision logic lives in the tested pure layers; this file only wires them to
HA's lifecycle and state machine.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator
from homeassistant.util import dt as dt_util

from . import learned_store as ls
from . import runtime as rt
from . import sample_store as sstore
from .engine import engine as eng
from .engine.util import to_float
from .engine.accumulator import Sample
from .engine.validation import (
    LUX_SPEC,
    MOISTURE_SPEC,
    PAR_SPEC,
    SOIL_TEMP_SPEC,
    validate_series,
    current_reading_stale,
)
from .sources import forecast as forecast_src
from .sources import open_meteo as open_meteo_src

_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _MacroReading:
    """Radiation values normalized for the plant engine."""

    par: float | None
    global_irradiance: float | None
    diffuse_irradiance: float | None
    direct_horizontal: float | None
    direct_normal: float | None
    outdoor_lux: float | None
    data_stale: bool
    api_issue: bool
    age_hours: float | None
    selected_data_time: datetime | None
    stale: bool

UPDATE_INTERVAL = timedelta(minutes=10)
ENRICHMENT_INTERVAL = timedelta(hours=24)
ENRICHMENT_RETRY_INTERVAL = timedelta(minutes=15)  # retry unresolved plants soon, not daily
SUN_ENTITY = "sun.sun"
PROVISIONAL_LIGHT_MIN_OBS = 6  # min paired daylight observations for a live k

# Neutral macro used before the first STRÅNG API fetch lands (treated as stale so
# the light model falls back to the learned baseline rather than inventing data).

_EMPTY_MACRO = _MacroReading(
    par=None, global_irradiance=None, diffuse_irradiance=None,
    direct_horizontal=None, direct_normal=None, outdoor_lux=None,
    data_stale=True, api_issue=False, age_hours=None,
    selected_data_time=None, stale=True,
)


def _state_float(hass: HomeAssistant, entity_id: str | None) -> float | None:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable", None):
        return None
    return to_float(state.state)


def _state_raw(hass: HomeAssistant, entity_id: str | None) -> str | None:
    """Raw state string (for batteries that report high/middle/low, not %)."""
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable", None):
        return None
    return state.state


def _sun_elevation(hass: HomeAssistant) -> float | None:
    state = hass.states.get(SUN_ENTITY)
    if state is None:
        return None
    return to_float(state.attributes.get("elevation"))


def _daylight_hours(hass: HomeAssistant) -> float | None:
    """Astronomical daylight length from sun.sun's next rising/setting."""
    state = hass.states.get(SUN_ENTITY)
    if state is None:
        return None
    from .engine.util import daylight_hours, parse_iso

    return daylight_hours(
        parse_iso(state.attributes.get("next_rising")),
        parse_iso(state.attributes.get("next_setting")),
    )


class PlantHelperCoordinator(DataUpdateCoordinator):
    """Owns the compute cycle for all configured plants."""

    def __init__(
        self,
        hass: HomeAssistant,
        *,
        learned: Any,
        samples: Any,
        plants: dict[str, dict[str, Any]],
        forecast_entity: str | None,
        outdoor_data_source: str = "auto",
        ozone_entity: str | None = None,
        api: Any = None,
        update_interval_seconds: int = 300,
        latitude: float | None = None,
        longitude: float | None = None,
    ) -> None:
        try:
            interval_seconds = max(60, min(3600, int(update_interval_seconds)))
        except (TypeError, ValueError):
            interval_seconds = 300
        # Size the per-series count cap so the 3-day time retention is never
        # undercut by the count limit at fast update intervals. Below ~130s the
        # default 800 cap would keep less than the STRÅNG lag / a full calendar
        # day, silently starving indoor-light pairing and complete-day DLI. +20%
        # headroom over the theoretical count.
        self._max_samples = max(
            sstore.MAX_PER_SERIES,
            int(sstore.RETENTION.total_seconds() / interval_seconds * 1.2) + 1,
        )
        super().__init__(
            hass, _LOGGER, name="plant_helper",
            update_interval=timedelta(seconds=interval_seconds),
        )
        self._learned = learned
        self._samples = samples
        self._plants = plants
        self._open_meteo_context = None
        self._last_open_meteo = None
        self._ozone_entity = ozone_entity
        self._api = api
        self._enrichment: dict[str, dict[str, Any]] = {
            pid: cfg["enrichment"]
            for pid, cfg in plants.items()
            if cfg.get("enrichment")
        }
        self._api_health: dict[str, dict[str, Any]] = {}
        self._last_enrichment = None
        self._last_enrichment_retry = None
        self._enrichment_task = None

        self._latitude = latitude
        self._longitude = longitude
        self._par_series_key = "global:par:open_meteo"
        self._radiation_status: dict[str, Any] = {
            "configured_source": "open_meteo",
            "active_source": "open_meteo",
            "available": False,
            "last_attempt": None,
            "last_success": None,
            "last_error": None,
            "latest_data_time": None,
            "data_age_hours": None,
            "sample_counts": {},
            "consecutive_failures": 0,
            "fallback": False,
            "estimated": True,
            "day_source_lock": self._par_series_key,
        }

    @property
    def enrichment(self) -> dict[str, dict[str, Any]]:
        return self._enrichment

    @property
    def api_health(self) -> dict[str, dict[str, Any]]:
        return self._api_health

    @property
    def radiation_status(self) -> dict[str, Any]:
        """Return diagnostic state for the configured radiation source."""
        return dict(self._radiation_status)

    def linked_sources(self, plant_id: str) -> dict[str, str]:
        """Return the HA sensor entities linked to one configured plant."""
        sensors = self._plants.get(plant_id, {}).get("sensors", {})
        return {
            key: entity_id
            for key, entity_id in sensors.items()
            if key in {"moisture", "soil_temp", "lux", "battery"} and entity_id
        }

    async def _async_update_data(self) -> dict[str, eng.EngineResult]:
        now = dt_util.now()
        sdata = self._samples.data

        # --- Open-Meteo radiation and outdoor context --------------------
        macro = _EMPTY_MACRO
        forecast: list[Any] = []
        self._radiation_status["last_attempt"] = now.isoformat()

        if self._latitude is None or self._longitude is None:
            self._radiation_status.update({
                "available": False,
                "last_error": "location_unavailable",
                "consecutive_failures": self._radiation_status.get("consecutive_failures", 0) + 1,
            })
        else:
            refresh_due = (
                self._last_open_meteo is None
                or now - self._last_open_meteo >= timedelta(minutes=30)
            )
            if refresh_due:
                from homeassistant.helpers.aiohttp_client import async_get_clientsession

                context = await open_meteo_src.fetch_context(
                    async_get_clientsession(self.hass),
                    self._latitude,
                    self._longitude,
                    now,
                )
                if context is not None:
                    self._open_meteo_context = context
                    self._last_open_meteo = now
                    self._radiation_status.update({
                        "available": True,
                        "last_success": now.isoformat(),
                        "last_error": None,
                        "consecutive_failures": 0,
                    })
                else:
                    self._radiation_status.update({
                        "last_error": "request_failed",
                        "consecutive_failures": self._radiation_status.get("consecutive_failures", 0) + 1,
                    })

            context = self._open_meteo_context
            context_fresh = (
                context is not None
                and now - context.fetched_at <= timedelta(hours=2)
            )
            if context_fresh and context.estimated_par_series:
                self._par_series_key = "global:par:open_meteo"
                for ts, value in context.estimated_par_series:
                    sstore.append_reading(
                        sdata, self._par_series_key, ts, value, now, dedupe=True
                    )
                latest_ts, historical_par = context.estimated_par_series[-1]
                current_shortwave = context.shortwave_radiation
                current_par = (
                    current_shortwave * open_meteo_src.SHORTWAVE_TO_PAR
                    if current_shortwave is not None
                    else historical_par
                )
                age_hours = max(
                    0.0,
                    (now.replace(tzinfo=None) - latest_ts.replace(tzinfo=None)).total_seconds()
                    / 3600.0,
                )
                macro = _MacroReading(
                    par=current_par,
                    global_irradiance=current_shortwave,
                    diffuse_irradiance=context.diffuse_radiation,
                    direct_horizontal=None,
                    direct_normal=None,
                    outdoor_lux=(
                        current_shortwave * open_meteo_src.SHORTWAVE_TO_LUX
                        if current_shortwave is not None
                        else None
                    ),
                    data_stale=False,
                    api_issue=False,
                    age_hours=age_hours,
                    selected_data_time=now,
                    stale=False,
                )
                self._radiation_status.update({
                    "available": True,
                    "latest_data_time": latest_ts.isoformat(),
                    "data_age_hours": age_hours,
                    "sample_counts": {"estimated_par": len(context.estimated_par_series)},
                    "shortwave_radiation": context.shortwave_radiation,
                    "diffuse_radiation": context.diffuse_radiation,
                    "day_source_lock": self._par_series_key,
                })
            else:
                self._radiation_status["available"] = False
                if not self._radiation_status.get("last_error"):
                    self._radiation_status["last_error"] = "no_usable_data"
        if self._open_meteo_context is not None:
            forecast = self._open_meteo_context.forecast

        elevation = _sun_elevation(self.hass)

        if elevation is not None:
            sstore.append_reading(sdata, "global:elevation", now, elevation, now, max_per_series=self._max_samples)

        results: dict[str, eng.EngineResult] = {}
        for plant_id, cfg in self._plants.items():
            try:
                results[plant_id] = self._process_plant(plant_id, cfg, now, macro, forecast)
            except Exception:  # noqa: BLE001 - one bad plant must not sink the cycle
                _LOGGER.exception("Plant Helper: error processing plant %s", plant_id)
                # Preserve the previous result if we have one.
                prev = (self.data or {}).get(plant_id)
                if prev is not None:
                    results[plant_id] = prev

        self._samples.schedule_save()
        self._learned.schedule_save()
        # Enrichment does network I/O; run it off the update's critical path so a
        # slow/hung provider can't stall setup or the cycle. Entities refresh when
        # it completes.
        if self._enrichment_task is None or self._enrichment_task.done():
            self._enrichment_task = self.hass.async_create_task(
                self._enrich_and_notify(now), "plant_helper_enrichment_refresh"
            )
        return results

    async def async_shutdown(self) -> None:
        """Cancel and drain background work before the config entry unloads."""
        tasks = [
            task
            for task in (self._enrichment_task,)
            if task is not None and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._enrichment_task = None

    async def _enrich_and_notify(self, now) -> None:
        did_refresh = await self._maybe_refresh_enrichment(now)
        if did_refresh:
            self.async_update_listeners()


    async def _maybe_refresh_enrichment(self, now) -> bool:
        """Fetch species context once a day; keep per-provider API health fresh.

        Best-effort and throttled — provider calls are cached, so a restart or a
        cache hit costs nothing. Enrichment is context only; it never feeds the
        care engine.
        """
        if self._api is None:
            return False
        from . import enrichment as en

        first_run = self._last_enrichment is None
        daily_due = first_run or (now - self._last_enrichment) >= ENRICHMENT_INTERVAL

        # Plants that still have no enrichment get retried on a short interval, so
        # a transient startup or provider failure does not leave them blank for a
        # whole day (the daily throttle only governs refreshing resolved plants).
        unresolved = {
            pid for pid, cfg in self._plants.items()
            if cfg.get("species") and not self._enrichment.get(pid)
        }
        retry_due = bool(unresolved) and (
            self._last_enrichment_retry is None
            or (now - self._last_enrichment_retry) >= ENRICHMENT_RETRY_INTERVAL
        )
        if not daily_due and not retry_due:
            return False

        changed = False
        for plant_id, cfg in self._plants.items():
            species = cfg.get("species")
            if not species:
                continue
            if not daily_due and plant_id not in unresolved:
                continue
            try:
                # Force a real provider lookup for a plant that isn't resolved yet
                # (bypassing an empty cache); resolved plants read cache on the
                # throttled daily cycle.
                force = first_run or plant_id in unresolved
                result = await self._api.fetch_plant(species, force_fetch=force)
                if result and getattr(result, "found", False) and result.data:
                    data = dict(result.data)
                    data.setdefault("provider", getattr(result, "provider", None))
                    self._enrichment[plant_id] = en.summarize_enrichment(data)
                    changed = True
            except Exception:  # noqa: BLE001 - enrichment must never break the cycle
                _LOGGER.debug("Enrichment refresh failed for %s", plant_id, exc_info=True)

        if daily_due:
            self._last_enrichment = now
        if retry_due:
            self._last_enrichment_retry = now
        self._api_health = self._collect_api_health()
        return changed or daily_due

    def _collect_api_health(self) -> dict[str, dict[str, Any]]:
        api = self._api
        if api is None:
            return {}

        def snapshot(provider, label: str, enabled: bool) -> dict[str, Any]:
            limiter = getattr(provider, "limiter", None)
            last_error = getattr(provider, "last_error", None)
            calls_today = getattr(limiter, "calls_today", None)
            daily_limit = getattr(limiter, "daily_limit", None)
            throttled = bool(
                enabled and daily_limit is not None and calls_today is not None
                and calls_today >= daily_limit
            )
            if not enabled:
                result = "not_configured"
            elif throttled:
                result = "throttled"
            elif last_error:
                result = "error"
            elif getattr(provider, "last_success", None):
                result = "success"
            else:
                result = "idle"
            return {
                "provider": label,
                "configured": enabled,
                "enabled": enabled,
                "ok": (not enabled) or last_error is None,
                "last_result": result,
                "partial_result": False,
                "last_attempt": getattr(limiter, "last_call_at", None),
                "last_success": getattr(provider, "last_success", None),
                "last_error": last_error if enabled else None,
                "calls_today": calls_today,
                "daily_limit": daily_limit,
                "throttled": throttled,
            }

        perenual_on = bool(getattr(api.perenual, "api_key", ""))
        trefle_on = bool(getattr(api.trefle, "api_key", "")) and getattr(api.trefle, "enabled", True)
        inat_on = getattr(api.inaturalist, "enabled", True)
        return {
            "perenual": snapshot(api.perenual, "Perenual", perenual_on),
            "trefle": snapshot(api.trefle, "Trefle", trefle_on),
            "inaturalist": snapshot(api.inaturalist, "iNaturalist", inat_on),
        }

    def _process_plant(
        self,
        plant_id: str,
        cfg: dict[str, Any],
        now,
        macro: _MacroReading,
        forecast: list[Any],
    ) -> eng.EngineResult:
        ldata = self._learned.data
        sdata = self._samples.data
        sensors = cfg.get("sensors", {})
        placement = cfg.get("placement", "indoor")

        # 1. Append this cycle's local readings.
        for signal, spec_entity, validation_spec in (
            ("moisture", sensors.get("moisture"), MOISTURE_SPEC),
            ("soil_temp", sensors.get("soil_temp"), SOIL_TEMP_SPEC),
            ("lux", sensors.get("lux"), LUX_SPEC),
        ):
            if not spec_entity:
                continue
            state = self.hass.states.get(spec_entity)
            value = _state_float(self.hass, spec_entity)
            source_ts = getattr(state, "last_updated", None) if state else None
            if (
                value is not None
                and source_ts is not None
                and not current_reading_stale(source_ts, now, validation_spec)
            ):
                # Preserve the source timestamp. Re-polling an unchanged entity
                # must not manufacture fresh telemetry. Timestamp dedupe then
                # prevents duplicate samples across coordinator cycles.
                sstore.append_reading(
                    sdata, f"plant:{plant_id}:{signal}", source_ts, value, now,
                    dedupe=True, max_per_series=self._max_samples,
                )
        battery = _state_raw(self.hass, sensors.get("battery"))
        ozone = _state_float(self.hass, self._ozone_entity)

        # 2. Day-boundary reduction + advancement.
        current_date = now.date().isoformat()
        last_reduced = ls.get_last_reduced(ldata, plant_id)
        if last_reduced is None:
            ls.set_last_reduced(ldata, plant_id, current_date)
        elif last_reduced != current_date:
            self._reduce_and_advance(plant_id, cfg, now, placement)
            ls.set_last_reduced(ldata, plant_id, current_date)

        # 3. Build inputs and compute.
        baseline = ls.active_baseline(ldata, plant_id, placement)
        dormancy = ls.get_dormancy(ldata, plant_id)
        dli3, dli7 = rt.recent_dli_means(ls.get_daily(ldata, plant_id))
        indoor_obs = self._indoor_observations(plant_id)

        # Reboot-safe run durations from persisted "since" stamps (updated after
        # compute below). These override the sample-walk timers so the long
        # "too-long" counters survive restarts and downtime.
        dry_dur = rt.timer_duration(ldata, plant_id, "dry", now)
        wet_dur = rt.timer_duration(ldata, plant_id, "wet", now)
        cold_dur = rt.timer_duration(ldata, plant_id, "cold", now)
        warm_dur = rt.timer_duration(ldata, plant_id, "warm", now)

        # Indoor light coefficient. Use the locked, PAR-calibrated k when present.
        # Otherwise (still calibrating, or a pre-PAR baseline whose k is withheld)
        # derive a PROVISIONAL k live from the accumulated observations, so light
        # reports within a day of having data instead of only after a full 14-day
        # calibration. Flagged provisional so it is not mistaken for the settled
        # value.
        _light_ready = (baseline or {}).get("light_ref") == "par"
        light_k_band = (baseline or {}).get("k_window_by_band") if _light_ready else None
        light_k_scalar = (baseline or {}).get("k_window_scalar") if _light_ready else None
        light_provisional = False
        if light_k_band is None and light_k_scalar is None and len(indoor_obs) >= PROVISIONAL_LIGHT_MIN_OBS:
            from .engine.calibration_math import WindowSample, window_factor_scalar
            prov = window_factor_scalar(
                [WindowSample(o.elevation_deg, o.indoor_lux, o.outdoor_lux) for o in indoor_obs]
            )
            if prov is not None:
                light_k_scalar = prov
                light_provisional = True

        # Diagnostic: when an indoor plant has no paired observations, say WHY —
        # the coordinator alone can tell a missing light sensor from a missing
        # radiation reference from a timing (pairing) gap. Makes a persistent
        # light: none explainable instead of silent.
        light_reason = None
        if placement != "outdoor" and not indoor_obs:
            have_lux = bool(sstore.raw_readings(sdata, f"plant:{plant_id}:lux"))
            have_par = bool(sstore.raw_readings(sdata, self._par_series_key))
            if not have_lux:
                light_reason = "no_light_sensor"
            elif not have_par:
                light_reason = "no_radiation_reference"
            else:
                light_reason = "no_daylight_overlap"

        # Advisory context: ambient humidity (optional sensor) + species light
        # preference (from enrichment). prefers_humidity is true for a moisture-
        # loving profile or a species whose enrichment indicates a humidity need.
        enrich = self._enrichment.get(plant_id) or {}
        profile = cfg.get("profile", "balanced")
        prefers_humidity = profile == "moisture_loving" or bool(enrich.get("prefers_humidity"))
        light_pref = enrich.get("light_preference")
        humidity_pct = _state_float(self.hass, sensors.get("humidity"))

        inputs = eng.EngineInputs(
            now=now,
            placement=placement,
            profile=profile,
            humidity_pct=humidity_pct,
            prefers_humidity=prefers_humidity,
            light_preference=light_pref,
            calibrating=rt.is_calibrating(ldata, plant_id, placement),
            m_max=(baseline or {}).get("m_max"),
            m_dry=(baseline or {}).get("m_dry"),
            drying_rate=(baseline or {}).get("drying_rate"),
            dli_target=(baseline or {}).get("dli_target"),
            dli_mean_3d=dli3,
            dli_mean_7d=dli7,
            # Only apply a learned k-window if it was calibrated against the PAR
            # reference. A pre-PAR (lux-era) baseline would give a k off by a large
            # constant, producing false obstruction/low-light; gate it to None so
            # indoor light reads "calibrating" until the plant is recalibrated.
            k_by_band=light_k_band,
            k_scalar=light_k_scalar,
            light_provisional=light_provisional,
            light_reason=light_reason,
            thermal_mean=(baseline or {}).get("thermal_mean"),
            diurnal_swing=(baseline or {}).get("diurnal_swing"),
            moisture_raw=sstore.raw_readings(sdata, f"plant:{plant_id}:moisture"),
            soil_temp_raw=sstore.raw_readings(sdata, f"plant:{plant_id}:soil_temp"),
            lux_raw=sstore.raw_readings(sdata, f"plant:{plant_id}:lux"),
            battery_pct=battery,
            par_raw=sstore.raw_readings(sdata, self._par_series_key),
            indoor_light_obs=indoor_obs,
            diffuse_irradiance=macro.diffuse_irradiance,
            global_irradiance=macro.global_irradiance,
            forecast=forecast,
            profile_rain_limit_mm=cfg.get("rain_limit_mm", 1.0),
            currently_dormant=dormancy.get("dormant", False),
            days_in_dormancy_state=dormancy.get("days_in_state", 999),
            par_slope_30d=rt.daily_field_slope(ls.get_daily(ldata, plant_id), "par_mean"),
            soil_temp_slope_30d=rt.daily_field_slope(ls.get_daily(ldata, plant_id), "soil_temp_mean"),
            dry_run_minutes=dry_dur,
            wet_run_minutes=wet_dur,
            cold_run_minutes=cold_dur,
            warm_run_minutes=warm_dur,
            ozone_ugm3=ozone,
            daylight_hours=_daylight_hours(self.hass),
            et0_next_24h_mm=(
                self._open_meteo_context.et0_next_24h_mm
                if placement == "outdoor"
                and self._open_meteo_context is not None
                and now - self._open_meteo_context.fetched_at <= timedelta(hours=2)
                else None
            ),
        )
        result = eng.compute(inputs)
        self._update_condition_timers(plant_id, result, now)
        return result

    def _update_condition_timers(self, plant_id: str, result, now) -> None:
        """Advance the persisted condition stamps from this cycle's flags."""
        ldata = self._learned.data
        m = result.moisture
        t = result.thermal
        if m is not None:
            rt.update_timer(ldata, plant_id, "dry", active=m.below_dry, now=now)
            rt.update_timer(ldata, plant_id, "wet", active=m.above_wet, now=now)
        if t is not None:
            rt.update_timer(ldata, plant_id, "cold", active=t.below_band, now=now)
            rt.update_timer(ldata, plant_id, "warm", active=t.above_band, now=now)

    def _reduce_and_advance(self, plant_id: str, cfg: dict[str, Any], now, placement: str) -> None:
        ldata = self._learned.data
        sdata = self._samples.data

        moisture = validate_series(sstore.raw_readings(sdata, f"plant:{plant_id}:moisture"), MOISTURE_SPEC)
        soil_temp = validate_series(sstore.raw_readings(sdata, f"plant:{plant_id}:soil_temp"), SOIL_TEMP_SPEC)
        par = validate_series(sstore.raw_readings(sdata, self._par_series_key), PAR_SPEC)
        window_obs = self._window_samples(plant_id)

        day_index = len(
            (ls.get_calibration(ldata, plant_id, placement) or {}).get("day_records", [])
        )
        record = rt.reduce_day(
            day_index=day_index, now=now, placement=placement,
            moisture=moisture, soil_temp=soil_temp, par=par, window_obs=window_obs,
            max_gap=eng.DEFAULT_LOCAL_GAP,
        )
        if rt.is_calibrating(ldata, plant_id, placement):
            rt.advance_calibration(
                ldata, plant_id, placement, record, cfg.get("profile", "balanced"),
                now_iso=now.isoformat(), custom_multiplier=cfg.get("custom_multiplier"),
            )
        else:
            rt.adapt_locked_baseline(
                ldata, plant_id, placement, record, now_iso=now.isoformat()
            )

        # Tier-2 daily aggregate for long-horizon trends.
        ls.append_daily(ldata, plant_id, {
            "date": (now.date().isoformat()),
            "daily_dli": record.daily_dli,
            "soil_temp_mean": record.daily_temp_mean,
            "par_mean": _mean_value(par),
        })

        # Dormancy once per day from the 30-day trends.
        daily = ls.get_daily(ldata, plant_id)
        rt.advance_dormancy(
            ldata, plant_id,
            par_slope_30d=rt.daily_field_slope(daily, "par_mean"),
            soil_temp_slope_30d=rt.daily_field_slope(daily, "soil_temp_mean"),
            now_iso=now.isoformat(),
        )

    def _window_samples(self, plant_id: str):
        from .engine.calibration_math import WindowSample

        obs = self._indoor_observations(plant_id)
        return [WindowSample(o.elevation_deg, o.indoor_lux, o.outdoor_lux) for o in obs]

    def _indoor_observations(self, plant_id: str):
        sdata = self._samples.data
        local_lux = validate_series(sstore.raw_readings(sdata, f"plant:{plant_id}:lux"), LUX_SPEC)
        # Pair against the reliably-populated, source-correct PAR series (W/m²),
        # NOT the fragile global:outdoor_lux. PAR is buffered from Open-Meteo under _par_series_key. The local indoor
        # lux reading is paired with the same outdoor PAR baseline, avoiding a
        # separate outdoor-lux stream that could leave indoor observations empty.
        # This previously left indoor
        # light unable to pair -> source: none. The k-window is a ratio, so the
        # outdoor unit only needs to be consistent between calibration and runtime
        # (both now use PAR).
        outdoor = [Sample(r.ts, r.value) for r in sstore.raw_readings(sdata, self._par_series_key)]
        elevation = [Sample(r.ts, r.value) for r in sstore.raw_readings(sdata, "global:elevation")]
        return rt.build_indoor_observations(local_lux, outdoor, elevation, eng.DEFAULT_MACRO_GAP)


def _mean_value(samples) -> float | None:
    vals = [s.value for s in samples if s.usable]
    return sum(vals) / len(vals) if vals else None
