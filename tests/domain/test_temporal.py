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


def obs(minutes_ago, moisture, *, valid=True, soil_temp=None):
    return PlantObservation(
        observed_at=NOW - timedelta(minutes=minutes_ago),
        moisture=moisture,
        soil_temperature=soil_temp,
        moisture_valid=valid,
        soil_temperature_valid=soil_temp is not None,
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
