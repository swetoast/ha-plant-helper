"""Replay two weeks of real Home Assistant recorder data through the engine.

The fixture holds the raw recorder history of two Zigbee soil sensors (Boras,
September 2026) and Astral sunrise/sunset for the same place. Real sensors
behave in ways synthetic tests miss: whole-percent readings, an ~8 point
day/night probe swing, slow soaks that take most of a day, and Home Assistant
restarts that briefly make everything unavailable. These tests pin the
behaviour the replay established, so none of the fixed false alerts can return:

- Soil Sensor (snake plant): two normal watering cycles, no alerts at all.
- Soil Sensor 2: two genuine dry spells, exactly two clean attention episodes.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

from domain.temporal import status as S
from domain.temporal.baseline import (
    BaselineSamples,
    cycle_baseline,
    daily_baseline,
    derive_band,
    monthly_baseline,
    update_samples,
)
from domain.temporal.daily import completed_days, update_ledger
from domain.temporal.daylight import DaylightWindow, parse_daily_windows, resolve_daylight
from domain.temporal.engine import EngineInputs, evaluate_plant
from domain.temporal.history import ObservationHistory
from domain.temporal.moisture import PROFILE_BANDS, watering_rise_threshold
from domain.temporal.observation import PlantObservation

TZ = ZoneInfo("Europe/Stockholm")
FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
DATA = json.loads((FIXTURES / "home_assistant" / "soil_sensor_history.json").read_text())
WINDOWS = tuple(
    DaylightWindow(datetime.fromisoformat(a), datetime.fromisoformat(b))
    for a, b in DATA["daylight_windows"]
)
STEP = timedelta(minutes=10)
_UNLEARNABLE = ("too_wet", "too_dry", "sensor_problem", "waiting_for_data")


def _series(name):
    out = []
    for stamp, state in DATA["series"].get(name, []):
        try:
            value = float(state)
        except ValueError:
            value = None
        out.append((datetime.fromisoformat(stamp), value))
    return out


@lru_cache(maxsize=None)  # deterministic: each replay runs once per test session
def replay(prefix, *, profile, light=True, learn=False):
    signals = {"m": "soil_moisture", "t": "temperature", "h": "humidity"}
    if light:
        signals["l"] = "illuminance"
    series = {k: _series(f"{prefix}_{v}") for k, v in signals.items()}
    index = {k: 0 for k in series}
    held = {k: None for k in series}
    now = max(s[0][0] for s in series.values())
    end = min(s[-1][0] for s in series.values())
    history, ledger, prior = ObservationHistory(), {}, None
    samples, learned = BaselineSamples(), {}
    band = PROFILE_BANDS[profile]
    timeline = []
    while now <= end:
        for k, s in series.items():  # Home Assistant holds a state until it changes
            while index[k] < len(s) and s[index[k]][0] <= now:
                held[k] = s[index[k]][1]
                index[k] += 1
        daylight = resolve_daylight(now, forecast_windows=WINDOWS, forecast_fetched_at=now)
        m, t, h, lx = held["m"], held["t"], held["h"], held.get("l")
        history.append(PlantObservation(
            now, m, t, m is not None, t is not None, light=lx, humidity=h,
            light_valid=lx is not None, humidity_valid=h is not None,
            is_daylight=daylight.is_daylight, daylight_source=daylight.source,
        ))
        ledger = update_ledger(ledger, history, now, TZ, placement="indoor", learned=learned)
        if learn:  # mirrors the runtime learning step
            days = completed_days(ledger, now, TZ)
            learnable = prior is None or prior.status not in _UNLEARNABLE
            high = learned["high"] if learned.get("complete") else band[1]
            new = update_samples(samples, history, now, band_high=high, learnable=learnable,
                                 watering_rise=watering_rise_threshold(days))
            day_key = now.astimezone(TZ).date().isoformat()
            if new.last_watering != samples.last_watering or learned.get("updated") != day_key:
                learned = dict(learned)
                learned.update(cycle_baseline(new))
                learned.update(daily_baseline(days))
                learned["monthly"] = monthly_baseline(learned.get("monthly"), days)
                derived = derive_band(new, history.confidence(now), now, band)
                if derived:
                    learned.update({"complete": True, "low": derived[0], "high": derived[1]})
                learned["updated"] = day_key
            samples = new
        result = evaluate_plant(EngineInputs(
            history, prior, ledger, now, TZ, profile=profile, placement="indoor",
            learned=learned,
        ))
        prior = result.moisture_state
        timeline.append((now, result))
        now += STEP
    return timeline, samples, learned


def attention_episodes(timeline):
    episodes, start = [], None
    for t, r in timeline:
        if r.needs_attention and start is None:
            start = (t, r.attention_reason)
        elif not r.needs_attention and start is not None:
            episodes.append((start[0], t, start[1]))
            start = None
    if start is not None:
        episodes.append((start[0], timeline[-1][0], start[1]))
    return episodes


def share(timeline, predicate):
    return sum(1 for _t, r in timeline if predicate(r)) / len(timeline)


def test_snake_plant_normal_watering_cycles_raise_no_alerts():
    timeline, _samples, _learned = replay("soil_sensor", profile="dry")
    assert attention_episodes(timeline) == []
    assert share(timeline, lambda r: r.health == S.HEALTH_GOOD) >= 0.9
    # Soil drying 3-4 points a day reads as drying, not as stalled wet soil.
    assert share(timeline, lambda r: r.status == S.DRYING) >= 0.6
    assert share(timeline, lambda r: r.status == S.TOO_WET) == 0


def test_restarts_never_look_like_a_sensor_problem():
    for prefix, light in (("soil_sensor", True), ("soil_sensor_2", False)):
        timeline, _s, _l = replay(prefix, profile="balanced", light=light)
        assert not any(r.status == S.SENSOR_PROBLEM for _t, r in timeline)


def test_second_plant_gets_exactly_its_two_genuine_dry_spells():
    timeline, _samples, _learned = replay("soil_sensor_2", profile="balanced", light=False)
    episodes = attention_episodes(timeline)
    assert [reason for _a, _b, reason in episodes] == ["soil_dry", "soil_dry"]
    # Each clears once that watering is recognised: never before the water went
    # in, and within a few hours even for the slow overnight soak on Sep 21.
    watered = [datetime(2026, 9, 14, 19, 0, tzinfo=TZ), datetime(2026, 9, 21, 23, 40, tzinfo=TZ)]
    for (_a, cleared, _r), began in zip(episodes, watered):
        assert began <= cleared <= began + timedelta(hours=3)
    # 65-80 % air humidity is healthy for houseplants and must not be a concern.
    assert not any("humid" in (r.health_summary or "") for _t, r in timeline)


def test_learning_sees_only_the_real_waterings():
    _t, snake, snake_learned = replay("soil_sensor", profile="dry", learn=True)
    assert snake.troughs == (43.0, 33.0) and snake.peaks == (62.0,)
    assert snake.rises == (19.0,)
    assert abs(snake_learned["light_effective"] - 3571.0) < 200.0
    _t, second, _l = replay("soil_sensor_2", profile="balanced", light=False, learn=True)
    assert second.troughs == (0.0, 11.0)
    assert len(second.peaks) == 1 and 65.0 <= second.peaks[0] <= 80.0


def test_learning_does_not_change_the_verdicts_on_this_data():
    for prefix, profile, light in (("soil_sensor", "dry", True), ("soil_sensor_2", "balanced", False)):
        plain, _s, _l = replay(prefix, profile=profile, light=light)
        learned, _s, _l = replay(prefix, profile=profile, light=light, learn=True)
        assert attention_episodes(plain) == attention_episodes(learned)


def test_real_indoor_forecast_gives_the_local_daylight_window():
    raw = json.loads((FIXTURES / "open_meteo" / "boras_indoor_daylight.json").read_text())
    windows = parse_daily_windows(raw["daily"])
    first = windows[0]
    assert first.sunrise.astimezone(TZ).strftime("%H:%M") == "06:59"
    assert first.sunset.astimezone(TZ).strftime("%H:%M") == "18:59"
    fetched = datetime(2026, 9, 25, 12, 0, tzinfo=TZ)
    for hour, expected in ((5, False), (12, True), (19, False)):
        state = resolve_daylight(
            datetime(2026, 9, 25, hour, 0, tzinfo=TZ),
            forecast_windows=windows, forecast_fetched_at=fetched,
        )
        assert state.is_daylight is expected and state.source == "forecast"
