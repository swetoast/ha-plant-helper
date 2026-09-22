"""Perenual free/paid access and payload cleanup regression tests."""
import asyncio
from plant_helper.api.perenual import PerenualProvider

class Response:
    def __init__(self, payload=None, status=200, text="", headers=None):
        self.payload, self.status, self._text = payload, status, text
        self.headers = headers or {}
    async def __aenter__(self): return self
    async def __aexit__(self, *args): return False
    async def json(self, content_type=None): return self.payload
    async def text(self): return self._text

class Session:
    def __init__(self, responses): self.responses=list(responses); self.urls=[]
    def get(self, url, params=None, timeout=None):
        self.urls.append((url, params)); return self.responses.pop(0)


def run(coro): return asyncio.run(coro)

def test_free_restricted_id_keeps_search_and_avoids_wasted_calls():
    search={"data":[{"id":5257,"common_name":"Swiss cheese plant","scientific_name":["Monstera deliciosa"],"family":"Araceae","hybrid":None,"default_image":{"regular_url":"https://host/upgrade_access.jpg"}}]}
    session=Session([Response(search)])
    result=run(PerenualProvider(session=session,api_key="x").fetch("Monstera deliciosa"))
    assert result.found and result.calls_made == 1
    assert result.data["provider_id"] == 5257
    assert result.data["perenual_access"] == "upgrade_required"
    assert "hybrid" not in result.data and "default_image" not in result.data
    assert len(session.urls) == 1

def test_free_accessible_detail_cleans_restricted_and_secret_values():
    search={"data":[{"id":1,"scientific_name":["Abies alba"]}]}
    detail={"id":1,"common_name":"European Silver Fir","scientific_name":["Abies alba"],"seeds":False,"medicinal":True,"maintenance":None,"hardiness":{"min":"7","max":"7"},"hardiness_location":{"full_url":"https://x?key=secret"},"other_images":"Upgrade Plan To Supreme For Access","default_image":{"regular_url":"https://img/real.jpg","license_name":"CC BY-SA"}}
    session=Session([Response(search),Response(detail)])
    result=run(PerenualProvider(session=session,api_key="x").fetch("Abies alba",fetch_care_guides=False,fetch_diseases=False))
    assert result.data["seeds"] is False and result.data["medicinal"] is True
    assert result.data["hardiness_min"] == "7" and "hardiness_location" not in result.data
    assert "maintenance" not in result.data and "other_images" not in result.data
    assert "key=" not in repr(result.data)

def test_paid_attempts_restricted_detail_and_429_does_not_block_provider():
    search={"data":[{"id":5257,"scientific_name":["Monstera deliciosa"],"family":"Araceae"}]}
    session=Session([Response(search),Response(status=429,text="Please Upgrade Plan")])
    provider=PerenualProvider(session=session,api_key="x",access_level="paid")
    result=run(provider.fetch("Monstera deliciosa",fetch_care_guides=False,fetch_diseases=False))
    assert result.found and result.data["perenual_access"] == "upgrade_required"
    assert provider._blocked_until is None
    assert len(session.urls) == 2
