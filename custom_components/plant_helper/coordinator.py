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
from .engine.accumulator import Sample
from .engine.validation import (
    LUX_SPEC,
    MOISTURE_SPEC,
    PAR_SPEC,
    SOIL_TEMP_SPEC,
    validate_series,
)
from .sources import forecast as forecast_src
from .sources import smhi as smhi_src

_LOGGER = logging.getLogger(__name__)

UPDATE_INTERVAL = timedelta(minutes=10)
ENRICHMENT_INTERVAL = timedelta(hours=24)
SUN_ENTITY = "sun.sun"


def _state_float(hass: HomeAssistant, entity_id: str | None) -> float | None:
    if not entity_id:
        return None
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable", None):
        return None
    try:
        return float(state.state)
    except (TypeError, ValueError):
        return None


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
    try:
        return float(state.attributes.get("elevation"))
    except (TypeError, ValueError):
        return None


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
        strang_entities: dict[str, str] | None,
        forecast_entity: str | None,
        ozone_entity: str | None = None,
        api: Any = None,
    ) -> None:
        super().__init__(
            hass, _LOGGER, name="plant_helper", update_interval=UPDATE_INTERVAL
        )
        self._learned = learned
        self._samples = samples
        self._plants = plants
        self._strang_entities = strang_entities
        self._forecast_entity = forecast_entity
        self._ozone_entity = ozone_entity
        self._api = api
        self._enrichment: dict[str, dict[str, Any]] = {
            pid: cfg["enrichment"]
            for pid, cfg in plants.items()
            if cfg.get("enrichment")
        }
        self._api_health: dict[str, dict[str, Any]] = {}
        self._last_enrichment = None

    @property
    def enrichment(self) -> dict[str, dict[str, Any]]:
        return self._enrichment

    @property
    def api_health(self) -> dict[str, dict[str, Any]]:
        return self._api_health

    async def _async_update_data(self) -> dict[str, eng.EngineResult]:
        now = dt_util.now()
        sdata = self._samples.data

        # --- shared macro sources -----------------------------------------
        macro = await smhi_src.read_macro(self.hass, self._strang_entities)
        forecast = (
            await forecast_src.async_fetch_forecast(self.hass, self._forecast_entity, now)
            if self._forecast_entity
            else []
        )
        elevation = _sun_elevation(self.hass)

        par_sample = smhi_src.macro_par_sample(macro, now)
        if par_sample.usable:
            sstore.append_reading(
                sdata, "global:par", par_sample.ts, par_sample.value, now,
                dedupe=True,
            )
        if macro.outdoor_lux is not None and not macro.stale:
            ts = macro.selected_data_time or now
            sstore.append_reading(sdata, "global:outdoor_lux", ts, macro.outdoor_lux, now, dedupe=True)
        if elevation is not None:
            sstore.append_reading(sdata, "global:elevation", now, elevation, now)

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
        self.hass.async_create_task(self._enrich_and_notify(now))
        return results

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
        first_run = self._last_enrichment is None
        if not first_run and (now - self._last_enrichment) < ENRICHMENT_INTERVAL:
            return False
        self._last_enrichment = now

        from . import enrichment as en

        for plant_id, cfg in self._plants.items():
            species = cfg.get("species")
            if not species:
                continue
            try:
                # Force a real provider lookup on the first cycle after setup (and
                # after a plant is added, which reloads) so the plant is actually
                # resolved and the API diagnostics reflect it; cache-read on the
                # throttled daily cycles after that.
                result = await self._api.fetch_plant(species, force_fetch=first_run)
                if result and getattr(result, "found", False) and result.data:
                    data = dict(result.data)
                    data.setdefault("provider", getattr(result, "provider", None))
                    self._enrichment[plant_id] = en.summarize_enrichment(data)
            except Exception:  # noqa: BLE001 - enrichment must never break the cycle
                _LOGGER.debug("Enrichment refresh failed for %s", plant_id, exc_info=True)
        self._api_health = self._collect_api_health()
        return True

    def _collect_api_health(self) -> dict[str, dict[str, Any]]:
        api = self._api
        if api is None:
            return {}

        def snapshot(provider, label: str, enabled: bool) -> dict[str, Any]:
            limiter = getattr(provider, "limiter", None)
            last_error = getattr(provider, "last_error", None)
            return {
                "provider": label,
                # A provider with no key/disabled isn't a problem, just unused.
                "ok": (not enabled) or last_error is None,
                "enabled": enabled,
                "last_success": getattr(provider, "last_success", None),
                "last_error": last_error if enabled else None,
                "calls_today": getattr(limiter, "calls_today", None),
                "daily_limit": getattr(limiter, "daily_limit", None),
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
        macro: smhi_src.MacroReading,
        forecast: list[Any],
    ) -> eng.EngineResult:
        ldata = self._learned.data
        sdata = self._samples.data
        sensors = cfg.get("sensors", {})
        placement = cfg.get("placement", "indoor")

        # 1. Append this cycle's local readings.
        for signal, spec_entity in (
            ("moisture", sensors.get("moisture")),
            ("soil_temp", sensors.get("soil_temp")),
            ("lux", sensors.get("lux")),
        ):
            value = _state_float(self.hass, spec_entity)
            if value is not None:
                sstore.append_reading(sdata, f"plant:{plant_id}:{signal}", now, value, now)
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

        inputs = eng.EngineInputs(
            now=now,
            placement=placement,
            profile=cfg.get("profile", "balanced"),
            calibrating=rt.is_calibrating(ldata, plant_id, placement),
            m_max=(baseline or {}).get("m_max"),
            m_dry=(baseline or {}).get("m_dry"),
            drying_rate=(baseline or {}).get("drying_rate"),
            dli_target=(baseline or {}).get("dli_target"),
            dli_mean_3d=dli3,
            dli_mean_7d=dli7,
            k_by_band=(baseline or {}).get("k_window_by_band"),
            k_scalar=(baseline or {}).get("k_window_scalar"),
            thermal_mean=(baseline or {}).get("thermal_mean"),
            diurnal_swing=(baseline or {}).get("diurnal_swing"),
            moisture_raw=sstore.raw_readings(sdata, f"plant:{plant_id}:moisture"),
            soil_temp_raw=sstore.raw_readings(sdata, f"plant:{plant_id}:soil_temp"),
            lux_raw=sstore.raw_readings(sdata, f"plant:{plant_id}:lux"),
            battery_pct=battery,
            par_raw=sstore.raw_readings(sdata, "global:par"),
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
        par = validate_series(sstore.raw_readings(sdata, "global:par"), PAR_SPEC)
        window_obs = self._window_samples(plant_id)

        day_index = len(
            (ls.get_calibration(ldata, plant_id, placement) or {}).get("day_records", [])
        )
        record = rt.reduce_day(
            day_index=day_index, now=now, placement=placement,
            moisture=moisture, soil_temp=soil_temp, par=par, window_obs=window_obs,
            max_gap=eng.DEFAULT_LOCAL_GAP,
        )
        rt.advance_calibration(
            ldata, plant_id, placement, record, cfg.get("profile", "balanced"),
            now_iso=now.isoformat(), custom_multiplier=cfg.get("custom_multiplier"),
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
        outdoor = [Sample(r.ts, r.value) for r in sstore.raw_readings(sdata, "global:outdoor_lux")]
        elevation = [Sample(r.ts, r.value) for r in sstore.raw_readings(sdata, "global:elevation")]
        return rt.build_indoor_observations(local_lux, outdoor, elevation, eng.DEFAULT_MACRO_GAP)


def _mean_value(samples) -> float | None:
    vals = [s.value for s in samples if s.usable]
    return sum(vals) / len(vals) if vals else None
