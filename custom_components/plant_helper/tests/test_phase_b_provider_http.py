"""Provider HTTP-workflow regression tests for Phase B."""
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
    def __init__(self, payload, status=200, text=""):
        self.payload = payload
        self.status = status
        self._text = text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def json(self, **_kwargs):
        return self.payload

    async def text(self):
        return self._text


class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


async def run() -> None:
    # Trefle search and detail are one provider workflow but two real calls.
    trefle_session = Session([
        Response({"data": [{
            "scientific_name": "Dracaena trifasciata",
            "slug": "dracaena-trifasciata",
            "links": {"self": "/api/v1/species/dracaena-trifasciata"},
        }]}),
        Response({"data": {
            "scientific_name": "Dracaena trifasciata",
            "growth": {"light": 7, "soil_humidity": 3},
        }}),
    ])
    trefle = TrefleProvider(
        session=trefle_session, api_key="token", min_interval_seconds=0.001
    )
    result = await trefle.fetch("Dracaena trifasciata")
    assert result.found and result.calls_made == 2
    assert len(trefle_session.calls) == 2
    assert result.data["growth"]["light"] == 7

    # iNaturalist sparse taxon uses an observation-photo fallback.
    inat_session = Session([
        Response({"results": [{
            "id": 7,
            "name": "Dracaena trifasciata",
            "iconic_taxon_name": "Plantae",
            "ancestors": [],
        }]}),
        Response({"results": [{"photos": [{"url": "https://img/square.jpg"}]}]}),
    ])
    inat = INaturalistProvider(session=inat_session, min_interval_seconds=0.001)
    result = await inat.resolve("snake plant")
    assert result.found and result.calls_made == 2
    assert len(inat_session.calls) == 2
    assert result.data["photo"] == "https://img/medium.jpg"

    # Daily cap prevents a request and reports zero actual calls.
    capped_session = Session([])
    capped = INaturalistProvider(session=capped_session, daily_limit=0)
    result = await capped.resolve("snake plant")
    assert not result.found
    assert result.calls_made == 0
    assert capped_session.calls == []


asyncio.run(run())
