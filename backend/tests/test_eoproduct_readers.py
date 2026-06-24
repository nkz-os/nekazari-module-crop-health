"""crop-health readers must consume the canonical EOProduct contract.

Contract (vegetation-health CONTRACT.md): one EOProduct per (parcel, sensingDate);
each index is a named lowercased Property (`ndvi`, value = zonal mean). No
`productType` discriminator and no `ndviMean`/`ndviValue` on optical products.
"""
from unittest.mock import AsyncMock, patch

import pytest


def _eoproduct(sensing_date: str, ndvi: float) -> dict:
    # keyValues representation, as returned with options=keyValues.
    return {
        "id": f"urn:ngsi-ld:EOProduct:montiko:da36ccd2e5:{sensing_date}",
        "type": "EOProduct",
        "hasAgriParcel": "urn:ngsi-ld:AgriParcel:da36ccd2-85d2-4c76-b552-c5c835a987c1",
        "sensingDate": sensing_date,
        "ndvi": ndvi,
    }


@pytest.mark.asyncio
async def test_fetch_parcel_ndvi_reads_latest_eoproduct():
    from app.services import pipeline

    client = AsyncMock()
    client.query_entities = AsyncMock(return_value=[
        _eoproduct("2026-06-10", 0.55),
        _eoproduct("2026-06-20", 0.72),  # newest by sensingDate
    ])
    client.close = AsyncMock()

    with patch("nkz_platform_sdk.orion.OrionClient", return_value=client):
        val = await pipeline._fetch_parcel_ndvi(
            "da36ccd2-85d2-4c76-b552-c5c835a987c1", "montiko"
        )

    assert val == 0.72  # newest acquisition's ndvi mean
    kwargs = client.query_entities.call_args.kwargs
    assert kwargs.get("type") == "EOProduct"
    # optical EOProducts carry no productType discriminator
    assert "productType" not in (kwargs.get("q") or "")


@pytest.mark.asyncio
async def test_ndvi_climatology_reads_eoproduct_history():
    """VHI climatology must read EOProduct history (sensingDate + ndvi), not VegetationIndex."""
    from app.services import context_client

    # 4 acquisitions in June (month 6) for the parcel
    ents = [_eoproduct(f"2025-06-0{d}", 0.60 + d * 0.01) for d in range(1, 5)]
    client = AsyncMock()
    client.query_entities = AsyncMock(return_value=ents)
    client.close = AsyncMock()

    with patch("app.services.context_client.OrionClient", return_value=client):
        result = await context_client.get_ndvi_climatology(
            "da36ccd2-unique-clim", "montiko", target_month=6, eppo_code=None
        )

    assert client.query_entities.call_args.kwargs.get("type") == "EOProduct"
    assert result["is_reliable"] is True
    assert result["sample_count"] >= 2


@pytest.mark.asyncio
async def test_ndvi_cwsi_correlation_reads_eoproduct():
    """The NDVI/CWSI correlation endpoint must read EOProduct (ndvi + sensingDate)."""
    from datetime import date
    from types import SimpleNamespace
    from app.api import assessments

    orion = AsyncMock()
    orion.query_entities = AsyncMock(return_value=[
        {"id": "urn:ngsi-ld:EOProduct:montiko:p:2026-06-05", "sensingDate": "2026-06-05", "ndvi": 0.72},
    ])
    orion.close = AsyncMock()

    conn = AsyncMock()
    conn.fetch = AsyncMock(return_value=[{"date": date(2026, 6, 5), "cwsi": 0.42}])
    conn.close = AsyncMock()

    import asyncpg
    req = SimpleNamespace(state=SimpleNamespace(tenant_id="montiko"))
    fake_settings = SimpleNamespace(
        orion_ld_url="http://orion", orion_ld_context="http://ctx",
        weather_db_url="postgresql://x",
    )

    with patch("app.api.assessments.OrionClient", return_value=orion), \
         patch("app.api.assessments.get_settings", return_value=fake_settings), \
         patch.object(asyncpg, "connect", AsyncMock(return_value=conn)):
        out = await assessments.ndvi_cwsi_correlation(req, parcelId="p", days=30)

    # No productType discriminator in the EOProduct query
    assert "productType" not in (orion.query_entities.call_args.kwargs.get("q") or "")
    assert out["pairs"] == [{"date": "2026-06-05", "ndvi": 0.72, "cwsi": 0.42}]
