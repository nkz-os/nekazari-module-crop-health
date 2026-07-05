"""Tests for assessment_mapper and assessments API."""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from app.api.assessment_mapper import (
    map_entity_to_assessment,
    map_entity_to_zone_assessment,
    dedupe_latest_per_parcel,
    dedupe_latest_per_zone,
)


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

SAMPLE_ZONE_ENTITY = {
    **SAMPLE_ENTITY,
    "id": "urn:ngsi-ld:CropHealthZoneAssessment:parcel-a-z1-20260628",
    "type": "CropHealthZoneAssessment",
    "zoneId": "z1",
    "hasAgriParcelZone": {
        "type": "Relationship",
        "object": "urn:ngsi-ld:AgriParcelZone:t:parcel-a:z1",
    },
}

_PARCEL_GEOM = {
    "type": "Polygon",
    "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]],
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

    def test_dedupe_latest_per_zone(self):
        older = {**SAMPLE_ZONE_ENTITY, "assessedAt": "2026-06-27T10:00:00Z"}
        newer = {**SAMPLE_ZONE_ENTITY, "assessedAt": "2026-06-28T10:00:00Z"}
        other = {
            **SAMPLE_ZONE_ENTITY,
            "id": "urn:ngsi-ld:CropHealthZoneAssessment:parcel-a-z2-20260628",
            "zoneId": "z2",
            "hasAgriParcelZone": {"object": "urn:ngsi-ld:AgriParcelZone:t:parcel-a:z2"},
        }
        result = dedupe_latest_per_zone([older, newer, other])
        assert len(result) == 2
        by_zone = {map_entity_to_zone_assessment(e)["zoneId"]: e for e in result}
        assert by_zone["z1"]["assessedAt"] == "2026-06-28T10:00:00Z"

    def test_map_zone_assessment_includes_geometry(self):
        result = map_entity_to_zone_assessment(
            SAMPLE_ZONE_ENTITY,
            geometry=_PARCEL_GEOM,
            sensor_nearby=True,
        )
        assert result["zoneId"] == "z1"
        assert result["zoneUrn"] == "urn:ngsi-ld:AgriParcelZone:t:parcel-a:z1"
        assert result["geometry"]["type"] == "Polygon"
        assert result["sensorNearby"] is True


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

    def test_zone_assessments_requires_parcel(self, client):
        resp = client.get("/api/crop-health/assessments/zones")
        assert resp.status_code == 200
        assert resp.json() == {"zones": [], "isWholeParcel": True}

    def test_zone_assessments_for_parcel(self, client):
        with patch(
            "app.api.assessments._fetch_zone_assessment_entities",
            AsyncMock(return_value=[SAMPLE_ZONE_ENTITY]),
        ), patch(
            "app.api.assessments.resolve_zones",
            AsyncMock(return_value=[]),
        ), patch(
            "app.api.assessments.is_whole_parcel",
            return_value=False,
        ), patch(
            "app.api.assessments._map_zone_entities_with_geometry",
            AsyncMock(return_value=([
                map_entity_to_zone_assessment(SAMPLE_ZONE_ENTITY, geometry=_PARCEL_GEOM),
            ], False)),
        ):
            resp = client.get("/api/crop-health/assessments/zones?parcelId=parcel-a")
            assert resp.status_code == 200
            body = resp.json()
            assert body["isWholeParcel"] is False
            assert len(body["zones"]) == 1
            assert body["zones"][0]["zoneId"] == "z1"

    def test_zone_assessments_all(self, client):
        with patch(
            "app.api.assessments._fetch_zone_assessment_entities",
            AsyncMock(return_value=[SAMPLE_ZONE_ENTITY]),
        ), patch(
            "app.api.assessments._map_zone_entities_with_geometry",
            AsyncMock(return_value=([
                map_entity_to_zone_assessment(SAMPLE_ZONE_ENTITY, geometry=_PARCEL_GEOM),
            ], False)),
        ):
            resp = client.get("/api/crop-health/assessments/zones/all")
            assert resp.status_code == 200
            assert len(resp.json()["zones"]) == 1
