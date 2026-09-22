from pathlib import Path

ROOT = Path(__file__).parents[1] / "custom_components" / "plant_helper"


def test_remove_requires_checked_confirmation():
    source = (ROOT / "options.py").read_text()
    assert 'if not user_input.get("confirm", False):' in source
    assert 'errors["base"] = "confirmation_required"' in source


def test_remove_delegates_to_runtime_lifecycle_coordinator():
    source = (ROOT / "options.py").read_text()
    assert "await runtime.remove_plant(uuid, self._expected_revision)" in source
    assert "_async_remove_loaded_entities" not in source


def test_pending_cleanup_runs_after_platform_setup():
    source = (ROOT / "__init__.py").read_text()
    setup = source.index("async_forward_entry_setups")
    reconcile = source.index("reconcile_pending_removals")
    assert setup < reconcile
