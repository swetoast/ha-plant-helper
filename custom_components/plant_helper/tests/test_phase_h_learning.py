"""Phase H learning-lifecycle behavior tests."""
from datetime import datetime, timezone
from pathlib import Path
from plant_helper import learned_store as ls, runtime as rt
from plant_helper.engine import calibration_math as cal

NOW = "2026-08-28T12:00:00+00:00"

def test_post_lock_adaptation_is_bounded_and_mmax_only():
    data = ls.empty_data()
    ls.set_baseline(data, "p", "indoor", {"m_max": 80.0, "m_dry": 40.0}, status="complete", locked_at=NOW)
    record = cal.DailyRecord(day_index=15, coverage=0.9, day_peak=90.0)
    assert rt.adapt_locked_baseline(data, "p", "indoor", record, now_iso=NOW)
    base = ls.active_baseline(data, "p", "indoor")
    assert base["m_max"] == cal.nudge_peak(80.0, 90.0)
    assert base["m_dry"] == 40.25
    assert base["adaptation"] == "m_max_only"

def test_adaptation_rejects_low_coverage_and_downward_noise():
    data = ls.empty_data()
    ls.set_baseline(data, "p", "indoor", {"m_max": 80.0}, status="complete")
    assert not rt.adapt_locked_baseline(data, "p", "indoor", cal.DailyRecord(day_index=1, coverage=0.2, day_peak=95.0), now_iso=NOW)
    assert not rt.adapt_locked_baseline(data, "p", "indoor", cal.DailyRecord(day_index=2, coverage=0.9, day_peak=70.0), now_iso=NOW)
    assert ls.active_baseline(data, "p", "indoor")["m_max"] == 80.0

def test_dual_baselines_survive_placement_transition():
    data = ls.empty_data()
    ls.set_config(data, "p", {"placement": "indoor"})
    ls.set_baseline(data, "p", "indoor", {"m_max": 80.0}, status="complete")
    assert ls.swap_placement(data, "p", "outdoor") is True
    assert ls.active_baseline(data, "p", "indoor")["m_max"] == 80.0
    ls.set_baseline(data, "p", "outdoor", {"m_max": 90.0}, status="complete")
    assert ls.swap_placement(data, "p", "indoor") is False
    assert ls.active_baseline(data, "p")["m_max"] == 80.0


def test_standard_profile_adaptation_recomputes_threshold_policy():
    data = ls.empty_data()
    ls.set_baseline(data, "p", "indoor", {
        "profile": cal.PROFILE_BALANCED, "m_max": 80.0, "m_dry": 39.0,
        "dry_multiplier": 0.5,
    }, status="complete")
    record = cal.DailyRecord(day_index=20, coverage=0.9, day_peak=90.0)
    assert rt.adapt_locked_baseline(data, "p", "indoor", record, now_iso=NOW)
    base = ls.active_baseline(data, "p", "indoor")
    assert base["m_dry"] == cal.dry_threshold(base["m_max"], cal.PROFILE_BALANCED)

def test_custom_profile_adaptation_uses_persisted_multiplier():
    data = ls.empty_data()
    ls.set_baseline(data, "p", "indoor", {
        "profile": cal.PROFILE_CUSTOM, "custom_multiplier": 0.3,
        "dry_multiplier": 0.3, "m_max": 80.0, "m_dry": 24.0,
    }, status="complete")
    record = cal.DailyRecord(day_index=20, coverage=0.9, day_peak=90.0)
    assert rt.adapt_locked_baseline(data, "p", "indoor", record, now_iso=NOW)
    base = ls.active_baseline(data, "p", "indoor")
    assert base["m_dry"] == cal.dry_threshold(
        base["m_max"], cal.PROFILE_CUSTOM, custom_multiplier=0.3
    )

def test_swap_to_missing_baseline_initializes_calibration():
    data = ls.empty_data()
    ls.set_config(data, "p", {"placement": "indoor"})
    ls.set_baseline(data, "p", "indoor", {"m_max": 80.0}, status="complete")
    assert ls.swap_placement(data, "p", "outdoor") is True
    progress = ls.get_calibration(data, "p", "outdoor")
    assert progress == {"status": "calibrating", "day_records": []}
    assert ls.active_baseline(data, "p", "indoor")["m_max"] == 80.0

def test_swap_to_complete_baseline_reuses_without_resetting_progress():
    data = ls.empty_data()
    ls.set_config(data, "p", {"placement": "indoor"})
    ls.set_baseline(data, "p", "indoor", {"m_max": 80.0}, status="complete")
    ls.set_baseline(data, "p", "outdoor", {"m_max": 90.0}, status="complete")
    ls.set_calibration(data, "p", "outdoor", {"status": "complete", "day_records": [{"day": 1}]})
    assert ls.swap_placement(data, "p", "outdoor") is False
    assert ls.active_baseline(data, "p")["m_max"] == 90.0
    assert ls.get_calibration(data, "p", "outdoor")["day_records"] == [{"day": 1}]

def test_options_flow_consumes_placement_transition_decision():
    source = (Path(__file__).resolve().parents[1] / "config_flow.py").read_text()
    assert "needs_calibration = learned_swap_placement(" in source
    assert "if needs_calibration:" in source
    assert "reused its complete baseline" in source
