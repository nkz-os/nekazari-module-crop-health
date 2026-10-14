"""Season start comes from the platform crop-cycle rule, read from the broker by the SDK."""
import pytest

import app.services.context_client as cc


def _timeline(current, acc="2026-03-12", basis="cycle_start"):
    return {"current": current, "accumulation": {"start": acc, "basis": basis}}


@pytest.mark.asyncio
async def test_season_start_is_the_accumulation_start_of_the_current_cycle(monkeypatch):
    seen = {}

    async def fake(tenant_id, parcel_id, at=None, *, base_url=None, context_url=None):
        seen.update(tenant=tenant_id, parcel=parcel_id, base_url=base_url, context_url=context_url)
        return _timeline({"start": {"date": "2026-03-12", "provenance": "actual"}})

    monkeypatch.setattr(cc, "fetch_crop_timeline", fake)
    assert await cc.resolve_season_start("p1", "t") == "2026-03-12"
    settings = cc.get_settings()
    assert seen == {"tenant": "t", "parcel": "urn:ngsi-ld:AgriParcel:p1",
                    "base_url": settings.orion_ld_url, "context_url": settings.orion_ld_context}


@pytest.mark.asyncio
async def test_not_sown_yet_has_no_season_start(monkeypatch):
    async def fake(*a, **k):
        return {"current": None, "pending": {"start": {"date": "2026-10-01", "provenance": "planned"}},
                "accumulation": {"start": "2026-01-01", "basis": "calendar_year"}}

    monkeypatch.setattr(cc, "fetch_crop_timeline", fake)
    assert await cc.resolve_season_start("p1", "t") is None


@pytest.mark.asyncio
async def test_broker_unavailable_has_no_season_start(monkeypatch):
    async def fake(*a, **k):
        return None

    monkeypatch.setattr(cc, "fetch_crop_timeline", fake)
    assert await cc.resolve_season_start("urn:ngsi-ld:AgriParcel:p1", "t") is None


def test_no_core_endpoint_left():
    import inspect

    src = inspect.getsource(cc)
    assert "/crop-cycles" not in src and "_fetch_platform_crop_cycles" not in src


@pytest.mark.asyncio
async def test_unexpected_error_is_no_season_start(monkeypatch):
    """The assessment must not fail because the season start could not be resolved."""
    async def boom(*a, **k):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(cc, "fetch_crop_timeline", boom)
    assert await cc.resolve_season_start("p1", "t") is None
