from domain.physical import BATTERY_STATES, normalize_battery_state


def test_verified_categorical_battery_contract_is_exact():
    assert BATTERY_STATES == {"low", "middle", "high"}
    assert normalize_battery_state("low") == "low"
    assert normalize_battery_state("middle") == "middle"
    assert normalize_battery_state("high") == "high"
    assert normalize_battery_state("empty") is None
    assert normalize_battery_state("full") is None


def test_numeric_battery_contract_is_zero_through_one_hundred():
    assert normalize_battery_state(0) == 0.0
    assert normalize_battery_state("100") == 100.0
    assert normalize_battery_state(-1) is None
    assert normalize_battery_state(101) is None
