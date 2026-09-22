"""Regression tests for Perenual 429 handling."""
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

from plant_helper.api.perenual import PerenualProvider

class Response:
    def __init__(self, payload, status=200, headers=None):
        self.payload = payload
        self.status = status
        self.headers = headers or {}
    async def __aenter__(self): return self
    async def __aexit__(self, *_args): return False
    async def json(self, **_kwargs): return self.payload

class Session:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.responses.pop(0)


def test_perenual_429_honors_retry_after_without_retry_loop():
    async def scenario():
        session = Session([Response({"error": "Too Many Requests"}, 429, {"Retry-After": "120"})])
        provider = PerenualProvider(session=session, api_key="secret")
        first = await provider.fetch("Monstera deliciosa")
        assert not first.found
        assert first.api_called
        assert "retry after 120 seconds" in first.message
        assert len(session.calls) == 1
        second = await provider.fetch("Monstera deliciosa")
        assert not second.found
        assert not second.api_called
        assert len(session.calls) == 1
    asyncio.run(scenario())
