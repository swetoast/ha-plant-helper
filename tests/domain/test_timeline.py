"""Roadmap Phase 7: time-fast-forward timeline scenarios.

A small simulator advances a clock and feeds the same pipeline the Home
Assistant runtime uses: record an observation tagged with the resolved daylight
state, update the daily ledger, run the combined engine, carry the moisture
state forward. Each numbered test is one required roadmap scenario; the tests at
the end cover the appendix mechanics (dormancy, partial watering, learned
slow drying, stuck sensor).
"""
from __future__ import annotations

import inspect
import math
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from domain.physical import normalize_battery_state
from domain.temporal import status as S
from domain.temporal.daily import update_ledger
from domain.temporal.daylight import DaylightWindow, resolve_daylight
from domain.temporal.engine import EngineInputs, evaluate_plant
from domain.temporal.history import ObservationHistory
from domain.temporal.observation import PlantObservation
from domain.temporal.store import restore_daily, restore_store, serialize_store

TZ = ZoneInfo("Europe/Stockholm")
START = datetime(2026, 6, 1, 0, 0, tzinfo=TZ)


def windows_around(start, days=80):
    """Simple solar windows: sunrise 06:00, sunset 20:00 local, every day."""
    out = []
    for offset in range(-2, days):
        day = (start + timedelta(days=offset)).date()
        out.append(DaylightWindow(
            datetime.combine(day, time(6), TZ), datetime.combine(day, time(20), TZ)
        ))
    return tuple(out)


class Sim:
    def __init__(self, *, placement="indoor", profile="balanced", start=START,
                 learned=None, radiation=None, forecast=True, astral=False):
        self.history = ObservationHistory()
        self.ledger = {}
        self.prior = None
        self.now = start
        self.placement, self.profile = placement, profile
        self.learned = learned or {}
        self.radiation = radiation or {}
        self.windows = windows_around(start)
        self.fetched_at = start if forecast else None
        self.forecast_stale = False
        # A live forecast is refetched every few minutes, as the runtime does.
        self.live = forecast
        self.astral = astral
        self.moisture = 45.0
        self.temperature = 21.0
        self.humidity = 50.0
        self.light = None
        self.result = None
        self.daylight = None
        # Real rooms breathe: a gentle day/night swing on temperature and
        # humidity. A frozen device is simulated by switching this off.
        self.diurnal = True

    def daylight_state(self):
        return resolve_daylight(
            self.now,
            forecast_windows=self.windows if self.fetched_at else (),
            forecast_fetched_at=self.fetched_at,
            forecast_stale=self.forecast_stale,
            astral=(lambda _now: self.windows) if self.astral else None,
        )

    def default_light(self):
        return 800.0 if self.daylight_state().is_daylight else 0.0

    def step(self):
        if self.live:
            self.fetched_at = self.now
        self.daylight = self.daylight_state()
        light = self.default_light() if self.light is None else self.light
        m = self.moisture
        swing = math.sin(2 * math.pi * self.now.astimezone(TZ).hour / 24.0)
        temperature, humidity = self.temperature, self.humidity
        if self.diurnal and temperature is not None:
            temperature += 1.5 * swing
        if self.diurnal and humidity is not None:
            humidity -= 5.0 * swing
        self.history.append(PlantObservation(
            observed_at=self.now,
            moisture=m, soil_temperature=temperature,
            moisture_valid=m is not None,
            soil_temperature_valid=temperature is not None,
            light=light, humidity=humidity,
            light_valid=light is not None, humidity_valid=humidity is not None,
            is_daylight=self.daylight.is_daylight, daylight_source=self.daylight.source,
        ))
        self.ledger = update_ledger(
            self.ledger, self.history, self.now, TZ, placement=self.placement,
            radiation_for_day=lambda day: self.radiation.get(day.isoformat(),
                                                             self.radiation.get("*")),
            learned=self.learned,
        )
        self.result = evaluate_plant(EngineInputs(
            history=self.history, prior=self.prior, ledger=self.ledger,
            now=self.now, tz=TZ, profile=self.profile, placement=self.placement,
            learned=self.learned,
        ))
        self.prior = self.result.moisture_state
        return self.result

    def run(self, hours, *, step_minutes=10, each=None):
        end = self.now + timedelta(hours=hours)
        seen = []
        while self.now < end:
            if each is not None:
                each(self)
            result = self.step()
            if not seen or seen[-1] != result.status:
                seen.append(result.status)
            self.now += timedelta(minutes=step_minutes)
        return seen


def hours_since(sim, moment):
    return (sim.now - moment).total_seconds() / 3600.0


# 1
def test_01_normal_watering_and_drying():
    sim = Sim()
    sim.moisture = 30.0
    sim.run(24)
    watered = sim.now
    sim.moisture = 60.0
    seen = sim.run(1)
    assert S.RECENTLY_WATERED in seen

    def dry(s):
        s.moisture = 60.0 - 0.6 * hours_since(s, watered)

    sim.run(40, each=dry)
    assert sim.result.status in (S.DRYING, S.NORMAL)
    assert sim.result.health == S.HEALTH_GOOD and not sim.result.needs_attention


# 2
def test_02_high_moisture_immediately_after_watering():
    sim = Sim(profile="dry")  # band 15-45: 47 % is elevated
    sim.moisture = 47.0
    sim.run(1)
    assert sim.result.status == S.WET
    assert sim.result.health == S.HEALTH_GOOD and not sim.result.needs_attention


# 3
def test_03_moisture_falling_normally():
    sim = Sim()
    start = sim.now

    def fall(s):
        s.moisture = 75.0 - 1.0 * hours_since(s, start)

    sim.run(12, each=fall)
    assert sim.result.status == S.DRYING
    assert sim.result.health == S.HEALTH_GOOD and not sim.result.needs_attention


# 4
def test_04_persistently_wet_soil():
    sim = Sim()
    sim.moisture = 70.0
    seen = sim.run(24 * 6)
    assert seen.index(S.WET) < seen.index(S.STAYING_WET) < seen.index(S.TOO_WET)
    assert sim.result.status == S.TOO_WET
    assert sim.result.health == S.HEALTH_WATCH
    assert sim.result.needs_attention and sim.result.attention_reason == "persistently_wet"


# 5
def test_05_repeated_watering_before_sufficient_drying():
    sim = Sim()
    sim.moisture = 68.0
    sim.run(2)
    first = sim.now
    for _ in range(6):  # topped up every 12 h; never dries back into range
        sim.moisture = 68.0
        sim.run(1)
        sim.moisture = 76.0
        sim.run(11)
    assert sim.result.status in (S.STAYING_WET, S.TOO_WET)
    # The wet run keeps its original start; top-ups never reset the clock.
    assert sim.result.since <= first + timedelta(hours=2)


# 6
def test_06_approaching_dry_and_needs_water():
    sim = Sim()
    start = sim.now

    def fall(s):
        s.moisture = 40.0 - 1.0 * hours_since(s, start)

    seen = sim.run(20, each=fall)
    assert S.APPROACHING_DRY in seen and seen[-1] == S.NEEDS_WATER
    assert sim.result.needs_attention and sim.result.attention_reason == "soil_dry"
    assert sim.result.health == S.HEALTH_WATCH


# 7
def test_07_prolonged_dryness():
    sim = Sim()
    sim.moisture = 15.0
    sim.run(24 * 3)
    assert sim.result.status == S.TOO_DRY
    assert sim.result.health == S.HEALTH_STRESSED
    assert sim.result.attention_reason == "persistently_dry"


# 8
def test_08_one_cloudy_day():
    sim = Sim(radiation={"*": 250.0})
    sim.run(24 * 2)
    sim.light = None
    cloudy_day = sim.now.date().isoformat()
    sim.radiation[cloudy_day] = 30.0

    def dim_by_day(s):
        s.light = 100.0 if s.daylight_state().is_daylight else 0.0

    sim.run(24, each=dim_by_day)
    sim.light = None
    sim.run(12)
    assert sim.ledger[cloudy_day].light.classification == "overcast_day"
    assert sim.result.status != S.INSUFFICIENT_LIGHT
    assert not sim.result.needs_attention and sim.result.health == S.HEALTH_GOOD


# 9
def test_09_three_consecutive_low_light_days():
    sim = Sim()

    def dim(s):
        s.light = 100.0 if s.daylight_state().is_daylight else 0.0

    sim.run(24 * 3 + 12, each=dim)
    assert sim.result.status == S.INSUFFICIENT_LIGHT
    assert sim.result.attention_reason == "several_days_insufficient_light"
    assert sim.result.health == S.HEALTH_WATCH
    assert "3 days" in sim.result.summary


# 10
def test_10_bright_outdoor_radiation_but_shaded_indoor_spot():
    sim = Sim(radiation={"*": 400.0})

    def dim(s):
        s.light = 150.0 if s.daylight_state().is_daylight else 0.0

    sim.run(24 * 2 + 12, each=dim)
    assert sim.result.status == S.INSUFFICIENT_LIGHT
    assert sim.result.reason == "likely_shaded"
    assert not sim.result.needs_attention  # two days: evidence, not yet action


# 11
def test_11_sustained_nighttime_grow_light():
    sim = Sim()

    def grow(s):
        local = s.now.astimezone(TZ)
        if s.daylight_state().is_daylight:
            s.light = 150.0  # 150 lx x 14 h = 2100 lx-h: low on its own
        else:
            s.light = 5000.0 if 21 <= local.hour < 23 else 0.0

    sim.run(24 + 6, each=grow)
    day = START.date().isoformat()
    light = sim.ledger[day].light
    assert abs(light.artificial_light_exposure - 10000.0) < 1.0
    assert abs(light.effective_light_exposure - (2100.0 + 6000.0)) < 1.0
    assert light.classification == "supplemental_light_detected"


# 12
def test_12_five_minute_nighttime_room_light():
    sim = Sim()
    sim.run(22)  # to 22:00, night
    sim.light = 500.0
    sim.run(5 / 60, step_minutes=5)
    sim.light = 0.0
    sim.run(3)
    assert sim.ledger[START.date().isoformat()].light.artificial_light_exposure == 0.0


# 13
def test_13_grow_light_session_crossing_midnight():
    sim = Sim()
    sim.run(23)  # 23:00 on day one
    sim.light = 4000.0
    sim.run(2)  # 23:00 -> 01:00
    sim.light = None
    sim.run(24)
    day_one = sim.ledger[START.date().isoformat()].light
    day_two = sim.ledger[(START + timedelta(days=1)).date().isoformat()].light
    assert abs(day_one.artificial_light_exposure - 8000.0) < 1.0
    assert day_two.artificial_light_exposure == 0.0


# 14
def test_14_short_cold_excursion():
    sim = Sim()
    sim.run(6)
    sim.temperature = 15.0
    sim.run(1)
    assert sim.result.temperature_context == "low"
    assert sim.result.status not in (S.TOO_COLD,)
    assert sim.result.health == S.HEALTH_GOOD and not sim.result.needs_attention
    sim.temperature = 21.0
    sim.run(4)
    assert sim.result.health == S.HEALTH_GOOD


# 15
def test_15_prolonged_cold_and_wet_condition():
    sim = Sim()
    sim.moisture = 70.0
    sim.temperature = 15.0
    sim.run(14)
    assert sim.result.condition == "cold_wet_condition"
    assert sim.result.status == S.TOO_COLD  # outranks plain wet
    assert sim.result.health == S.HEALTH_WATCH
    assert "cool" in sim.result.summary or "cold" in sim.result.summary


# 16
def test_16_warm_dry_accelerated_drying():
    sim = Sim()
    sim.temperature, sim.humidity = 29.0, 25.0
    start = sim.now

    def fall(s):
        s.moisture = 62.0 - 1.2 * hours_since(s, start)

    sim.run(10, each=fall)
    assert sim.result.status == S.DRYING
    assert sim.result.condition == "accelerated_drying"
    assert "warm" in sim.result.summary


# 17
def test_17_sensor_unavailable_during_active_cycle():
    sim = Sim()
    sim.moisture = 60.0
    sim.run(6)
    sim.moisture = None
    sim.run(3)
    assert sim.result.status != S.SENSOR_PROBLEM  # short outage: keep last reading
    sim.run(4)
    assert sim.result.status == S.SENSOR_PROBLEM
    assert sim.result.health == S.HEALTH_UNKNOWN
    assert sim.result.attention_reason == "sensor_problem"


# 18
def test_18_restart_during_a_watering_cycle():
    sim = Sim()
    sim.moisture = 70.0
    sim.run(30)
    before = sim.result
    payload = serialize_store(
        {"p": sim.history}, {"p": sim.prior}, {"p": sim.ledger}
    )
    histories, states = restore_store(payload, sim.now)
    ledgers = restore_daily(payload)
    sim.history, sim.prior, sim.ledger = histories["p"], states["p"], ledgers["p"]
    after = sim.step()
    assert after.status == before.status and after.since == before.since
    assert set(ledgers["p"]) == set(sim.ledger)


# 19
def test_19_forecast_failure_with_valid_cache():
    sim = Sim()
    sim.live = False
    sim.now = START + timedelta(hours=30)  # 06:00 day two + 24 h cache age
    sim.forecast_stale = True
    state = sim.daylight_state()
    assert state.source == "cache" and state.is_daylight is True


# 20
def test_20_forecast_failure_using_astral_fallback():
    sim = Sim(forecast=True, astral=True)
    sim.live = False
    sim.now = START + timedelta(days=3, hours=12)  # cache is 84 h old
    state = sim.daylight_state()
    assert state.source == "astral" and state.is_daylight is True


# 21
def test_21_complete_daylight_uncertainty():
    sim = Sim(forecast=False, astral=False)
    sim.light = 50.0  # dim, but no alert may fire without daylight bounds
    sim.run(24 * 4)
    assert sim.daylight.is_daylight is None and sim.daylight.source == "unknown"
    assert sim.result.status != S.INSUFFICIENT_LIGHT
    assert not sim.result.needs_attention


# 22
def test_22_air_quality_failure_leaves_daylight_unaffected():
    # Daylight has no air-quality input at all: an AQ outage cannot touch it.
    params = inspect.signature(resolve_daylight).parameters
    assert not any("air" in name for name in params)
    sim = Sim()
    sim.now = START + timedelta(hours=12)
    assert sim.daylight_state().is_daylight is True


# 23
def test_23_two_plants_with_the_same_name_keep_independent_histories():
    wet, dry = Sim(), Sim()
    wet.moisture, dry.moisture = 70.0, 15.0
    wet.run(6)
    dry.run(6)
    assert wet.history is not dry.history
    assert wet.result.status == S.WET and dry.result.status == S.NEEDS_WATER


# 24
def test_24_zero_moisture_is_a_real_reading():
    sim = Sim()
    sim.moisture = 0.0
    sim.run(1)
    assert sim.result.status == S.NEEDS_WATER
    assert sim.result.health != S.HEALTH_UNKNOWN


# 25
def test_25_categorical_and_numeric_battery_sources_unaffected():
    assert normalize_battery_state("middle") == "middle"
    assert normalize_battery_state("55") == 55.0
    sim = Sim()
    sim.run(2)
    assert sim.result.status == S.NORMAL


# ------------------------------------------------- appendix mechanics

def test_dormancy_from_low_light_and_cooling_relaxes_needs_water():
    sim = Sim()

    def winter(s):
        s.light = 250.0 if s.daylight_state().is_daylight else 0.0  # 3500 lx-h
        s.temperature = 21.0 if hours_since(s, START) < 24 * 16 else 18.5

    sim.moisture = 40.0
    sim.run(24 * 24, step_minutes=30, each=winter)
    assert sim.result.dormant is True
    assert sim.result.reason == "seasonal_dormancy"
    sim.moisture = 22.0  # below the 25 % profile low, above the dormant 18.75 %
    sim.step()
    assert sim.result.status != S.NEEDS_WATER


def test_partial_watering_against_the_learned_peak():
    sim = Sim(learned={"peak": 75.0})
    sim.moisture = 30.0
    sim.run(4)
    sim.moisture = 50.0  # rises, but far short of the usual 75 % peak
    sim.run(8)
    assert sim.result.status == S.PARTIAL_WATERING
    assert not sim.result.needs_attention


def test_learned_slope_flags_unusually_slow_drying():
    sim = Sim(learned={"slope": 0.5})
    sim.moisture = 70.0
    sim.run(30)
    assert "slowly than usual" in sim.result.summary
    assert sim.result.health == S.HEALTH_WATCH


def test_stuck_moisture_sensor_is_a_sensor_problem():
    sim = Sim()
    sim.diurnal = False  # a frozen device repeats every value
    sim.moisture, sim.light = 44.0, 300.0
    sim.run(24 * 6, step_minutes=30)
    assert sim.result.status == S.SENSOR_PROBLEM
    assert "same value" in sim.result.summary
