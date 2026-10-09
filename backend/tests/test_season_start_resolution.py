import pytest
from datetime import date

import app.services.context_client as cc


@pytest.mark.asyncio
async def test_season_start_from_platform(monkeypatch):
    async def fake(urn, tenant):
        return {"current": {"start": {"date": "2026-03-12"}},
                "accumulation": {"start": "2026-03-12", "basis": "cycle_start"}}
    monkeypatch.setattr(cc, "_fetch_platform_crop_cycles", fake)
    assert await cc.resolve_season_start("p1", "t") == "2026-03-12"


@pytest.mark.asyncio
async def test_season_start_fallback_uses_sdk(monkeypatch):
    async def down(urn, tenant):
        return None
    async def crops(urn, tenant):
        return [{"id": "c", "refAgriParcel": urn, "status": "active", "plantingDate": "2026-10-15"}], []
    monkeypatch.setattr(cc, "_fetch_platform_crop_cycles", down)
    monkeypatch.setattr(cc, "_read_crops_and_operations", crops)
    # planned sowing in the future -> not sown -> no season start (never the future date or 1-mar)
    assert await cc.resolve_season_start("p1", "t") is None


@pytest.mark.asyncio
async def test_not_sown_yet_has_no_season_start(monkeypatch):
    async def fake(urn, tenant):
        return {"current": None, "next": {"start": {"date": "2026-10-15"}},
                "accumulation": {"start": "2026-01-01", "basis": "calendar_year"}}
    monkeypatch.setattr(cc, "_fetch_platform_crop_cycles", fake)
    assert await cc.resolve_season_start("p1", "t") is None


@pytest.mark.asyncio
async def test_fallback_reads_only_boundary_operations_and_pages(monkeypatch):
    calls = []

    class FakeOrion:
        def __init__(self, *a, **k):
            pass

        async def query_entities(self, type=None, q=None, limit=100, offset=0, options=None):
            calls.append({"type": type, "q": q, "offset": offset, "limit": limit})
            if type == "AgriParcelOperation" and offset < 1000:
                return [{"id": f"op{offset + i}"} for i in range(limit)]
            return []

        async def close(self):
            pass

    monkeypatch.setattr(cc, "OrionClient", FakeOrion)
    crops, ops = await cc._read_crops_and_operations("urn:ngsi-ld:AgriParcel:p1", "t")
    op_calls = [c for c in calls if c["type"] == "AgriParcelOperation"]
    assert len(ops) == 1000 and [c["offset"] for c in op_calls] == [0, 500, 1000]
    assert 'operationType=="sowing","harvesting","tillage"' in op_calls[0]["q"]
