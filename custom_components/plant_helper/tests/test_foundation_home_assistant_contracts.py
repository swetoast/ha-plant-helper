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
    names = function_names("config_flow.py") | function_names("options.py")
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
    text = source("options.py")
    assert "def _finish" in text
    assert 'options["_rev"]' in text
    assert "async_reload" not in text


def test_remove_flow_purges_all_runtime_layers() -> None:
    text = source("options.py")
    purge = text[text.index("async def _purge_plant"):text.index("def _moisture_state")]
    assert "async_remove_user_plant" in purge
    assert "from .learned_store import remove_plant" in purge
    assert "remove_plant(learned.data, plant_id)" in purge
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
    assert "CONF_RADIATION_SOURCE" not in init_text
    assert "CONF_RADIATION_ENTITY" not in init_text
    assert "_opt(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)" in init_text
    assert "update_interval_seconds=update_interval" in init_text
    assert "update_interval=timedelta(seconds=interval_seconds)" in coordinator

def test_local_sensor_freshness_uses_source_timestamp() -> None:
    text = source("coordinator.py")
    assert 'getattr(state, "last_updated", None)' in text
    assert "current_reading_stale(source_ts, now, validation_spec)" in text
    assert "dedupe=True" in text


def test_background_jobs_are_off_update_critical_path() -> None:
    text = source("coordinator.py")
    assert "self._enrich_and_notify(now)" in text
    assert "self._enrichment_task" in text
    assert "_refresh_strang" not in text

def test_manifest_and_translation_contract() -> None:
    manifest = json.loads((ROOT / "manifest.json").read_text(encoding="utf-8"))
    strings = json.loads((ROOT / "strings.json").read_text(encoding="utf-8"))
    translation = json.loads((ROOT / "translations" / "en.json").read_text(encoding="utf-8"))
    assert manifest["domain"] == "plant_helper"
    assert manifest["config_flow"] is True
    assert manifest["integration_type"] == "hub"
    assert manifest["iot_class"] == "cloud_polling"
    assert strings == translation
    serialized = json.dumps(strings)
    assert "radiation_source" not in serialized
    assert "forecast_entity" not in serialized
    assert "outdoor_data_source" not in serialized
    assert "radiation_entity" not in serialized


def test_global_schema_has_no_removed_outdoor_source_selector() -> None:
    """The Open-Meteo-only global flow must not reference removed selector names."""
    text = (ROOT / "config_flow.py").read_text(encoding="utf-8")
    schema = text[text.index("def _global_schema"):text.index("# --- config flow")]
    assert "CONF_OUTDOOR_DATA_SOURCE" not in schema
    assert "DEFAULT_OUTDOOR_DATA_SOURCE" not in schema
    assert "OUTDOOR_DATA_SOURCES" not in schema


def test_location_fields_have_translations() -> None:
    """Every coordinate field exposed by global options needs a UI label."""
    strings = json.loads((ROOT / "strings.json").read_text(encoding="utf-8"))
    translation = json.loads((ROOT / "translations" / "en.json").read_text(encoding="utf-8"))
    for document in (strings, translation):
        fields = document["options"]["step"]["global_settings"]["data"]
        assert fields["latitude"]
        assert fields["longitude"]

def test_config_flow_uses_current_home_assistant_result_type() -> None:
    """Prevent an import-time invalid-handler failure on Home Assistant 2025.12."""
    text = (ROOT / "config_flow.py").read_text(encoding="utf-8")
    assert "ConfigFlow" in text and "OptionsFlow" in text
    assert "from homeassistant.data_entry_flow import FlowResult" not in text
    assert "-> FlowResult" not in text


def test_options_flow_is_defined_once_and_uses_managed_config_entry() -> None:
    """Options remain in config_flow.py and use HA's managed config_entry property."""
    config_text = (ROOT / "config_flow.py").read_text(encoding="utf-8")
    options_text = (ROOT / "options.py").read_text(encoding="utf-8")
    assert "class PlantHelperOptionsFlow" not in config_text
    assert options_text.count("class PlantHelperOptionsFlow(OptionsFlow):") == 1
    assert "from .options import PlantHelperOptionsFlow" in config_text
    assert "return PlantHelperOptionsFlow()" in config_text
    assert "self.config_entry =" not in options_text
    assert (ROOT / "options.py").is_file()


def test_removed_provider_contract_is_absent_from_runtime_modules() -> None:
    """Legacy provider selection must not leak through const or coordinator."""
    const_text = (ROOT / "const.py").read_text(encoding="utf-8")
    coordinator_text = (ROOT / "coordinator.py").read_text(encoding="utf-8")
    for name in (
        "CONF_FORECAST_ENTITY",
        "CONF_OUTDOOR_DATA_SOURCE",
        "DEFAULT_OUTDOOR_DATA_SOURCE",
        "OUTDOOR_DATA_SOURCES",
    ):
        assert name not in const_text
    assert "forecast_entity:" not in coordinator_text
    assert "outdoor_data_source:" not in coordinator_text


def test_global_settings_perenual_selector_uses_compatible_options() -> None:
    """Opening Global settings must not pass unsupported selector arguments."""
    import ast

    tree = ast.parse((ROOT / "config_flow.py").read_text(encoding="utf-8"))
    global_schema = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_global_schema"
    )
    calls = [
        node for node in ast.walk(global_schema)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "SelectSelectorConfig"
    ]
    assert len(calls) == 1
    keywords = {kw.arg for kw in calls[0].keywords}
    assert keywords == {"options", "mode"}
    options = next(kw.value for kw in calls[0].keywords if kw.arg == "options")
    assert isinstance(options, ast.List) and len(options.elts) == 2
    for item in options.elts:
        assert isinstance(item, ast.Dict)
        assert {key.value for key in item.keys} == {"value", "label"}


def test_global_settings_step_builds_its_schema_before_showing_form() -> None:
    """The options step must call the schema builder with current options."""
    import ast

    tree = ast.parse((ROOT / "options.py").read_text(encoding="utf-8"))
    options_flow = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "PlantHelperOptionsFlow"
    )
    step = next(
        node for node in options_flow.body
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "async_step_global_settings"
    )
    calls = [node for node in ast.walk(step) if isinstance(node, ast.Call)]
    assert any(
        isinstance(call.func, ast.Name)
        and call.func.id == "_global_schema"
        and len(call.args) == 1
        and isinstance(call.args[0], ast.Attribute)
        and call.args[0].attr == "options"
        for call in calls
    )
