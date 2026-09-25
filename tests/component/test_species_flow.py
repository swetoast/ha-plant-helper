"""Drive the real options flow through per-provider species matching.

Home Assistant itself is not importable here, so the few flow and selector APIs
the options flow uses are stubbed; everything else is real: options.py, plant
storage, the runtime collection, and the add/edit domain paths. Provider
searches are served from recorded live responses.
"""
from __future__ import annotations

import asyncio
import copy
import importlib
import json
import sys
import types
from pathlib import Path

import pytest

pytest.importorskip("voluptuous")

ROOT = Path(__file__).resolve().parents[2]
PACKAGE_DIR = ROOT / "custom_components" / "plant_helper"
FIXTURES = ROOT / "tests" / "fixtures"


def _install_ha_stubs() -> None:
    if "homeassistant.config_entries" in sys.modules:
        return

    class OptionsFlow:
        def async_show_form(self, *, step_id, data_schema=None, errors=None,
                            description_placeholders=None):
            return {"type": "form", "step_id": step_id, "schema": data_schema,
                    "errors": errors or {}, "placeholders": description_placeholders or {}}

        def async_show_menu(self, *, step_id, menu_options):
            return {"type": "menu", "step_id": step_id, "menu_options": menu_options}

        def async_abort(self, *, reason):
            return {"type": "abort", "reason": reason}

        def async_create_entry(self, *, title, data):
            return {"type": "create_entry", "data": data}

        def add_suggested_values_to_schema(self, schema, _values):
            return schema

    class _Config:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _Selector:
        def __init__(self, config=None):
            self.config = config

        def __call__(self, value):  # voluptuous validators are callables
            return value

    selector = types.SimpleNamespace(
        SelectSelector=_Selector, SelectSelectorConfig=_Config,
        SelectSelectorMode=types.SimpleNamespace(LIST="list", DROPDOWN="dropdown"),
        TextSelector=_Selector, EntitySelector=_Selector, EntitySelectorConfig=_Config,
        NumberSelector=_Selector, NumberSelectorConfig=_Config,
        NumberSelectorMode=types.SimpleNamespace(BOX="box"),
    )
    config_entries = types.ModuleType("homeassistant.config_entries")
    config_entries.OptionsFlow = OptionsFlow
    config_entries.ConfigFlowResult = dict
    helpers = types.ModuleType("homeassistant.helpers")
    helpers.selector = selector
    ha = types.ModuleType("homeassistant")
    ha.config_entries = config_entries
    sys.modules.update({
        "homeassistant": ha,
        "homeassistant.config_entries": config_entries,
        "homeassistant.helpers": helpers,
        "homeassistant.helpers.selector": selector,
    })


def _load_options():
    _install_ha_stubs()
    package = types.ModuleType("ph_flow_pkg")
    package.__path__ = [str(PACKAGE_DIR)]
    sys.modules.setdefault("ph_flow_pkg", package)
    return importlib.import_module("ph_flow_pkg.options")


options = _load_options()
enrichment = importlib.import_module("ph_flow_pkg.domain.enrichment")
storage_mod = importlib.import_module("ph_flow_pkg.domain.storage")
runtime_mod = importlib.import_module("ph_flow_pkg.domain.runtime")


def _served(name):
    raw = json.loads((FIXTURES / name).read_text())
    return {"http_status": raw.get("http_status", 200), "body": raw.get("body", raw)}


class _Backend:
    def __init__(self):
        self.data = None

    async def async_load(self):
        return copy.deepcopy(self.data)

    async def async_save(self, data):
        self.data = copy.deepcopy(data)


class _Runtime:
    def __init__(self, adapters):
        self.provider_adapters = adapters
        self.perenual_free = True
        self.storage = storage_mod.PlantHelperStorage(_Backend())
        asyncio.run(self.storage.async_load())
        self.plants = runtime_mod.RuntimeCollection()
        self.platform_callbacks = {}
        self.enriched = []

    def require_storage(self):
        return self.storage

    async def _noop(self, *_args, **_kwargs):
        return None

    register_listeners = replace_listeners = evaluate = _noop
    handle_placement_change = handle_species_change = schedule_reconciliation = _noop

    async def schedule_enrichment(self, plant_uuid, species):
        self.enriched.append((plant_uuid, species))

    def destination_baseline_complete(self, *_args):
        return False


PERENUAL_QUERIES: list[str] = []


def _adapters():
    async def inaturalist(_query):
        return _served("inaturalist/inaturalist_dracaena_trifasciata.json")

    async def trefle(query):
        # Serve the live response only for the accepted name, as Trefle would
        # for a synonym it does not index; the flow must still find it.
        if "dracaena" in query.casefold():
            return _served("trefle/dracaena_trifasciata_search.json")
        return {"http_status": 200, "body": {"data": []}}

    async def perenual(query):
        # Live free-plan responses: the current name is absent, the older name
        # finds the species (behind the paywall), "snake plant" finds others.
        PERENUAL_QUERIES.append(query)
        name = query.casefold()
        if "dracaena" in name:
            return _served("perenual/dracaena_trifasciata_search.json")
        if "sansevieria" in name:
            return _served("perenual/sansevieria_trifasciata_search.json")
        return _served("perenual/snake_plant_search.json")

    PERENUAL_QUERIES.clear()
    return {
        "inaturalist": enrichment.INaturalistAdapter(inaturalist),
        "trefle": enrichment.TrefleAdapter(trefle),
        "perenual": enrichment.PerenualAdapter(perenual, "k"),
    }


def _flow(runtime):
    flow = options.PlantHelperOptionsFlow()
    flow.config_entry = types.SimpleNamespace(runtime_data=runtime, options={"latitude": 1})
    state = types.SimpleNamespace(state="40")
    flow.hass = types.SimpleNamespace(states=types.SimpleNamespace(get=lambda _entity: state))
    flow._placement = "indoor"
    return flow


def _choices(result):
    config = result["schema"].schema
    field = next(iter(config))
    return [o["value"] for o in config[field].config.options], field.default()


def _run(coro):
    return asyncio.run(coro)


def _add(flow):
    return _run(flow.async_step_add_plant({
        "display_name": "Snake Plant", "soil_moisture": "sensor.m", "profile": "dry"}))


def _stored(runtime):
    snapshot = _run(runtime.storage.async_snapshot())
    return next(iter(snapshot.data["plants"].values()))


def test_add_walks_each_provider_and_stores_the_chosen_records():
    runtime = _Runtime(_adapters())
    flow = _flow(runtime)
    step = _add(flow)
    assert step["step_id"] == "species_inaturalist"
    values, default = _choices(step)
    assert default == values[0] != "skip" and values[-1] == "skip"

    step = _run(flow.async_step_species_inaturalist({"candidate": default}))
    assert step["step_id"] == "species_trefle"
    values, default = _choices(step)
    # iNaturalist's name is the old synonym; the accepted Trefle species is
    # found through the synonym and preselected, the subspecies is not.
    assert values[:2] == ["375325", "453823"] and default == "375325"

    step = _run(flow.async_step_species_trefle({"candidate": "375325"}))
    assert step["step_id"] == "species_perenual"
    values, default = _choices(step)
    # Found through the older name after the current one came back empty, and
    # the search stops there instead of spending a third request.
    assert PERENUAL_QUERIES == ["Dracaena trifasciata", "Sansevieria trifasciata"]
    # On the free plan only records the key can open are offered. Every
    # snake-plant record is paid-only, so the step says so and offers Skip.
    assert values == ["skip"] and default == "skip"
    assert "only paid plans" in step["placeholders"]["status"]

    done = _run(flow.async_step_species_perenual({"candidate": "skip"}))
    assert done["type"] == "create_entry" and done["data"] == {"latitude": 1}
    record = _stored(runtime)
    assert record["species"] == "Dracaena trifasciata"  # Trefle's accepted name
    sources = record["species_sources"]
    assert sources["inaturalist"]["name"] == "Sansevieria trifasciata"
    assert sources["inaturalist"]["image_url"].startswith("https://")
    assert sources["trefle"] == {"id": 375325, "name": "Dracaena trifasciata"}
    assert sources["perenual"] == "skip"
    assert runtime.enriched and runtime.enriched[0][1] == "Dracaena trifasciata"


def test_skipping_every_provider_adds_the_plant_without_species():
    runtime = _Runtime(_adapters())
    flow = _flow(runtime)
    _add(flow)
    _run(flow.async_step_species_inaturalist({"candidate": "skip"}))
    _run(flow.async_step_species_trefle({"candidate": "skip"}))
    done = _run(flow.async_step_species_perenual({"candidate": "skip"}))
    assert done["type"] == "create_entry"
    record = _stored(runtime)
    assert record["species"] is None and runtime.enriched == []


def test_unconfigured_providers_are_not_asked_about():
    adapters = _adapters()
    runtime = _Runtime({"inaturalist": adapters["inaturalist"]})  # no API keys
    flow = _flow(runtime)
    step = _add(flow)
    _values, default = _choices(step)
    done = _run(flow.async_step_species_inaturalist({"candidate": default}))
    assert done["type"] == "create_entry"
    assert set(_stored(runtime)["species_sources"]) == {"inaturalist"}


def test_provider_failure_shows_why_and_still_allows_skip():
    async def broken(_query):
        raise enrichment.ProviderError("auth", 401)

    adapters = _adapters()
    adapters["trefle"] = enrichment.TrefleAdapter(broken)
    runtime = _Runtime(adapters)
    flow = _flow(runtime)
    step = _add(flow)
    step = _run(flow.async_step_species_inaturalist({"candidate": _choices(step)[1]}))
    assert step["step_id"] == "species_trefle"
    assert _choices(step)[0] == ["skip"]
    assert "rejected" in step["placeholders"]["status"]


def test_rematch_changes_only_the_species_data_and_re_enriches():
    runtime = _Runtime(_adapters())
    flow = _flow(runtime)
    step = _add(flow)
    step = _run(flow.async_step_species_inaturalist({"candidate": _choices(step)[1]}))
    _run(flow.async_step_species_trefle({"candidate": "skip"}))
    _run(flow.async_step_species_perenual({"candidate": "skip"}))
    uuid = next(iter(runtime.plants.plants))
    runtime.enriched.clear()

    rematch = _flow(runtime)
    step = _run(rematch.async_step_species({"plant_uuid": uuid}))
    step = _run(rematch.async_step_species_inaturalist({"candidate": _choices(step)[1]}))
    _run(rematch.async_step_species_trefle({"candidate": "375325"}))
    done = _run(rematch.async_step_species_perenual({"candidate": "skip"}))
    assert done["type"] == "create_entry"
    record = _stored(runtime)
    assert record["species_sources"]["trefle"]["id"] == 375325
    assert record["soil_moisture"] == "sensor.m" and record["profile"] == "dry"
    assert runtime.enriched == [(uuid, "Dracaena trifasciata")]


def test_ordinary_edit_keeps_the_chosen_records():
    runtime = _Runtime(_adapters())
    flow = _flow(runtime)
    step = _add(flow)
    step = _run(flow.async_step_species_inaturalist({"candidate": _choices(step)[1]}))
    _run(flow.async_step_species_trefle({"candidate": "375325"}))
    _run(flow.async_step_species_perenual({"candidate": "skip"}))
    uuid = next(iter(runtime.plants.plants))

    edit = _flow(runtime)
    _run(edit.async_step_edit({"plant_uuid": uuid}))
    _run(edit.async_step_edit_placement({"placement": "indoor"}))
    done = _run(edit.async_step_edit_plant({
        "display_name": "Snake Plant", "soil_moisture": "sensor.m", "profile": "balanced"}))
    assert done["type"] == "create_entry"
    record = _stored(runtime)
    assert record["profile"] == "balanced"
    assert record["species_sources"]["trefle"]["id"] == 375325
    assert record["species"] == "Dracaena trifasciata"


def test_paid_plan_lists_every_record_and_flags_a_key_that_looks_free():
    runtime = _Runtime(_adapters())
    runtime.perenual_free = False
    flow = _flow(runtime)
    step = _add(flow)
    step = _run(flow.async_step_species_inaturalist({"candidate": _choices(step)[1]}))
    step = _run(flow.async_step_species_trefle({"candidate": "375325"}))
    values, default = _choices(step)
    assert values[0] == "7171" and "7172" in values
    # These live results came from a free key (placeholder images), so a
    # "paid" setting is contradicted and the step says so.
    assert "looks like a free plan" in step["placeholders"]["status"]
    assert default == "skip"
    done = _run(flow.async_step_species_perenual({"candidate": "7171"}))
    assert done["type"] == "create_entry"
    assert _stored(runtime)["species_sources"]["perenual"] == {"id": 7171, "name": "Sansevieria trifasciata"}

