"""Tests for get_multiyear_vigor_anomaly() and _extract_season_year()."""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from app.services.context_client import (
    get_multiyear_vigor_anomaly,
    _extract_season_year,
)


class TestExtractSeasonYear:
    def test_april_is_current_year_season(self):
        assert _extract_season_year("2024-04-15T10:00:00Z") == 2024

    def test_july_is_current_year_season(self):
        assert _extract_season_year("2024-07-01T00:00:00Z") == 2024

    def test_october_is_current_year_season(self):
        assert _extract_season_year("2024-10-31T23:59:59Z") == 2024

    def test_january_belongs_to_previous_year_season(self):
        assert _extract_season_year("2025-01-15T10:00:00Z") == 2024

    def test_march_belongs_to_previous_year_season(self):
        assert _extract_season_year("2025-03-01T00:00:00Z") == 2024

    def test_november_outside_season_returns_none(self):
        assert _extract_season_year("2024-11-15T10:00:00Z") is None

    def test_december_outside_season_returns_none(self):
        assert _extract_season_year("2024-12-25T00:00:00Z") is None

    def test_february_belongs_to_previous_year_season(self):
        assert _extract_season_year("2025-02-14T10:00:00Z") == 2024

    def test_invalid_date_returns_none(self):
        assert _extract_season_year("not-a-date") is None

    def test_empty_string_returns_none(self):
        assert _extract_season_year("") is None


class TestGetMultiyearVigorAnomaly:
    """Integration-style tests mocking the Orion-LD HTTP call."""

    @pytest.fixture
    def mock_settings(self):
        with patch("app.services.context_client.get_settings") as mock:
            settings = MagicMock()
            settings.orion_ld_url = "http://orion:1026"
            mock.return_value = settings
            yield mock

    @pytest.fixture
    def mock_httpx(self):
        with patch("app.services.context_client.httpx.AsyncClient") as mock:
            client = AsyncMock()
            mock.return_value.__aenter__.return_value = client
            yield client

    def _make_entity(self, assessed_at, vigor_index):
        return {
            "id": "urn:ngsi-ld:CropHealthAssessment:parcel-1-20240601",
            "type": "CropHealthAssessment",
            "assessedAt": assessed_at,
            "vigorIndex": vigor_index,
        }

    @pytest.mark.asyncio
    async def test_returns_anomaly_for_multiple_seasons(self, mock_settings, mock_httpx):
        entities = [
            self._make_entity("2023-06-15T10:00:00Z", 0.75),
            self._make_entity("2023-07-15T10:00:00Z", 0.78),
            self._make_entity("2023-08-15T10:00:00Z", 0.72),
            self._make_entity("2024-06-15T10:00:00Z", 0.60),
            self._make_entity("2024-07-15T10:00:00Z", 0.58),
            self._make_entity("2024-08-15T10:00:00Z", 0.62),
        ]
        mock_httpx.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=lambda: entities,
        ))

        result = await get_multiyear_vigor_anomaly("parcel-1", "t1", seasons=3)
        assert result is not None
        assert result["seasons_analyzed"] == 2
        # 2023 mean: (0.75+0.78+0.72)/3 = 0.75
        # 2024 mean: (0.60+0.58+0.62)/3 = 0.60
        # overall mean: (all 6)/6 = 0.675
        # anomalies: 2023: +0.075, 2024: -0.075 → avg = 0.0
        assert result["avg_anomaly"] == pytest.approx(0.0, abs=0.01)
        assert result["overall_mean_vigor"] == pytest.approx(0.675, abs=0.01)

    @pytest.mark.asyncio
    async def test_negative_anomaly_when_recent_season_is_worse(self, mock_settings, mock_httpx):
        entities = [
            self._make_entity("2023-06-15T10:00:00Z", 0.80),
            self._make_entity("2023-07-15T10:00:00Z", 0.82),
            self._make_entity("2024-06-15T10:00:00Z", 0.50),
            self._make_entity("2024-07-15T10:00:00Z", 0.48),
        ]
        mock_httpx.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=lambda: entities,
        ))

        result = await get_multiyear_vigor_anomaly("parcel-1", "t1")
        assert result is not None
        assert result["seasons_analyzed"] == 2
        assert result["seasonal_means"][2023] > result["seasonal_means"][2024]

    @pytest.mark.asyncio
    async def test_persistent_decline_across_three_seasons(self, mock_settings, mock_httpx):
        entities = [
            self._make_entity("2022-06-15T10:00:00Z", 0.85),
            self._make_entity("2023-06-15T10:00:00Z", 0.70),
            self._make_entity("2024-06-15T10:00:00Z", 0.55),
        ]
        mock_httpx.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=lambda: entities,
        ))

        result = await get_multiyear_vigor_anomaly("parcel-1", "t1", seasons=3)
        assert result is not None
        assert result["seasons_analyzed"] == 3
        # overall mean = 0.70
        assert result["overall_mean_vigor"] == pytest.approx(0.70, abs=0.01)

    @pytest.mark.asyncio
    async def test_insufficient_seasons_returns_none(self, mock_settings, mock_httpx):
        entities = [
            self._make_entity("2024-06-15T10:00:00Z", 0.75),
            self._make_entity("2024-07-15T10:00:00Z", 0.78),
        ]
        mock_httpx.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=lambda: entities,
        ))

        result = await get_multiyear_vigor_anomaly("parcel-1", "t1")
        assert result is None  # Only 1 season, need ≥2

    @pytest.mark.asyncio
    async def test_empty_response_returns_none(self, mock_settings, mock_httpx):
        mock_httpx.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=lambda: [],
        ))

        result = await get_multiyear_vigor_anomaly("parcel-1", "t1")
        assert result is None

    @pytest.mark.asyncio
    async def test_orion_error_returns_none(self, mock_settings, mock_httpx):
        mock_httpx.get = AsyncMock(return_value=MagicMock(
            status_code=500, json=lambda: {"error": "Internal"},
        ))

        result = await get_multiyear_vigor_anomaly("parcel-1", "t1")
        assert result is None

    @pytest.mark.asyncio
    async def test_connection_error_returns_none(self, mock_settings, mock_httpx):
        import httpx
        mock_httpx.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        result = await get_multiyear_vigor_anomaly("parcel-1", "t1")
        assert result is None

    @pytest.mark.asyncio
    async def test_filters_out_outside_season_entities(self, mock_settings, mock_httpx):
        entities = [
            self._make_entity("2024-06-15T10:00:00Z", 0.75),
            self._make_entity("2024-12-15T10:00:00Z", 0.50),  # December → outside season
            self._make_entity("2023-07-15T10:00:00Z", 0.80),
        ]
        mock_httpx.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=lambda: entities,
        ))

        result = await get_multiyear_vigor_anomaly("parcel-1", "t1")
        assert result is not None
        assert result["seasons_analyzed"] == 2  # 2023 and 2024, December ignored

    @pytest.mark.asyncio
    async def test_handles_keyvalues_and_ngsi_ld_formats(self, mock_settings, mock_httpx):
        """Entity might have flat keyValues or nested NGSI-LD format."""
        entities = [
            {"assessedAt": "2023-06-15T10:00:00Z", "vigorIndex": 0.75},
            {"assessedAt": {"type": "Property", "value": "2024-06-15T10:00:00Z"},
             "vigorIndex": {"type": "Property", "value": 0.65}},
        ]
        mock_httpx.get = AsyncMock(return_value=MagicMock(
            status_code=200, json=lambda: entities,
        ))

        result = await get_multiyear_vigor_anomaly("parcel-1", "t1", seasons=3)
        assert result is not None
        assert result["seasons_analyzed"] == 2
