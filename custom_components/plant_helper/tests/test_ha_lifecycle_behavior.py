"""Executable Home Assistant-boundary lifecycle tests with lightweight fakes."""
from __future__ import annotations

import importlib.util
from importlib.machinery import SourceFileLoader
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
MODULE_NAME = "plant_helper._ha_lifecycle_under_test"


class ServiceValidationError(Exception):
    pass


class ConfigEntry:
    def __init__(self, entry_id="entry-1", data=None, options=None):
        self.entry_id = entry_id
        self.data = data or {}
        self.options = options or {}
        self.listeners = []
        self.unloads = []

    def add_update_listener(self, listener):
        self.listeners.append(listener)
        return listener

    def async_on_unload(self, callback):
        self.unloads.append(callback)


class ServiceCall:
    def __init__(self, data=None):
        self.data = data or {}


class FakeServices:
    def __init__(self):
        self.handlers = {}

    def has_service(self, domain, service):
        return (domain, service) in self.handlers

    def async_register(self, domain, service, handler):
        self.handlers[(domain, service)] = handler

    def async_remove(self, domain, service):
        self.handlers.pop((domain, service), None)


class FakeConfigEntries:
    def __init__(self):
        self.forwarded = []
        self.unloaded = []
        self.reloaded = []
        self.unload_result = True

    async def async_forward_entry_setups(self, entry, platforms):
        self.forwarded.append((entry.entry_id, tuple(platforms)))

    async def async_unload_platforms(self, entry, platforms):
        self.unloaded.append((entry.entry_id, tuple(platforms)))
        return self.unload_result

    async def async_reload(self, entry_id):
        self.reloaded.append(entry_id)


class FakeHass:
    def __init__(self):
        self.data = {}
        self.services = FakeServices()
        self.config_entries = FakeConfigEntries()
        self.config = types.SimpleNamespace(latitude=57.72, longitude=12.94)


class FakeStore:
    instances = []

    def __init__(self, hass):
        self.hass = hass
        self.loaded = False
        self.saved = False
        self.scheduled = False
        self.data = {"plants": {}}
        self.__class__.instances.append(self)

    async def async_load(self):
        self.loaded = True
        return self.data

    async def async_save(self):
        self.saved = True

    def schedule_save(self):
        self.scheduled = True

    def get_all_user_plants(self):
        return {
            "fern": {
                "custom_name": "Fern",
                "species": "Nephrolepis exaltata",
                "entities": {
                    "placement": "indoor",
                    "profile": "balanced",
                    "soil_moisture": "sensor.fern_moisture",
                },
            }
        }

    def get_plant(self, species):
        return {"species": species, "common_name": "Fern"}


class FakeApi:
    instances = []

    def __init__(self, *args, **kwargs):
        self.calls = []
        self.__class__.instances.append(self)

    async def fetch_plant(self, species, force_fetch=False):
        self.calls.append((species, force_fetch))
        return {"species": species}


class FakeCoordinator:
    instances = []

    def __init__(self, hass, **kwargs):
        self.hass = hass
        self.kwargs = kwargs
        self.first_refresh = False
        self.refreshes = 0
        self.shutdown = False
        self.__class__.instances.append(self)

    async def async_config_entry_first_refresh(self):
        self.first_refresh = True

    async def async_request_refresh(self):
        self.refreshes += 1

    async def async_shutdown(self):
        self.shutdown = True


def _install_stubs(monkeypatch):
    modules = {
        "homeassistant": types.ModuleType("homeassistant"),
        "homeassistant.config_entries": types.ModuleType("homeassistant.config_entries"),
        "homeassistant.core": types.ModuleType("homeassistant.core"),
        "homeassistant.exceptions": types.ModuleType("homeassistant.exceptions"),
        "homeassistant.helpers": types.ModuleType("homeassistant.helpers"),
        "homeassistant.helpers.aiohttp_client": types.ModuleType("homeassistant.helpers.aiohttp_client"),
    }
    modules["homeassistant.config_entries"].ConfigEntry = ConfigEntry
    modules["homeassistant.core"].HomeAssistant = FakeHass
    modules["homeassistant.core"].ServiceCall = ServiceCall
    modules["homeassistant.exceptions"].ServiceValidationError = ServiceValidationError
    modules["homeassistant.helpers.aiohttp_client"].async_get_clientsession = lambda hass: object()
    for name, module in modules.items():
        monkeypatch.setitem(sys.modules, name, module)

    coordinator = types.ModuleType("plant_helper.coordinator")
    coordinator.PlantHelperCoordinator = FakeCoordinator
    monkeypatch.setitem(sys.modules, "plant_helper.coordinator", coordinator)

    enrichment = types.ModuleType("plant_helper.enrichment")
    enrichment.summarize_enrichment = lambda value: value or {}
    monkeypatch.setitem(sys.modules, "plant_helper.enrichment", enrichment)

    learned = types.ModuleType("plant_helper.learned_store")
    learned.LearnedStore = FakeStore

    def reset_placement(data, plant_id, placement):
        data.setdefault("reset", []).append((plant_id, placement))
        return True

    learned.reset_placement = reset_placement
    monkeypatch.setitem(sys.modules, "plant_helper.learned_store", learned)

    api = types.ModuleType("plant_helper.plant_data_api")
    api.PlantDataAPI = FakeApi
    monkeypatch.setitem(sys.modules, "plant_helper.plant_data_api", api)

    samples = types.ModuleType("plant_helper.sample_store")
    samples.SampleStore = FakeStore

    def clear_key_prefix(data, prefix):
        data.setdefault("cleared", []).append(prefix)

    samples.clear_key_prefix = clear_key_prefix
    monkeypatch.setitem(sys.modules, "plant_helper.sample_store", samples)

    storage = types.ModuleType("plant_helper.storage")
    storage.PlantStorage = FakeStore
    monkeypatch.setitem(sys.modules, "plant_helper.storage", storage)


def _load_module(monkeypatch):
    FakeStore.instances.clear()
    FakeApi.instances.clear()
    FakeCoordinator.instances.clear()
    _install_stubs(monkeypatch)
    sys.modules.pop(MODULE_NAME, None)
    loader = SourceFileLoader(MODULE_NAME, str(ROOT / "__init__.py"))
    spec = importlib.util.spec_from_loader(MODULE_NAME, loader, is_package=False)
    module = importlib.util.module_from_spec(spec)
    sys.modules[MODULE_NAME] = module
    spec.loader.exec_module(module)
    return module


async def test_setup_loads_stores_refreshes_forwards_and_registers(monkeypatch):
    module = _load_module(monkeypatch)
    hass = FakeHass()
    entry = ConfigEntry(options={"update_interval": 420, "radiation_source": "auto"})

    assert await module.async_setup_entry(hass, entry) is True
    runtime = hass.data[module.DOMAIN][entry.entry_id]
    assert all(store.loaded for store in FakeStore.instances)
    assert runtime["coordinator"].first_refresh is True
    assert hass.config_entries.forwarded == [(entry.entry_id, ("sensor", "binary_sensor"))]
    assert len(entry.listeners) == 1 and len(entry.unloads) == 1
    assert (module.DOMAIN, "recalibrate") in hass.services.handlers
    assert (module.DOMAIN, "refresh_species") in hass.services.handlers
    assert runtime["plants"]["fern"]["name"] == "Fern"
    assert runtime["coordinator"].kwargs["update_interval_seconds"] == 420


async def test_options_listener_reloads_exact_entry(monkeypatch):
    module = _load_module(monkeypatch)
    hass = FakeHass()
    entry = ConfigEntry(entry_id="reload-me")
    await module._async_reload_entry(hass, entry)
    assert hass.config_entries.reloaded == ["reload-me"]


async def test_unload_failure_preserves_runtime_and_services(monkeypatch):
    module = _load_module(monkeypatch)
    hass = FakeHass()
    entry = ConfigEntry()
    await module.async_setup_entry(hass, entry)
    hass.config_entries.unload_result = False

    assert await module.async_unload_entry(hass, entry) is False
    assert entry.entry_id in hass.data[module.DOMAIN]
    assert hass.services.has_service(module.DOMAIN, "recalibrate")
    assert FakeCoordinator.instances[-1].shutdown is False


async def test_successful_last_unload_shutdowns_saves_and_removes_services(monkeypatch):
    module = _load_module(monkeypatch)
    hass = FakeHass()
    entry = ConfigEntry()
    await module.async_setup_entry(hass, entry)
    runtime = hass.data[module.DOMAIN][entry.entry_id]

    assert await module.async_unload_entry(hass, entry) is True
    assert entry.entry_id not in hass.data[module.DOMAIN]
    assert runtime["coordinator"].shutdown is True
    assert runtime["learned"].saved is True
    assert runtime["samples"].saved is True
    assert not hass.services.has_service(module.DOMAIN, "recalibrate")
    assert not hass.services.has_service(module.DOMAIN, "refresh_species")


async def test_services_execute_against_loaded_runtime(monkeypatch):
    module = _load_module(monkeypatch)
    hass = FakeHass()
    entry = ConfigEntry()
    await module.async_setup_entry(hass, entry)
    runtime = hass.data[module.DOMAIN][entry.entry_id]

    recalibrate = hass.services.handlers[(module.DOMAIN, "recalibrate")]
    await recalibrate(ServiceCall({"plant_id": "fern"}))
    assert runtime["learned"].data["reset"] == [("fern", "indoor")]
    assert runtime["samples"].data["cleared"] == ["plant:fern:"]
    assert runtime["coordinator"].refreshes == 1

    refresh = hass.services.handlers[(module.DOMAIN, "refresh_species")]
    await refresh(ServiceCall({"plant_id": "fern"}))
    assert runtime["api"].calls == [("Nephrolepis exaltata", True)]
    assert hass.config_entries.reloaded == [entry.entry_id]


async def test_services_reject_unknown_plant(monkeypatch):
    module = _load_module(monkeypatch)
    hass = FakeHass()
    entry = ConfigEntry()
    await module.async_setup_entry(hass, entry)

    for service in ("recalibrate", "refresh_species"):
        handler = hass.services.handlers[(module.DOMAIN, service)]
        with pytest.raises(ServiceValidationError, match="Unknown Plant Helper plant_id"):
            await handler(ServiceCall({"plant_id": "missing"}))
