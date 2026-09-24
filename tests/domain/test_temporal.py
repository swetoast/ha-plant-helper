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
    assert decision.health == S.HEALTH_TOO_WET
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
    assert S.worst_of([S.WET, S.RECENTLY_WATERED]) == S.WET
    assert S.raises_attention(S.TOO_DRY) is True
    assert S.raises_attention(S.WET) is False


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

from domain.temporal.drying import adjusted_wet_limit, drying_coefficient


def test_drying_coefficient_from_evapotranspiration_is_bounded():
    assert drying_coefficient(None) == 1.0
    assert drying_coefficient({"et0_24h": 3.0}) == 1.0
    assert drying_coefficient({"et0_24h": 6.0}) == 2.0
    assert drying_coefficient({"et0_24h": 0.3}) == 0.5  # clamped up from 0.1


def test_drying_coefficient_indoor_fallback_uses_temp_and_humidity():
    # Warm, dry air with no forecast evapotranspiration -> faster than baseline.
    k = drying_coefficient({"soil_temperature": 30.0, "humidity": 30.0})
    assert 1.2 < k < 1.4


def test_adjusted_wet_limit_bounds():
    assert adjusted_wet_limit(72.0, 1.0) == 72.0
    assert adjusted_wet_limit(72.0, 0.5) == 144.0  # slow drying, +100% cap
    assert adjusted_wet_limit(72.0, 2.0) == 72.0 * 0.65  # fast drying, -35% floor


def test_low_expected_drying_extends_the_allowance():
    # 90 h wet would be too_wet at the static 72 h limit, but low ET0 extends it.
    prior = TemporalMoistureState(
        S.STAYING_WET, NOW - timedelta(hours=90), None, 70.0, 0.0, None, "high"
    )
    decision, state = evaluate_moisture(
        _confident_wet_history(), prior, NOW, "balanced", {"et0_24h": 0.5}
    )
    assert decision.status == S.STAYING_WET
    assert state.adjusted_wet_duration_limit == 144.0


def test_strong_expected_drying_shortens_the_allowance():
    # 50 h wet is within the static 72 h limit, but high ET0 shortens it below 50.
    prior = TemporalMoistureState(
        S.STAYING_WET, NOW - timedelta(hours=50), None, 70.0, 0.0, None, "high"
    )
    decision, state = evaluate_moisture(
        _confident_wet_history(), prior, NOW, "balanced", {"et0_24h": 9.0}
    )
    assert decision.status == S.TOO_WET
    assert state.adjusted_wet_duration_limit == 72.0 * 0.65


def test_realized_drying_slope_beats_the_shortened_prediction():
    # Strong expected drying and past the shortened limit, but the soil is
    # measurably draining, so it reads drying rather than too_wet.
    declining = history(
        [obs(720, 95.0), obs(480, 86.0), obs(240, 76.0), obs(0, 70.0)]
    )
    prior = TemporalMoistureState(
        S.STAYING_WET, NOW - timedelta(hours=50), None, 95.0, -4.0, None, "high"
    )
    decision, _ = evaluate_moisture(
        declining, prior, NOW, "balanced", {"et0_24h": 9.0}
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
        assert decision.needs_attention == S.raises_attention(decision.status)


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


# ------------------------------------------------- care_status universal signals

from domain.temporal.drying import drying_context


def test_drying_context_buckets_are_shared_by_both_placements():
    assert drying_context(1.6) == "high"
    assert drying_context(1.0) == "normal"
    assert drying_context(0.5) == "low"


def test_decision_reports_confidence_and_drying_context_for_indoor():
    # Indoor: no ET0 forecast, warm dry air -> fallback coefficient -> "high".
    decision, _ = decide(
        [obs(0, 45.0)],
        profile="balanced",
        env={"placement": "indoor", "soil_temperature": 30.0, "humidity": 25.0},
    )
    assert decision.drying_context == "high"
    assert decision.confidence in ("low", "medium", "high")


def test_decision_reports_drying_context_for_outdoor_from_et0():
    decision, _ = decide(
        [obs(0, 45.0)],
        profile="balanced",
        env={"placement": "outdoor", "et0_24h": 0.5},
    )
    assert decision.drying_context == "low"


def test_waiting_for_data_still_reports_environmental_context():
    decision, _ = decide(
        [obs(0, None, valid=False)],
        env={"placement": "outdoor", "et0_24h": 9.0},
    )
    assert decision.status == S.WAITING_FOR_DATA
    assert decision.drying_context == "high"


# ------------------------------------------------- F2: light + humidity

from domain.temporal.light import light_context
from domain.temporal.humidity import humidity_context
from domain.temporal.status import merge_health


def test_light_context_buckets():
    assert light_context(None) is None
    assert light_context(100.0) == "low"
    assert light_context(5000.0) == "adequate"
    assert light_context(200000.0) == "high"


def test_humidity_context_buckets():
    assert humidity_context(None) is None
    assert humidity_context(20.0) == "low"
    assert humidity_context(50.0) == "adequate"
    assert humidity_context(85.0) == "high"


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


def test_merge_health_moisture_alarm_always_wins():
    assert merge_health(S.HEALTH_NEEDS_WATER, "low", "low") == S.HEALTH_NEEDS_WATER
    assert merge_health(S.HEALTH_TOO_WET, "adequate", None) == S.HEALTH_TOO_WET
    assert merge_health(S.HEALTH_UNKNOWN, "low", "high") == S.HEALTH_UNKNOWN


def test_merge_health_secondary_inadequacy_raises_watch_only():
    assert merge_health(S.HEALTH_GOOD, "low", "adequate") == S.HEALTH_WATCH
    assert merge_health(S.HEALTH_GOOD, "adequate", "high") == S.HEALTH_WATCH
    assert merge_health(S.HEALTH_GOOD, "adequate", "adequate") == S.HEALTH_GOOD
    assert merge_health(S.HEALTH_GOOD, None, None) == S.HEALTH_GOOD


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


# ------------------------------------------------- F4: seasonal dormancy

from domain.temporal.season import dormancy_multiplier, is_dormant


def test_dormancy_multiplier_reads_both_placements():
    assert dormancy_multiplier(None) == 1.0
    assert dormancy_multiplier({"growth_season": True}) == 1.0
    assert dormancy_multiplier({"growth_season": False}) == 0.7  # outdoor cold
    assert dormancy_multiplier({"season": "winter"}) == 0.7
    assert dormancy_multiplier({"season": "autumn"}) == 0.85
    assert dormancy_multiplier({"season": "summer"}) == 1.0
    assert dormancy_multiplier({"day_length": 8.0}) == 0.7
    assert dormancy_multiplier({"day_length": 14.0}) == 1.0
    assert is_dormant({"growth_season": False}) is True
    assert is_dormant({"growth_season": True}) is False


def test_dormancy_lowers_the_drying_coefficient():
    active = drying_coefficient({"et0_24h": 3.0, "growth_season": True})
    dormant = drying_coefficient({"et0_24h": 3.0, "growth_season": False})
    assert active == 1.0
    assert abs(dormant - 0.7) < 1e-9
    # a longer wet allowance follows directly
    assert adjusted_wet_limit(72.0, dormant) > adjusted_wet_limit(72.0, active)


def test_dormant_plant_tolerates_wet_soil_longer():
    prior = TemporalMoistureState(
        S.STAYING_WET, NOW - timedelta(hours=90), None, 70.0, 0.0, None, "high"
    )
    active, _ = evaluate_moisture(
        _confident_wet_history(), prior, NOW, "balanced", {"growth_season": True}
    )
    dormant, _ = evaluate_moisture(
        _confident_wet_history(), prior, NOW, "balanced", {"growth_season": False}
    )
    assert active.status == S.TOO_WET  # 90 h exceeds the 72 h active limit
    assert dormant.status == S.STAYING_WET  # dormant limit (~103 h) not yet reached


def test_extreme_wetness_still_escalates_even_when_dormant():
    prior = TemporalMoistureState(
        S.STAYING_WET, NOW - timedelta(hours=200), None, 70.0, 0.0, None, "high"
    )
    dormant, _ = evaluate_moisture(
        _confident_wet_history(), prior, NOW, "balanced", {"growth_season": False}
    )
    assert dormant.status == S.TOO_WET  # bounded limit (<=144 h) is exceeded


def test_dormancy_never_suppresses_genuine_dryness():
    decision, _ = decide(
        [obs(0, 18.0)], profile="balanced", env={"growth_season": False}
    )
    assert decision.status == S.NEEDS_WATER
    assert decision.needs_attention is True
