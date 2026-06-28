"""Tests for assessment_mapper and assessments API."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.api.assessment_mapper import map_entity_to_assessment, dedupe_latest_per_parcel


SAMPLE_ENTITY = {
    "id": "urn:ngsi-ld:CropHealthAssessment:parcel-a-20260628",
    "type": "CropHealthAssessment",
    "hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:parcel-a"},
    "assessedAt": "2026-06-28T10:00:00Z",
    "cwsiValue": 0.45,
    "overallSeverity": "MEDIUM",
    "recommendedAction": "MONITOR",
    "compactionRiskLevel": "moderate",
    "compactionRiskScore": 55,
    "compactionAdvisory": "compaction.advisory.monitor_susceptible_soil",
    "soilWaterMm": 80,
    "soilAWCmm": 120,
    "soilWaterRatio": 0.67,
    "vhi": 42.5,
    "vci": 38.0,
    "phenologyDeviation": "on_track",
    "stageProgressPct": 65.0,
    "gddAccumulated": 890,
}


class TestAssessmentMapper:
    def test_maps_compaction_and_nested_objects(self):
        result = map_entity_to_assessment(SAMPLE_ENTITY)
        assert result["parcelId"] == "parcel-a"
        assert result["compactionRiskLevel"] == "moderate"
        assert result["compactionRisk"]["advisory"] == "monitor_susceptible_soil"
        assert result["soilWaterBalance"]["swMm"] == 80
        assert result["vhi"]["vhi"] == 42.5
        assert result["phenologyDeviation"] == "on_track"
        assert result["gddAccumulated"] == 890

    def test_dedupe_latest_per_parcel(self):
        older = {**SAMPLE_ENTITY, "assessedAt": "2026-06-27T10:00:00Z"}
        newer = {**SAMPLE_ENTITY, "assessedAt": "2026-06-28T10:00:00Z"}
        other = {
            **SAMPLE_ENTITY,
            "id": "urn:ngsi-ld:CropHealthAssessment:parcel-b-20260628",
            "hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:parcel-b"},
        }
        result = dedupe_latest_per_parcel([older, newer, other])
        assert len(result) == 2
        by_parcel = {map_entity_to_assessment(e)["parcelId"]: e for e in result}
        assert by_parcel["parcel-a"]["assessedAt"] == "2026-06-28T10:00:00Z"


@pytest.fixture
def client():
    with patch("app.services.redis_state.RedisState.create", AsyncMock()), \
         patch("app.services.redis_state.RedisState.health_check", AsyncMock(return_value={"redis": "connected"})):
        from app.main import app
        c = TestClient(app)
        c.headers.update({"X-Tenant-ID": "test-tenant", "X-User-ID": "test-user"})
        return c


class TestAssessmentsAPI:
    def test_latest_empty(self, client):
        with patch(
            "app.api.assessments._fetch_assessment_entities",
            AsyncMock(return_value=[]),
        ):
            resp = client.get("/api/crop-health/assessments/latest")
            assert resp.status_code == 200
            assert resp.json() == {"assessments": []}

    def test_latest_filters_parcel_id(self, client):
        with patch(
            "app.api.assessments._fetch_assessment_entities",
            AsyncMock(return_value=[SAMPLE_ENTITY]),
        ):
            resp = client.get("/api/crop-health/assessments/latest?parcelId=parcel-a")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["assessments"]) == 1
            assert data["assessments"][0]["parcelId"] == "parcel-a"
            assert data["assessments"][0]["compactionRiskLevel"] == "moderate"

    def test_assessments_all_alias(self, client):
        with patch(
            "app.api.assessments._fetch_assessment_entities",
            AsyncMock(return_value=[SAMPLE_ENTITY]),
        ):
            resp = client.get("/api/crop-health/assessments/all")
            assert resp.status_code == 200
            assert len(resp.json()["assessments"]) == 1

    def test_correlation_stats(self, client):
        with patch(
            "app.api.assessments.OrionClient",
        ) as mock_cls, patch("httpx.AsyncClient") as mock_http:
            inst = AsyncMock()
            inst.query_entities = AsyncMock(return_value=[])
            inst.close = AsyncMock()
            mock_cls.return_value = inst

            mock_resp = MagicMock()
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json = MagicMock(return_value={"data": []})
            mock_http.return_value.__aenter__.return_value.get = AsyncMock(return_value=mock_resp)

            resp = client.get("/api/crop-health/assessments/correlation?parcelId=parcel-a")
            assert resp.status_code == 200
            body = resp.json()
            assert "pairs" in body
            assert "stats" in body
            assert body["stats"]["n"] == 0

    def test_export_csv(self, client):
        with patch("app.api.assessments.OrionClient") as mock_cls:
            inst = AsyncMock()
            inst.query_entities = AsyncMock(return_value=[])
            inst.close = AsyncMock()
            mock_cls.return_value = inst
            resp = client.get("/api/crop-health/assessments/export")
            assert resp.status_code == 200
            assert "text/csv" in resp.headers["content-type"]

    def test_disease_risks_empty(self, client):
        with patch("app.api.assessments.OrionClient") as mock_cls:
            inst = AsyncMock()
            inst.query_entities = AsyncMock(return_value=[])
            inst.close = AsyncMock()
            mock_cls.return_value = inst
            resp = client.get("/api/crop-health/diseases/active")
            assert resp.status_code == 200
            assert resp.json() == {"risks": []}
