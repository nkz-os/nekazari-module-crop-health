import pytest
from app.services import action_rules_io as io


class _Orion:
    def __init__(self, rows): self._rows = rows
    async def query_entities(self, **kw): self.kw = kw; return self._rows
    async def close(self): pass


@pytest.mark.asyncio
async def test_find_active_parcels_dedups(monkeypatch):
    rows = [{"id": "c1", "status": "active", "hasAgriParcel": "urn:p:1"},
            {"id": "c2", "status": "planned", "hasAgriParcel": "urn:p:1"},
            {"id": "c3", "status": "active", "hasAgriParcel": "urn:p:2"}]
    monkeypatch.setattr(io, "OrionClient", lambda *a, **k: _Orion(rows))
    out = await io._find_active_parcels("montiko")
    assert sorted(out) == ["urn:p:1", "urn:p:2"]


@pytest.mark.asyncio
async def test_get_action_rules_failsafe_empty(monkeypatch):
    class _C:
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return False
        async def get(self, *a, **k): raise RuntimeError("bioorch down")
    monkeypatch.setattr(io.httpx, "AsyncClient", lambda *a, **k: _C())
    assert await io.get_action_rules("Vicia", "flowering", "cover_crop", "montiko") == []
