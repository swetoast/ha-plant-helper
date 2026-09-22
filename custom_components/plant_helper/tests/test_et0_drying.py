"""Phase 2 ET0 drying-pressure behavior."""
from datetime import datetime, timedelta, timezone
from plant_helper.engine import engine as eng
from plant_helper.engine import thermal_model as th
from plant_helper.engine.validation import RawReading

NOW = datetime(2026, 8, 28, 12, tzinfo=timezone.utc)

def inputs(**kw):
    base = dict(now=NOW, placement="outdoor", m_max=80.0, m_dry=40.0,
                drying_rate=8.0, moisture_raw=[RawReading(NOW - timedelta(minutes=20), 61.0), RawReading(NOW - timedelta(minutes=10), 60.5), RawReading(NOW, 60.0)])
    base.update(kw)
    return eng.EngineInputs(**base)

def test_et0_modifier_is_bounded_and_neutral_near_reference():
    assert th.drying_modifier_from_et0(3.0, placement="outdoor") == 1.0
    assert th.drying_modifier_from_et0(0.0, placement="outdoor") == 0.85
    assert th.drying_modifier_from_et0(20.0, placement="outdoor") == 1.15

def test_et0_is_outdoor_only_and_invalid_is_neutral():
    assert th.drying_modifier_from_et0(8.0, placement="indoor") == 1.0
    assert th.drying_modifier_from_et0(None, placement="outdoor") == 1.0
    assert th.drying_modifier_from_et0(-1.0, placement="outdoor") == 1.0
    assert th.drying_modifier_from_et0(99.0, placement="outdoor") == 1.0

def test_high_et0_accelerates_projection_but_keeps_learned_rate_unchanged():
    neutral = eng.compute(inputs(et0_next_24h_mm=3.0))
    high = eng.compute(inputs(et0_next_24h_mm=8.0))
    assert neutral.et0_drying_modifier == 1.0
    assert high.et0_drying_modifier == 1.15
    assert high.effective_drying_rate > neutral.effective_drying_rate
    assert high.moisture.days_until_dry < neutral.moisture.days_until_dry
    assert inputs(et0_next_24h_mm=8.0).drying_rate == 8.0

def test_low_missing_and_indoor_behavior():
    low = eng.compute(inputs(et0_next_24h_mm=0.0))
    missing = eng.compute(inputs(et0_next_24h_mm=None))
    indoor = eng.compute(inputs(placement="indoor", et0_next_24h_mm=8.0))
    assert low.effective_drying_rate < missing.effective_drying_rate
    assert missing.et0_drying_modifier == 1.0
    assert indoor.et0_drying_modifier == 1.0 and indoor.et0_next_24h_mm is None

def test_combined_modifier_has_strict_global_bounds():
    assert th.combine_drying_modifiers(0.1, 0.85) == 0.60
    assert th.combine_drying_modifiers(2.0, 1.15) == 1.15
