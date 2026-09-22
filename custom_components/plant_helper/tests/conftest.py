"""Test bootstrap: expose the integration dir as package `plant_helper`.

Mirrors the shipped layout (custom_components/plant_helper/{engine,sources,...})
so intra-package relative imports like `from ..engine` resolve, without running
the HA-heavy top-level __init__.py.
"""
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if "plant_helper" not in sys.modules:
    pkg = types.ModuleType("plant_helper")
    pkg.__path__ = [str(ROOT)]
    sys.modules["plant_helper"] = pkg


def pytest_pyfunc_call(pyfuncitem):
    """Run coroutine test functions without an external pytest async plugin."""
    import asyncio
    import inspect

    if not inspect.iscoroutinefunction(pyfuncitem.obj):
        return None
    kwargs = {
        name: pyfuncitem.funcargs[name]
        for name in inspect.signature(pyfuncitem.obj).parameters
    }
    asyncio.run(pyfuncitem.obj(**kwargs))
    return True
