"""Integration test: EOProduct entity → _fetch_parcel_sar() → SAR engine."""
import sys
import pytest
from unittest.mock import patch, AsyncMock, MagicMock


def _patch_settings_module():
    """Create a mock app.config module that _fetch_parcel_sar can import."""
    mock_settings = MagicMock()
    mock_settings.orion_ld_url = "http://orion:1026"
    mock_config = MagicMock()
    mock_config.get_settings.return_value = mock_settings
    return mock_config


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_sar_queries_eo_product_type(mock_client_cls):
    """_fetch_parcel_sar() uses type=EOProduct in Orion-LD query."""
    from app.services.pipeline import _fetch_parcel_sar

    mock_config = _patch_settings_module()
    with patch.dict("sys.modules", {"app.config": mock_config}):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        await _fetch_parcel_sar("parcel-4", "test-tenant")

    # Verify the query parameters
    call_kwargs = mock_client.get.call_args
    params = call_kwargs[1]["params"]
    assert params["type"] == "EOProduct"
    assert "hasAgriParcel" in params["q"]
    assert "productType" in params["q"]
    assert "GRD" in params["q"]


@pytest.mark.asyncio
@patch("httpx.AsyncClient")
async def test_fetch_sar_returns_none_when_empty(mock_client_cls):
    """_fetch_parcel_sar() returns None when Orion-LD returns empty list."""
    from app.services.pipeline import _fetch_parcel_sar

    mock_config = _patch_settings_module()
    with patch.dict("sys.modules", {"app.config": mock_config}):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = []

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_response
        mock_client.__aenter__.return_value = mock_client
        mock_client_cls.return_value = mock_client

        result = await _fetch_parcel_sar("parcel-4", "test-tenant")

    assert result is None
