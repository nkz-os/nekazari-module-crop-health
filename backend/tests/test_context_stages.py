"""Tests for context_client.get_phenology_stages() and the default fallback table."""

import pytest
from app.services import context_client


@pytest.mark.asyncio
async def test_returns_table_from_bioorch(monkeypatch):
    class _Resp:
        status_code = 200
        def json(self):
            return {"species": "Zea mays", "stages": [
                {"stage": "emergence", "gddMin": 0, "gddMax": 90, "baseTemp": 10.0},
                {"stage": "vegetative", "gddMin": 90, "gddMax": 520, "baseTemp": 10.0},
            ]}
    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _Resp()
    monkeypatch.setattr(context_client.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(context_client.get_settings(), "bioorchestrator_url", "http://bio", raising=False)
    table = await context_client.get_phenology_stages("Zea mays")
    assert table.stages["emergence"] == (0.0, 90.0)
    assert table.stages["vegetative"] == (90.0, 520.0)
    assert table.base_temp == 10.0


@pytest.mark.asyncio
async def test_falls_back_to_default_when_empty(monkeypatch):
    class _Resp:
        status_code = 200
        def json(self): return {"species": "x", "stages": []}
    class _Client:
        def __init__(self, *a, **k): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): return _Resp()
    monkeypatch.setattr(context_client.httpx, "AsyncClient", _Client)
    monkeypatch.setattr(context_client.get_settings(), "bioorchestrator_url", "http://bio", raising=False)
    table = await context_client.get_phenology_stages("unknown-crop")
    assert table == context_client._DEFAULT_STAGE_TABLE
