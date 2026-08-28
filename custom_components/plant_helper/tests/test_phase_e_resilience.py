"""Phase E operational-resilience contracts."""
from pathlib import Path
import ast
ROOT = Path(__file__).resolve().parents[1]
def text(name): return (ROOT / name).read_text(encoding="utf-8")
def test_background_tasks_are_tracked_and_non_overlapping():
    source=text("coordinator.py")
    assert "self._strang_task = None" in source and "self._enrichment_task = None" in source
    assert "self._strang_task is None or self._strang_task.done()" in source
    assert "self._enrichment_task is None or self._enrichment_task.done()" in source
def test_background_tasks_are_cancelled_on_unload():
    coordinator=text("coordinator.py"); setup=text("__init__.py")
    assert "async def async_shutdown" in coordinator and "task.cancel()" in coordinator
    assert "await asyncio.gather(*tasks, return_exceptions=True)" in coordinator
    assert "await coordinator.async_shutdown()" in setup
def test_strang_failure_retries_before_hourly_success_window():
    source=text("coordinator.py"); tree=ast.parse(source)
    method=next(n for n in ast.walk(tree) if isinstance(n,ast.AsyncFunctionDef) and n.name=="_refresh_strang")
    body=ast.get_source_segment(source,method)
    assert body.index("self._last_strang = now") > body.index("self._strang_failures = 0")
    assert body.index("self._last_strang = now") > body.index("except Exception as err")
def test_services_register_independently():
    source=text("__init__.py")
    assert 'if not hass.services.has_service(DOMAIN, "recalibrate"):' in source
    assert 'if not hass.services.has_service(DOMAIN, "refresh_species"):' in source
def test_provider_diagnostics_expose_full_contract():
    source=text("binary_sensor.py")
    for key in ("configured","enabled","ok","last_result","partial_result","last_attempt","last_success","last_error","calls_today","daily_limit","throttled"):
        assert f'health.get("{key}")' in source
