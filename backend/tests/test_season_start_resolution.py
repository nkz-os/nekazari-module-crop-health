import pytest
from datetime import date

import app.services.context_client as cc


@pytest.mark.asyncio
async def test_season_start_from_platform(monkeypatch):
    async def fake(urn, tenant):
        return {"accumulation": {"start": "2026-03-12", "basis": "cycle_start"}}
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
    # planned sowing in the future -> no current cycle -> 1-ene, never the future date or 1-mar
    assert await cc.resolve_season_start("p1", "t") == date(date.today().year, 1, 1).isoformat()
