"""Phase B Home Assistant-facing contract tests.

These tests verify the integration boundary without importing Home Assistant,
so they remain runnable in the lightweight source-test environment. Pure model
behaviour is covered by the existing engine suite.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def source(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def function_names(name: str) -> set[str]:
    tree = ast.parse(source(name))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_config_flow_exposes_complete_lifecycle() -> None:
    names = function_names("config_flow.py")
    assert {
        "async_step_user",
        "async_get_options_flow",
        "async_step_init",
        "async_step_add_plant",
        "async_step_edit_plant_select",
        "async_step_edit_plant",
        "async_step_remove_plant",
        "async_step_global_settings",
    } <= names


def test_config_flow_uses_single_reload_revision_path() -> None:
    text = source("config_flow.py")
    assert "def _finish" in text
    assert 'options["_rev"]' in text
    assert "async_reload" not in text


def test_remove_flow_purges_all_runtime_layers() -> None:
    text = source("config_flow.py")
    purge = text[text.index("async def _purge_plant"):text.index("def _moisture_state")]
    assert "async_remove_user_plant" in purge
    assert "learned_remove_plant" in purge
    assert "clear_key_prefix" in purge
    assert "self._remove_device(plant_id)" in purge
    assert "registry.async_remove_device(device.id)" in text
    assert 'getattr(coordinator, "_plants", {}).pop' in purge
    assert 'getattr(coordinator, "_enrichment", {}).pop' in purge


def test_unload_never_resaves_immediate_storage() -> None:
    text = source("__init__.py")
    unload = text[text.index("async def async_unload_entry"):text.index("def _register_services")]
    assert 'for key in ("learned", "samples")' in unload
    assert 'data.get("storage")' not in unload


def test_services_and_descriptions_stay_synchronized() -> None:
    init_text = source("__init__.py")
    services = (ROOT / "services.yaml").read_text(encoding="utf-8")
    strings = json.loads((ROOT / "strings.json").read_text(encoding="utf-8"))
    for service in ("recalibrate", "refresh_species"):
        assert f'async_register(DOMAIN, "{service}"' in init_text
        assert f"{service}:" in services
        assert service in strings["services"]


def test_coordinator_covers_failure_isolation_and_persistence() -> None:
    text = source("coordinator.py")
    assert "for plant_id, cfg in self._plants.items()" in text
    assert "except Exception" in text
    assert "self._samples.schedule_save()" in text
    assert "self._learned.schedule_save()" in text
    assert "ls.get_last_reduced" in text
    assert "ls.set_last_reduced" in text


def test_runtime_settings_reach_coordinator() -> None:
    init_text = source("__init__.py")
    coordinator = source("coordinator.py")
    assert "radiation_source = _opt(CONF_RADIATION_SOURCE" in init_text
    assert "update_interval = _opt(CONF_UPDATE_INTERVAL" in init_text
    assert "update_interval_seconds=update_interval" in init_text
    assert "update_interval=timedelta(seconds=interval_seconds)" in coordinator


def test_local_sensor_freshness_uses_source_timestamp() -> None:
    text = source("coordinator.py")
    assert 'getattr(state, "last_updated", None)' in text
    assert "current_reading_stale(source_ts, now, validation_spec)" in text
    assert "dedupe=True" in text


def test_background_jobs_are_off_update_critical_path() -> None:
    text = source("coordinator.py")
    assert "self._refresh_strang(now)" in text and "self._strang_task" in text
    assert "self._enrich_and_notify(now)" in text and "self._enrichment_task" in text


def test_manifest_and_translation_contract() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    strings = json.loads((ROOT / "strings.json").read_text(encoding="utf-8"))
    translation = json.loads((ROOT / "translations" / "en.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "plant_helper"
    assert manifest["config_flow"] is True
    assert manifest["integration_type"] == "hub"
    assert manifest["iot_class"] == "cloud_polling"
    assert strings == translation
    radiation_label = strings["config"]["step"]["user"]["data"]["radiation_source"]
    assert "STRÅNG in Nordic coverage" in radiation_label
    assert "Open-Meteo radiation elsewhere" in radiation_label
    assert "else your sensors" not in radiation_label
