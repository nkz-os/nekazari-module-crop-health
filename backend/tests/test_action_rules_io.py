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


from datetime import date
from app.services.action_rules_io import build_operation_entity


def test_build_operation_entity_shape():
    rule = {"id": "cover_crop_termination_flowering", "category": "termination",
            "action": {"operation_type": "tillage", "urgency": "high", "window_days": 7,
                       "description_template": "Tumbar {crop.species} con roller crimper"}}
    ctx = {"crop": {"species": "Vicia sativa"}}
    e = build_operation_entity("urn:ngsi-ld:AgriParcel:montiko:p1",
                               {"id": "urn:ngsi-ld:AgriCrop:montiko:p1:2026:0"},
                               rule, ctx, "montiko", date(2026, 3, 1))
    assert e["type"] == "AgriParcelOperation"
    assert e["operationType"]["value"] == "tillage"
    assert e["status"]["value"] == "issued"
    assert e["sourceRule"]["value"] == "cover_crop_termination_flowering"
    assert e["hasAgriParcel"]["object"] == "urn:ngsi-ld:AgriParcel:montiko:p1"
    assert e["hasAgriCrop"]["object"] == "urn:ngsi-ld:AgriCrop:montiko:p1:2026:0"
    assert "Vicia sativa" in e["description"]["value"]   # template rendered
    assert e["plannedEndDate"]["value"] == "2026-03-08"  # today + 7d
