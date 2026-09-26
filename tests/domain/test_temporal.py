from __future__ import annotations

from datetime import datetime, timedelta, timezone

from domain.temporal.history import ObservationHistory
from domain.temporal.moisture import (
    WET_DURATION_LIMIT_HOURS,
    CRITICAL_MOISTURE,
    TemporalMoistureState,
    evaluate_moisture,
)
from domain.temporal.observation import PlantObservation
from domain.temporal import status as S

NOW = datetime(2026, 1, 15, 12, 0, tzinfo=timezone.utc)


def obs(minutes_ago, moisture, *, valid=True, soil_temp=None, light=None, humidity=None):
    return PlantObservation(
        observed_at=NOW - timedelta(minutes=minutes_ago),
        moisture=moisture,
        soil_temperature=soil_temp,
        moisture_valid=valid,
        soil_temperature_valid=soil_temp is not None,
        light=light,
        humidity=humidity,
        light_valid=light is not None,
        humidity_valid=humidity is not None,
    )


def history(samples):
    h = ObservationHistory()
    for o in samples:
        h.append(o)
    return h


def decide(samples, *, profile="balanced", prior=None, env=None, now=NOW):
    return evaluate_moisture(history(samples), prior, now, profile, env)


# ---------------------------------------------------------------- P0: history


def test_dedup_skips_tiny_unchanged_samples_but_keeps_real_moves():
    h = ObservationHistory()
    assert h.append(obs(20, 40.0)) is True
    assert h.append(obs(16, 40.2)) is False  # <0.5 delta, <10 min, same validity
    assert h.append(obs(15, 41.0)) is True  # >=0.5 delta
    assert len(h) == 2


def test_validity_transition_is_always_recorded():
    h = ObservationHistory()
    h.append(obs(5, 40.0))
    assert h.append(obs(2, None, valid=False)) is True


def test_retention_prunes_observations_beyond_the_window():
    h = ObservationHistory(retention_hours=48.0)
    h.append(obs(60 * 60, 30.0))  # 60 h ago
    h.append(obs(1, 31.0))  # now
    assert len(h) == 1  # the 60 h sample was pruned


def test_valid_zero_moisture_is_a_real_reading_not_missing():
    h = history([obs(2, 0.0)])
    latest = h.latest_valid()
    assert latest is not None and latest.moisture == 0.0


def test_invalid_readings_are_excluded_from_valid_and_latest():
    h = history([obs(30, 42.0), obs(1, None, valid=False)])
    assert [o.moisture for o in h.valid()] == [42.0]
    assert h.latest_valid().moisture == 42.0


def test_two_plants_with_the_same_name_keep_separate_histories():
    a = history([obs(2, 20.0)])
    b = history([obs(2, 70.0)])
    assert a.latest_valid().moisture == 20.0
    assert b.latest_valid().moisture == 70.0


# ------------------------------------------------- P1: single-sample safety


def test_single_elevated_reading_is_wet_not_too_wet():
    # Dry profile band tops out at 45; a lone 47% used to read too_wet.
    decision, state = decide([obs(0, 47.0)], profile="dry")
    assert decision.status == S.WET
    assert decision.health == S.HEALTH_GOOD
    assert decision.needs_attention is False
    assert state.status == S.WET


def test_probable_watering_reads_recently_watered():
    decision, _ = decide([obs(40, 39.0), obs(0, 47.0)], profile="dry")
    assert decision.status == S.RECENTLY_WATERED
    assert decision.needs_attention is False


def test_small_fluctuations_create_no_watering_event():
    decision, _ = decide(
        [obs(60, 44.0), obs(40, 45.0), obs(20, 44.0), obs(0, 46.0)],
        profile="balanced",
    )
    assert decision.status == S.NORMAL


# ------------------------------------------------- P1: wet-side escalation


def _dense_wet_history(hours, level, step_minutes=60):
    samples = []
    minutes = int(hours * 60)
    m = minutes
    while m >= 0:
        samples.append(obs(m, level))
        m -= step_minutes
    return history(samples)


def test_sustained_wet_with_confidence_becomes_too_wet():
    h = _dense_wet_history(hours=80, level=70.0)  # balanced high = 65
    prior = TemporalMoistureState(
        S.WET, NOW - timedelta(hours=80), None, 70.0, 0.0, None, "high"
    )
    decision, state = evaluate_moisture(h, prior, NOW, "balanced", None)
    assert decision.status == S.TOO_WET
    assert decision.health == S.HEALTH_WATCH
    assert decision.needs_attention is True


def test_wet_run_start_survives_observation_pruning():
    # The retained observations only span the last day (so on their own the run
    # would read as staying_wet, not too_wet), but the persisted run start is
    # 80 h old. Escalation must use the persisted start, not just the window.
    samples = []
    m = 24 * 60
    while m >= 0:
        samples.append(obs(m, 70.0))
        m -= 120
    h = history(samples)
    assert h.duration_above(65.0, NOW) < timedelta(hours=WET_DURATION_LIMIT_HOURS)
    prior = TemporalMoistureState(
        S.STAYING_WET, NOW - timedelta(hours=80), None, 70.0, 0.0, None, "high"
    )
    decision, _ = evaluate_moisture(h, prior, NOW, "balanced", None)
    assert decision.status == S.TOO_WET


def test_elevated_but_falling_reads_drying_even_past_the_limit():
    # A clear downward slope beats the wet-duration escalation.
    samples = [obs(300, 95.0), obs(180, 85.0), obs(60, 74.0), obs(0, 68.0)]
    prior = TemporalMoistureState(
        S.WET, NOW - timedelta(hours=80), None, 95.0, -4.0, None, "high"
    )
    decision, _ = evaluate_moisture(history(samples), prior, NOW, "balanced", None)
    assert decision.status == S.DRYING
    assert decision.needs_attention is False


# ------------------------------------------------- P1: dry-side and rain


def test_below_band_reads_needs_water_with_attention():
    decision, _ = decide([obs(0, 18.0)], profile="balanced")
    assert decision.status == S.NEEDS_WATER
    assert decision.needs_attention is True


def test_outdoor_rain_pauses_watering_when_not_critical():
    decision, _ = decide(
        [obs(0, 18.0)],
        profile="balanced",
        env={"placement": "outdoor", "rain_suppression": True},
    )
    assert decision.status == S.WATERING_PAUSED
    assert decision.needs_attention is False
    assert decision.reason == "rain_expected"


def test_critically_dry_overrides_rain_suppression():
    decision, _ = decide(
        [obs(0, CRITICAL_MOISTURE - 1.0)],
        profile="balanced",
        env={"placement": "outdoor", "rain_suppression": True},
    )
    assert decision.status == S.NEEDS_WATER
    assert decision.needs_attention is True


def test_sustained_dry_with_confidence_becomes_too_dry():
    samples = []
    m = 60 * 60  # 60 h ago
    while m >= 0:
        samples.append(obs(m, 10.0))
        m -= 60
    prior = TemporalMoistureState(
        S.NEEDS_WATER, NOW - timedelta(hours=60), None, 10.0, 0.0, None, "high"
    )
    decision, _ = evaluate_moisture(history(samples), prior, NOW, "balanced", None)
    assert decision.status == S.TOO_DRY
    assert decision.needs_attention is True


# ------------------------------------------------- P1: comfortable and empty


def test_in_band_reads_normal():
    decision, _ = decide([obs(0, 45.0)], profile="balanced")
    assert decision.status == S.NORMAL
    assert decision.health == S.HEALTH_GOOD


def test_no_valid_data_waits():
    decision, state = decide([obs(0, None, valid=False)])
    assert decision.status == S.WAITING_FOR_DATA
    assert decision.needs_attention is False
    assert state.status == S.WAITING_FOR_DATA


def test_status_precedence_picks_the_most_urgent():
    assert S.worst_of([S.NORMAL, S.NEEDS_WATER, S.WET]) == S.NEEDS_WATER
    # Roadmap Phase 5 order: recently_watered outranks wet.
    assert S.worst_of([S.WET, S.RECENTLY_WATERED]) == S.RECENTLY_WATERED
    assert S.worst_of([S.WET, S.TOO_COLD, S.INSUFFICIENT_LIGHT]) == S.TOO_COLD
    assert S.worst_of([S.DRYING, S.TOO_COLD]) == S.DRYING
    assert S.worst_of([S.NEEDS_WATER, S.SENSOR_PROBLEM]) == S.SENSOR_PROBLEM


# ------------------------------------------------- P2: persistence / restart

from domain.temporal.store import STORE_VERSION, restore_store, serialize_store


def test_store_roundtrip_preserves_history_and_state():
    hist = history([obs(120, 30.0), obs(60, 42.0), obs(0, 44.0)])
    state = TemporalMoistureState(
        S.WET, NOW - timedelta(hours=10), NOW - timedelta(hours=10), 70.0, -1.0, None, "high"
    )
    payload = serialize_store({"p1": hist}, {"p1": state})
    histories, states = restore_store(payload, NOW)
    assert [o.moisture for o in histories["p1"].valid()] == [30.0, 42.0, 44.0]
    assert states["p1"].status == S.WET
    assert states["p1"].state_since == NOW - timedelta(hours=10)
    assert states["p1"].confidence == "high"


def test_store_rejects_future_and_naive_timestamps():
    payload = {
        "version": STORE_VERSION,
        "plants": {
            "p1": {
                "rolling": [
                    {  # future -> dropped
                        "observed_at": (NOW + timedelta(hours=1)).isoformat(),
                        "moisture": 50.0,
                        "soil_temperature": None,
                        "moisture_valid": True,
                        "soil_temperature_valid": False,
                    },
                    {  # naive -> dropped
                        "observed_at": "2026-01-15T09:00:00",
                        "moisture": 40.0,
                        "soil_temperature": None,
                        "moisture_valid": True,
                        "soil_temperature_valid": False,
                    },
                    {  # valid -> kept
                        "observed_at": (NOW - timedelta(hours=1)).isoformat(),
                        "moisture": 42.0,
                        "soil_temperature": None,
                        "moisture_valid": True,
                        "soil_temperature_valid": False,
                    },
                ],
                "moisture_state": {
                    "status": S.WET,
                    "state_since": (NOW + timedelta(hours=2)).isoformat(),  # future
                    "last_watering_event": None,
                    "cycle_peak_moisture": 70.0,
                    "drying_rate_per_hour": None,
                    "adjusted_wet_duration_limit": None,
                    "confidence": "high",
                },
            }
        },
    }
    histories, states = restore_store(payload, NOW)
    assert [o.moisture for o in histories["p1"].valid()] == [42.0]
    assert states["p1"].state_since is None  # future timestamp dropped to None


def test_store_unknown_version_starts_fresh():
    histories, states = restore_store({"version": 999, "plants": {"p1": {}}}, NOW)
    assert histories == {} and states == {}


def test_restart_resumes_wet_duration_and_escalates():
    # Scenario 18: restart mid-cycle. Only the last day of observations is
    # retained, but the persisted run start (80 h) survives, so the plant
    # escalates to too_wet instead of resetting.
    samples = []
    m = 24 * 60
    while m >= 0:
        samples.append(obs(m, 70.0))
        m -= 120
    state = TemporalMoistureState(
        S.STAYING_WET, NOW - timedelta(hours=80), None, 70.0, 0.0, None, "high"
    )
    payload = serialize_store({"p1": history(samples)}, {"p1": state})
    histories, states = restore_store(payload, NOW)
    decision, _ = evaluate_moisture(histories["p1"], states["p1"], NOW, "balanced", None)
    assert decision.status == S.TOO_WET


def test_sensor_unavailable_midcycle_keeps_last_valid_reading():
    # Scenario 17: the sensor drops out after a wet run. The invalid reading is
    # excluded from analysis and the last valid value still drives the status.
    samples = [obs(180, 70.0), obs(120, 70.0), obs(60, 70.0), obs(0, None, valid=False)]
    prior = TemporalMoistureState(
        S.WET, NOW - timedelta(hours=3), None, 70.0, 0.0, None, "medium"
    )
    decision, _ = evaluate_moisture(history(samples), prior, NOW, "balanced", None)
    assert decision.status in (S.WET, S.STAYING_WET, S.TOO_WET)
    assert decision.status != S.WAITING_FOR_DATA


# ------------------------------------------------- P3: duration escalation

def _confident_wet_history():
    # ~12 h of dense wet readings: enough for medium confidence, but short
    # enough that the persisted run start (not the window) sets the elapsed age.
    samples = []
    m = 12 * 60
    while m >= 0:
        samples.append(obs(m, 70.0))
        m -= 120
    return history(samples)


def test_wetness_escalates_only_as_the_run_ages():
    # The background tick advances the run start; the same confident wet history
    # reads differently only because more time has elapsed.
    ladder = {
        20: S.WET,
        30: S.STAYING_WET,
        80: S.TOO_WET,
    }
    for hours, expected in ladder.items():
        prior = TemporalMoistureState(
            expected, NOW - timedelta(hours=hours), None, 70.0, 0.0, None, "high"
        )
        decision, _ = evaluate_moisture(
            _confident_wet_history(), prior, NOW, "balanced", None
        )
        assert decision.status == expected, (hours, decision.status)


def test_attention_stays_off_through_recently_watered_wet_and_drying():
    recently = decide([obs(40, 39.0), obs(0, 47.0)], profile="dry")[0]
    wet = decide([obs(0, 70.0)], profile="balanced")[0]
    prior = TemporalMoistureState(
        S.WET, NOW - timedelta(hours=6), None, 95.0, -4.0, None, "high"
    )
    drying = evaluate_moisture(
        history([obs(300, 95.0), obs(120, 82.0), obs(0, 70.0)]),
        prior,
        NOW,
        "balanced",
        None,
    )[0]
    assert recently.status == S.RECENTLY_WATERED and recently.needs_attention is False
    assert wet.status == S.WET and wet.needs_attention is False
    assert drying.status == S.DRYING and drying.needs_attention is False


# ------------------------------------------------- P4: drying coefficient

from domain.temporal.drying import drying_context, limit_factor, vpd_kpa


def _ctx(**kw):
    base = dict(base_limit_hours=72.0, slope=None, temperature=None, humidity=None,
                light_lux_hours_24h=None, radiation_24h=None)
    base.update(kw)
    return drying_context(**base)


def test_k_drying_is_neutral_without_inputs_and_bounded():
    ctx = _ctx()
    assert ctx.k_drying == 0.5 and ctx.adjusted_wet_duration_limit == 72.0
    assert ctx.confidence == "low" and ctx.label == "normal"
    hot = _ctx(slope=-5.0, temperature=40.0, humidity=5.0,
               light_lux_hours_24h=1e6, radiation_24h=1e6)
    cold = _ctx(slope=0.0, temperature=0.0, humidity=100.0,
                light_lux_hours_24h=0.0, radiation_24h=0.0)
    assert hot.k_drying == 1.0 and cold.k_drying == 0.0
    assert hot.adjusted_wet_duration_limit == 72.0 * 0.65
    assert cold.adjusted_wet_duration_limit == 72.0 * 2.0


def test_outdoor_radiation_never_exceeds_its_fifteen_percent_share():
    only_radiation = _ctx(radiation_24h=1e6)
    assert abs(only_radiation.k_drying - (0.85 * 0.5 + 0.15)) < 1e-9
    assert only_radiation.outdoor_radiation_bounded == 0.15


def test_limit_factor_mapping_and_vpd():
    assert limit_factor(0.0) == 2.0 and limit_factor(0.5) == 1.0
    assert abs(limit_factor(1.0) - 0.65) < 1e-9
    assert vpd_kpa(None, 50.0) is None
    assert abs(vpd_kpa(25.0, 50.0) - 1.584) < 0.01  # Tetens at 25 C / 50 %


def test_dormancy_extends_the_allowance_up_to_three_times():
    cold = _ctx(slope=0.0, temperature=0.0, humidity=100.0,
                light_lux_hours_24h=0.0, radiation_24h=0.0, dormant=True)
    assert cold.adjusted_wet_duration_limit == 72.0 * 3.0


def test_low_expected_drying_extends_the_allowance():
    # 90 h wet would be too_wet at the base 72 h limit; a longer limit holds it.
    prior = TemporalMoistureState(
        S.STAYING_WET, NOW - timedelta(hours=90), None, 70.0, 0.0, None, "high"
    )
    decision, state = evaluate_moisture(
        _confident_wet_history(), prior, NOW, "balanced", wet_limit_hours=144.0
    )
    assert decision.status == S.STAYING_WET
    assert state.adjusted_wet_duration_limit == 144.0


def test_strong_expected_drying_shortens_the_allowance():
    prior = TemporalMoistureState(
        S.STAYING_WET, NOW - timedelta(hours=50), None, 70.0, 0.0, None, "high"
    )
    decision, _ = evaluate_moisture(
        _confident_wet_history(), prior, NOW, "balanced", wet_limit_hours=72.0 * 0.65
    )
    assert decision.status == S.TOO_WET
    assert decision.health == S.HEALTH_WATCH and decision.reason == "persistently_wet"


def test_realized_drying_slope_beats_the_shortened_prediction():
    declining = history(
        [obs(720, 95.0), obs(480, 86.0), obs(240, 76.0), obs(0, 70.0)]
    )
    prior = TemporalMoistureState(
        S.STAYING_WET, NOW - timedelta(hours=50), None, 95.0, -4.0, None, "high"
    )
    decision, _ = evaluate_moisture(
        declining, prior, NOW, "balanced", wet_limit_hours=72.0 * 0.65
    )
    assert decision.status == S.DRYING
    assert decision.needs_attention is False


# ------------------------------------------------- P5: precedence / summaries

def _sample_decisions():
    return [
        decide([obs(0, 45.0)], profile="balanced")[0],  # normal
        decide([obs(0, 70.0)], profile="balanced")[0],  # wet
        decide([obs(0, 18.0)], profile="balanced")[0],  # needs_water
        decide([obs(40, 39.0), obs(0, 47.0)], profile="dry")[0],  # recently_watered
    ]


def test_needs_attention_matches_status_classification():
    for decision in _sample_decisions():
        assert decision.needs_attention == (decision.reason in S.ATTENTION_REASONS)


def test_decision_summaries_are_plain_language_and_reasons_are_keys():
    for decision in _sample_decisions():
        assert " " in decision.summary and decision.summary[0].isupper()
        assert " " not in decision.reason and decision.reason.islower()


def test_since_is_a_datetime_for_active_statuses():
    decision, _ = decide([obs(0, 18.0)], profile="balanced")  # needs_water
    assert isinstance(decision.since, datetime)


def test_precedence_is_deterministic_and_total():
    # Every status has a distinct rank, so worst_of is unambiguous.
    ranks = [S._RANK[s] for s in S.STATUS_PRECEDENCE]
    assert ranks == sorted(ranks) and len(set(ranks)) == len(ranks)
    assert S.worst_of([S.WAITING_FOR_DATA, S.TOO_WET, S.NORMAL]) == S.TOO_WET


# ------------------------------------------------- health vocabulary

def test_moisture_health_uses_only_the_four_roadmap_states():
    allowed = {S.HEALTH_GOOD, S.HEALTH_WATCH, S.HEALTH_STRESSED, S.HEALTH_UNKNOWN}
    for decision in _sample_decisions():
        assert decision.health in allowed
    assert decide([])[0].health == S.HEALTH_UNKNOWN
    assert decide([obs(0, 18.0)])[0].health == S.HEALTH_WATCH  # needs_water


def test_worst_health_ignores_unknown_when_something_is_known():
    assert S.worst_health([S.HEALTH_GOOD, S.HEALTH_WATCH]) == S.HEALTH_WATCH
    assert S.worst_health([S.HEALTH_WATCH, S.HEALTH_STRESSED]) == S.HEALTH_STRESSED
    assert S.worst_health([S.HEALTH_UNKNOWN, S.HEALTH_GOOD]) == S.HEALTH_GOOD
    assert S.worst_health([]) == S.HEALTH_UNKNOWN


# ------------------------------------------------- history helpers

def test_rolling_mean_needs_minimum_samples_and_respects_window():
    h = history([
        obs(30, 40.0, light=1000.0, humidity=45.0),
        obs(20, 40.0, light=1200.0, humidity=55.0),
    ])
    # only two samples -> below default minimum of three
    assert h.rolling_mean(NOW, "light", "light_valid", window_hours=24.0) is None
    h.append(obs(10, 40.5, light=800.0, humidity=50.0))
    mean = h.rolling_mean(NOW, "light", "light_valid", window_hours=24.0)
    assert abs(mean - 1000.0) < 0.01
    # a reading outside the window is excluded
    assert h.rolling_mean(NOW, "light", "light_valid", window_hours=0.25) is None


def test_store_roundtrip_preserves_light_and_humidity():
    h = history([obs(10, 40.0, soil_temp=19.0, light=900.0, humidity=48.0)])
    payload = serialize_store({"p1": h}, {})
    histories, _ = restore_store(payload, NOW)
    restored = histories["p1"].observations[0]
    assert restored.light == 900.0 and restored.light_valid is True
    assert restored.humidity == 48.0 and restored.humidity_valid is True


# ------------------------------------------------- F3: learned baselines

from domain.temporal.baseline import (
    BaselineSamples,
    MIN_BAND_GAP,
    derive_band,
    update_samples,
)


def _obs_at(dt, moisture):
    return PlantObservation(dt, float(moisture), None, True, False)


def _simulate_cycles(cycles, spacing_days, start, *, dry, water):
    """Run update_samples over N watering cycles; return (samples, history)."""
    h = ObservationHistory(retention_hours=24 * 60)
    samples = BaselineSamples()
    for cycle in range(cycles):
        base = start + timedelta(days=cycle * spacing_days)
        for i, m in enumerate(dry):
            t = base + timedelta(hours=i * 6)
            h.append(_obs_at(t, m))
            samples = update_samples(samples, h, t)
        wt0 = base + timedelta(hours=len(dry) * 6)
        h.append(_obs_at(wt0, dry[-1]))
        samples = update_samples(samples, h, wt0)
        wt1 = wt0 + timedelta(minutes=30)
        h.append(_obs_at(wt1, water))
        samples = update_samples(samples, h, wt1)
    return samples, h


def test_update_samples_accumulates_troughs_and_peaks_per_cycle():
    start = NOW - timedelta(days=20)
    samples, _ = _simulate_cycles(3, 7, start, dry=[70, 55, 40, 28, 20], water=75.0)
    assert len(samples.troughs) >= 2 and len(samples.peaks) >= 2
    assert all(t <= 25 for t in samples.troughs)  # troughs are the dry lows


def test_derive_band_requires_the_full_gate():
    # Only ~11 days of coverage -> below the 14-day gate even with cycles.
    start = NOW - timedelta(days=12)
    samples, _ = _simulate_cycles(2, 5, start, dry=[70, 50, 30, 20], water=75.0)
    assert derive_band(samples, "high", samples.last_seen) is None
    # Enough coverage but low confidence -> still None.
    start = NOW - timedelta(days=20)
    ok, _ = _simulate_cycles(3, 7, start, dry=[70, 50, 30, 20], water=75.0)
    assert derive_band(ok, "medium", ok.last_seen) is None


def test_derive_band_learns_a_sane_range_once_calibrated():
    start = NOW - timedelta(days=20)
    samples, _ = _simulate_cycles(3, 7, start, dry=[72, 55, 40, 25, 18], water=78.0)
    band = derive_band(samples, "high", samples.last_seen)
    assert band is not None
    low, high = band
    assert 12 <= low <= 28 and 68 <= high <= 82 and high - low >= MIN_BAND_GAP


def test_stuck_sensor_never_learns_a_degenerate_band():
    start = NOW - timedelta(days=20)
    # dries only 52->48 and "waters" to 52: the band gap is far under the minimum
    samples, _ = _simulate_cycles(3, 7, start, dry=[52, 51, 50, 49, 48], water=52.0)
    assert derive_band(samples, "high", samples.last_seen) is None


def test_baseline_samples_roundtrip():
    s = BaselineSamples(
        troughs=(20.0, 22.0),
        peaks=(75.0, 78.0),
        cycle_low=30.0,
        cycle_high=60.0,
        last_watering=NOW - timedelta(hours=2),
        first_seen=NOW - timedelta(days=15),
        last_seen=NOW,
    )
    restored = BaselineSamples.from_dict(s.to_dict())
    assert restored == s


def test_learned_band_overrides_profile_in_the_engine():
    # 35% is comfortable under the balanced profile (25-65) but below a learned low of 40.
    profile_decision, _ = decide([obs(0, 35.0)], profile="balanced")
    assert profile_decision.status == S.NORMAL
    learned_decision, _ = evaluate_moisture(
        history([obs(0, 35.0)]), None, NOW, "balanced", None, band=(40.0, 80.0)
    )
    assert learned_decision.status == S.NEEDS_WATER


# ------------------------------------------------- dormancy (engine-level)
# Evidence-based dormancy and its effects are covered in test_timeline.py.

def test_dormancy_never_suppresses_genuine_dryness():
    # The dormant band only lowers the needs_water threshold, never removes it.
    from domain.temporal.season import dormant_band
    decision, _ = evaluate_moisture(
        history([obs(0, 10.0)]), None, NOW, "balanced",
        band=dormant_band((25.0, 65.0), True),
    )
    assert decision.status == S.NEEDS_WATER and decision.needs_attention is True


def test_watering_time_is_stable_across_dense_readings():
    # Real sensors report every few minutes. The detected watering must stay at
    # the moment of the rise, not move forward with each new reading.
    t0 = NOW - timedelta(hours=3)
    h = ObservationHistory()
    h.append(_obs_at(t0, 30.0))
    detected = set()
    for i in range(1, 25):  # 5-minute readings for 2 hours after watering
        t = t0 + timedelta(minutes=5 * i)
        h.append(_obs_at(t, 62.0 - i * 0.1))
        found = h.detect_watering(t)
        if found is not None:
            detected.add(found)
    assert detected == {t0 + timedelta(minutes=5)}


def test_one_watering_closes_exactly_one_learning_cycle():
    t0 = NOW - timedelta(days=2)
    h = ObservationHistory(retention_hours=24 * 60)
    samples = BaselineSamples()
    for i, m in enumerate([60, 50, 40, 30]):  # drying down
        t = t0 + timedelta(hours=i * 6)
        h.append(_obs_at(t, m))
        samples = update_samples(samples, h, t)
    wt = t0 + timedelta(hours=24)
    for i in range(24):  # watering, then 5-minute readings for 2 hours
        t = wt + timedelta(minutes=5 * i)
        h.append(_obs_at(t, 30.0 if i == 0 else 70.0 - i * 0.1))
        samples = update_samples(samples, h, t)
    assert len(samples.troughs) == 1
    assert samples.troughs[0] == 30.0
    # The span before the first watering ever seen did not start at a watering,
    # so its high is not a post-watering peak and is not learned.
    assert samples.peaks == ()


# ------------------------------------------------- calibration progress

from domain.temporal.baseline import (
    RELEARN_KEY,
    calibration_progress,
    days_since_relearn,
    relearn_baseline,
)


def test_calibration_progress_counts_days_and_cycles_and_says_what_is_missing():
    empty = calibration_progress(BaselineSamples(), "low", NOW, complete=False)
    assert empty.percent == 0 and empty.phase == "learning"
    assert empty.waiting_for == "2 more complete watering cycles"
    assert empty.estimated_ready is None

    # ~12 days in, two waterings seen: one complete cycle, one to go.
    start = NOW - timedelta(days=13)
    samples, _ = _simulate_cycles(2, 6, start, dry=[70, 50, 30, 20], water=75.0)
    at = samples.last_seen
    progress = calibration_progress(samples, "high", at, complete=False)
    assert progress.cycles == 1 and 0 < progress.percent < 99
    assert progress.waiting_for == "one more complete watering cycle"
    # Projected from this plant's own watering interval (about six days).
    assert samples.intervals and progress.estimated_ready is not None
    assert timedelta(days=4) < progress.estimated_ready - at < timedelta(days=8)


def test_calibration_progress_waits_for_days_then_confidence_then_completes():
    # Three waterings six days apart: two complete cycles in about 13 days.
    short, _ = _simulate_cycles(3, 6, NOW - timedelta(days=20), dry=[70, 50, 30, 20], water=75.0)
    early = calibration_progress(short, "high", short.last_seen, complete=False)
    assert early.cycles == 2 and early.days == 13
    assert early.waiting_for == "one more day of readings"
    # Four waterings five days apart: 16 days, but the data is not steady yet.
    covered, _ = _simulate_cycles(4, 5, NOW - timedelta(days=20), dry=[70, 50, 30, 20], water=75.0)
    unsure = calibration_progress(covered, "medium", covered.last_seen, complete=False)
    assert unsure.waiting_for == "steadier readings (data confidence is medium)"
    assert unsure.percent == 99  # every gate but the last: never shows 100 early
    done = calibration_progress(covered, "high", covered.last_seen, complete=True)
    assert done.percent == 100 and done.phase == "calibrated" and done.waiting_for is None


def test_watering_intervals_survive_a_restart():
    start = NOW - timedelta(days=20)
    samples, _ = _simulate_cycles(3, 7, start, dry=[70, 50, 30, 20], water=75.0)
    assert len(samples.intervals) == 2
    assert all(abs(hours - 7 * 24) < 1 for hours in samples.intervals)
    assert BaselineSamples.from_dict(samples.to_dict()).intervals == samples.intervals


def test_relearn_discards_days_before_the_reset():
    from datetime import date
    fresh = relearn_baseline(date(2026, 9, 26))
    assert fresh == {RELEARN_KEY: "2026-09-26"}

    class Day:
        def __init__(self, day):
            self.day = day

    days = [Day("2026-09-24"), Day("2026-09-26"), Day("2026-09-27")]
    assert [d.day for d in days_since_relearn(days, fresh)] == ["2026-09-26", "2026-09-27"]
    assert len(days_since_relearn(days, {})) == 3 and len(days_since_relearn(days, None)) == 3


def test_calibration_sensor_reports_progress_and_the_learned_range():
    from zoneinfo import ZoneInfo
    from domain.temporal.baseline import CalibrationProgress, describe_calibration
    tz = ZoneInfo("Europe/Stockholm")
    # 22:30 UTC is already the next day in Stockholm.
    learning = CalibrationProgress(62, "learning", 9, 1, "one more complete watering cycle",
                                   datetime(2026, 10, 2, 22, 30, tzinfo=timezone.utc))
    state, attrs = describe_calibration(learning, {"light_effective": 3500.0}, tz)
    assert state == 62 and attrs["phase"] == "learning"
    assert (attrs["days"], attrs["days_required"], attrs["cycles"], attrs["cycles_required"]) == (9, 14, 1, 2)
    assert attrs["estimated_ready"] == "2026-10-03"
    assert attrs["learned_norms"] == ["light"] and "learned_low" not in attrs
    assert "waiting for one more complete watering cycle" in attrs["summary"]
    done = CalibrationProgress(100, "calibrated", 20, 2, None, None)
    state, attrs = describe_calibration(done, {"complete": True, "low": 33.2, "high": 61.7}, tz)
    assert state == 100 and (attrs["learned_low"], attrs["learned_high"]) == (33, 62)
    assert attrs["summary"] == "Judged against its own learned range, 33-62%"
