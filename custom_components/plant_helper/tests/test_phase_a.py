"""Phase A regression tests."""
from __future__ import annotations

import asyncio
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if "plant_helper" not in sys.modules:
    pkg = types.ModuleType("plant_helper")
    pkg.__path__ = [str(ROOT)]
    sys.modules["plant_helper"] = pkg

from plant_helper.api.inaturalist import INaturalistProvider
from plant_helper.api.trefle import TrefleProvider


class Response:
    def __init__(self, payload, status=200):
        self.payload = payload
        self.status = status

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self, **_kwargs):
        return self.payload

    async def text(self):
        return ""


class Session:
    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return Response(self.payloads.pop(0))


async def check_providers():
    trefle_session = Session([
        {"data": [{"scientific_name": "Dracaena trifasciata", "slug": "dracaena-trifasciata", "links": {"self": "/api/v1/species/dracaena-trifasciata"}}]},
        {"data": {"scientific_name": "Dracaena trifasciata", "growth": {"light": 7}}},
    ])
    trefle = TrefleProvider(session=trefle_session, api_key="x", min_interval_seconds=0.01)
    result = await trefle.fetch("Dracaena trifasciata")
    assert result.found and len(trefle_session.calls) == 2
    assert result.calls_made == 2 and result.data["growth"]["light"] == 7

    inat_session = Session([
        {"results": [{"id": 1, "name": "Dracaena trifasciata", "iconic_taxon_name": "Plantae", "ancestors": []}]},
        {"results": [{"photos": [{"url": "https://img/square.jpg"}]}]},
    ])
    inat = INaturalistProvider(session=inat_session, min_interval_seconds=0.01)
    result = await inat.resolve("snake plant")
    assert result.found and len(inat_session.calls) == 2
    assert result.calls_made == 2
    assert result.data["photo"] == "https://img/medium.jpg"


asyncio.run(check_providers())

init_text = (ROOT / "__init__.py").read_text()
assert "radiation_source = _opt(CONF_RADIATION_SOURCE" in init_text
assert "update_interval_seconds=update_interval" in init_text
flow_text = (ROOT / "config_flow.py").read_text()
assert "permanently deletes its device" in flow_text
coord_text = (ROOT / "coordinator.py").read_text()
assert "source_ts" in coord_text and "current_reading_stale" in coord_text
print("PHASE A REGRESSION TESTS PASSED")
