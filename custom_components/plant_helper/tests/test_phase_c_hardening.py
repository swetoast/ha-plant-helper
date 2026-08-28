"""Phase C source and lifecycle hardening contracts."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]

def text(name):
    return (ROOT / name).read_text(encoding="utf-8")

def test_retryable_strang_source_policy():
    source = text("coordinator.py")
    assert 'self._radiation_source = radiation_source' in source
    assert 'self._strang_failures >= 3' in source
    assert 'self._radiation_source == "auto"' in source
    assert 'API mode retained for retry' in source
    assert 'self._use_strang_api = False' in source

def test_radiation_diagnostics_exposed():
    coordinator = text("coordinator.py")
    binary = text("binary_sensor.py")
    for key in ("configured_source", "active_source", "last_attempt", "last_success", "last_error", "latest_data_time", "data_age_hours", "sample_counts", "consecutive_failures", "fallback"):
        assert f'"{key}"' in coordinator
    assert "class RadiationSourceIssueBinary" in binary
    assert "radiation_status" in binary

def test_provider_health_contract_is_consistent():
    source = text("coordinator.py")
    for key in ("configured", "enabled", "ok", "last_result", "partial_result", "last_attempt", "last_success", "last_error", "calls_today", "daily_limit", "throttled"):
        assert f'"{key}"' in source
    for state in ("not_configured", "throttled", "error", "success", "idle"):
        assert f'"{state}"' in source

def test_duplicate_engine_enrichment_is_absent():
    assert not (ROOT / "engine" / "enrichment.py").exists()
    for path in ROOT.rglob("*.py"):
        if path == Path(__file__):
            continue
        assert "engine.enrichment" not in path.read_text(encoding="utf-8")

def test_services_removed_after_last_unload_and_resolve_runtime_entry():
    source = text("__init__.py")
    assert 'if not hass.data.get(DOMAIN)' in source
    assert 'hass.services.async_remove(DOMAIN, service)' in source
    assert '"entry_id": entry.entry_id' in source
    assert 'entry_id = data.get("entry_id")' in source

def test_public_metadata_is_privacy_safe():
    assert 'AUTHOR = "Plant Helper"' in text("const.py")
    assert "Peter Skopa" not in text("const.py")
    manifest = json.loads(text("manifest.json"))
    assert tuple(map(int, manifest["version"].split("."))) >= (4, 0, 24)
