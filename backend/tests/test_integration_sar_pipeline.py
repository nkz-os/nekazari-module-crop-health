"""Integration test: EOProduct entity → _fetch_parcel_sar() → SAR engine."""
import sys
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def _patch_settings_module(extra=None):
    """Create a mock app.config module that _fetch_parcel_sar can import."""
    mock_settings = MagicMock()
    mock_settings.orion_ld_url = "http://orion:1026"
    mock_settings.orion_ld_context = "http://context/ngsi-ld-context.json"
    if extra:
        for k, v in extra.items():
            setattr(mock_settings, k, v)
    mock_config = MagicMock()
    mock_config.get_settings.return_value = mock_settings
    return mock_config


def _make_orion_client_cls(entities):
    """Return a mock OrionClient class whose instances return *entities* from query_entities."""
    mock_instance = AsyncMock()
    mock_instance.query_entities = AsyncMock(return_value=entities)
    mock_instance.close = AsyncMock()
    mock_cls = MagicMock(return_value=mock_instance)
    return mock_cls, mock_instance


@pytest.mark.asyncio
async def test_fetch_sar_queries_eo_product_type():
    """_fetch_parcel_sar() reads the parcel's products in both stored shapes."""
    from app.services.pipeline import _fetch_parcel_sar

    mock_cls, mock_instance = _make_orion_client_cls([])
    mock_config = _patch_settings_module()

    with patch.dict("sys.modules", {"app.config": mock_config}), \
         patch("nkz_platform_sdk.orion.OrionClient", mock_cls):
        await _fetch_parcel_sar("parcel-4", "test-tenant")

    calls = [c.kwargs for c in mock_instance.query_entities.call_args_list]
    assert {c["type"] for c in calls} == {"EOProduct", "EOSatelliteImagery"}
    assert all('hasAgriParcel=="urn:ngsi-ld:AgriParcel:parcel-4"' in c["q"] for c in calls)


@pytest.mark.asyncio
async def test_fetch_sar_returns_none_when_empty():
    """_fetch_parcel_sar() returns None when Orion-LD returns empty list."""
    from app.services.pipeline import _fetch_parcel_sar

    mock_cls, _ = _make_orion_client_cls([])
    mock_config = _patch_settings_module()

    with patch.dict("sys.modules", {"app.config": mock_config}), \
         patch("nkz_platform_sdk.orion.OrionClient", mock_cls):
        result = await _fetch_parcel_sar("parcel-4", "test-tenant")

    assert result == (None, "unavailable")
