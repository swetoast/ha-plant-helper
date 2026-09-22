from pathlib import Path

ROOT = Path(__file__).parents[2] / "custom_components" / "plant_helper"


def test_setup_initializes_storage_before_forwarding_platforms():
    source = (ROOT / "__init__.py").read_text()
    initialize = source.index("await entry.runtime_data.async_initialize")
    assign = source.index("entry.runtime_data=PlantHelperRuntime()")
    forward = source.index("async_forward_entry_setups")
    assert assign < initialize < forward
    assert "HomeAssistantStorageBackend" in source
    assert "homeassistant.helpers.storage import Store" in source


def test_runtime_loads_storage_and_restores_persisted_plants():
    source = (ROOT / "runtime.py").read_text()
    assert "snapshot = await storage.async_load()" in source
    assert 'self.plants.load(snapshot.data["plants"])' in source
    assert "def require_storage" in source


def test_add_flow_requires_initialized_storage_and_logs_unexpected_failures():
    source = (ROOT / "options.py").read_text()
    assert "storage=runtime.require_storage()" in source
    assert '_LOGGER.exception("Failed to add plant")' in source
