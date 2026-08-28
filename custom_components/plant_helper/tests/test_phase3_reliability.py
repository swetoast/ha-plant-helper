"""Phase 3 provider, service, and storage reliability regressions."""
from __future__ import annotations

import asyncio
from pathlib import Path

from plant_helper.api.inaturalist import INaturalistProvider
from plant_helper.api.perenual import PerenualProvider
from plant_helper.api.trefle import TrefleProvider

ROOT = Path(__file__).resolve().parents[1]


class Response:
    def __init__(self, payload=None, *, status=200, text=""):
        self.payload = payload or {}
        self.status = status
        self.body = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self, **_kwargs):
        return self.payload

    async def text(self):
        return self.body


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        item = self.responses.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_inaturalist_photo_fallback_does_not_require_research_grade():
    async def run():
        session = Session([
            Response({"results": [{
                "id": 7, "name": "Dracaena trifasciata",
                "iconic_taxon_name": "Plantae", "ancestors": [],
            }]}),
            Response({"results": [{"photos": [{"url": "https://img/square.jpg"}]}]}),
        ])
        provider = INaturalistProvider(session=session, min_interval_seconds=0)
        result = await provider.resolve("snake plant")
        assert result.found and result.calls_made == 2
        observation_params = session.calls[1][1]["params"]
        assert observation_params["photos"] == "true"
        assert "quality_grade" not in observation_params
    asyncio.run(run())


def test_provider_http_diagnostics_never_expose_response_bodies():
    async def run():
        secret = "remote-body-with-private-details"
        cases = [
            (INaturalistProvider(session=Session([Response(status=403, text=secret)]), min_interval_seconds=0), "resolve", "fern", "iNaturalist HTTP 403"),
            (PerenualProvider(session=Session([Response(status=500, text=secret)]), api_key="x"), "fetch", "fern", "Perenual HTTP 500"),
            (TrefleProvider(session=Session([Response(status=500, text=secret)]), api_key="x", min_interval_seconds=0), "fetch", "fern", "Trefle HTTP 500"),
        ]
        for provider, method, query, expected in cases:
            result = await getattr(provider, method)(query)
            assert result.calls_made == 1
            assert provider.last_error == expected
            assert secret not in provider.last_error
            assert secret not in result.message
    asyncio.run(run())


def test_exception_paths_report_actual_http_call_count():
    async def run():
        providers = [
            (INaturalistProvider(session=Session([RuntimeError("boom")]), min_interval_seconds=0), "resolve"),
            (PerenualProvider(session=Session([RuntimeError("boom")]), api_key="x"), "fetch"),
            (TrefleProvider(session=Session([RuntimeError("boom")]), api_key="x", min_interval_seconds=0), "fetch"),
        ]
        for provider, method in providers:
            result = await getattr(provider, method)("fern")
            assert result.calls_made == 1
            assert result.api_called is True
            assert "boom" not in result.message
    asyncio.run(run())


def test_service_handlers_raise_actionable_validation_errors():
    source = (ROOT / "__init__.py").read_text(encoding="utf-8")
    assert "from homeassistant.exceptions import ServiceValidationError" in source
    assert 'raise ServiceValidationError("plant_id is required")' in source
    assert "Unknown Plant Helper plant_id" in source
    assert "Plant has no species configured" in source
    assert "Species refresh failed for plant_id" in source


def test_main_storage_load_recovers_without_overwriting_bad_payload():
    source = (ROOT / "storage.py").read_text(encoding="utf-8")
    load = source[source.index("async def async_load"):source.index("async def async_save")]
    assert "except Exception" in load
    assert "isinstance(data, dict)" in load
    assert 'self._data = {"plants": {}, "user_plants": {}}' in load
    assert "async_save" not in load
