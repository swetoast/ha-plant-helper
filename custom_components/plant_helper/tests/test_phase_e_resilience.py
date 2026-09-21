"""Phase E operational-resilience contracts."""
from pathlib import Path
import ast
ROOT = Path(__file__).resolve().parents[1]
def text(name): return (ROOT / name).read_text(encoding="utf-8")
def test_background_tasks_are_tracked_and_non_overlapping():
    source=text("coordinator.py")
    assert "self._enrichment_task = None" in source
    assert "self._enrichment_task is None or self._enrichment_task.done()" in source
    assert "self._strang_task" not in source

def test_background_tasks_are_cancelled_on_unload():
    coordinator=text("coordinator.py"); setup=text("__init__.py")
    assert "async def async_shutdown" in coordinator and "task.cancel()" in coordinator
    assert "await asyncio.gather(*tasks, return_exceptions=True)" in coordinator
    assert "await coordinator.async_shutdown()" in setup
def test_open_meteo_refresh_is_throttled_and_cached():
    source=text("coordinator.py")
    assert "timedelta(minutes=30)" in source
    assert "timedelta(hours=2)" in source
    assert '"request_failed"' in source
    assert "self._open_meteo_context" in source

def test_services_register_independently():
    source=text("__init__.py")
    assert 'if not hass.services.has_service(DOMAIN, "recalibrate"):' in source
    assert 'if not hass.services.has_service(DOMAIN, "refresh_species"):' in source
def test_provider_diagnostics_expose_full_contract():
    source=text("binary_sensor.py")
    for key in ("configured","enabled","ok","last_result","partial_result","last_attempt","last_success","last_error","calls_today","daily_limit","throttled"):
        assert f'health.get("{key}")' in source
