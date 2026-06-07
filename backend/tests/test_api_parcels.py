"""Tests for GET /api/crop-health/parcels endpoint."""

import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def client():
    with patch("app.services.redis_state.RedisState.create", AsyncMock()), \
         patch("app.services.redis_state.RedisState.health_check", AsyncMock(return_value={"redis": "connected"})):
        from app.main import app
        return TestClient(app)


class TestParcels:
    def test_parcels_empty_when_no_data(self, client):
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=MagicMock(
            status_code=200, json=MagicMock(return_value=[])
        ))):
            resp = client.get("/api/crop-health/parcels")
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"parcels": []}

    def test_parcels_includes_assessment_data(self, client):
        call_count = [0]

        def mock_get(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(status_code=200, json=MagicMock(return_value=[
                    {
                        "id": "urn:ngsi-ld:CropHealthAssessment:cha-1",
                        "type": "CropHealthAssessment",
                        "hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:Parcela-4"},
                        "cwsiValue": {"type": "Property", "value": 0.42},
                        "vigorIndex": {"type": "Property", "value": 0.72},
                        "overallSeverity": {"type": "Property", "value": "MEDIUM"},
                        "assessedAt": {"type": "Property", "value": "2026-06-03T14:22:00Z"},
                        "cropName": "Trigo blando",
                        "phenologyStage": "flowering",
                    }
                ]))
            else:
                return MagicMock(status_code=200, json=MagicMock(return_value=[
                    {
                        "id": "urn:ngsi-ld:AgriParcel:Parcela-4",
                        "type": "AgriParcel",
                        "name": {"type": "Property", "value": "Parcela 4"},
                        "area": {"type": "Property", "value": 3.2},
                    }
                ]))

        with patch("httpx.AsyncClient.get", side_effect=mock_get):
            resp = client.get("/api/crop-health/parcels")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["parcels"]) == 1
            parcel = data["parcels"][0]
            assert parcel["parcelId"] == "Parcela-4"
            assert parcel["hasData"] is True
            assert parcel["overallSeverity"] == "MEDIUM"
            assert parcel["cwsiValue"] == 0.42
            assert parcel["parcelName"] == "Parcela 4"
            assert parcel["areaHa"] == 3.2
            assert parcel["cropName"] == "Trigo blando"
            assert parcel["phenologyStage"] == "flowering"

    def test_parcels_without_assessment(self, client):
        call_count = [0]

        def mock_get(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(status_code=200, json=MagicMock(return_value=[]))
            else:
                return MagicMock(status_code=200, json=MagicMock(return_value=[
                    {
                        "id": "urn:ngsi-ld:AgriParcel:Parcela-15",
                        "type": "AgriParcel",
                        "name": {"type": "Property", "value": "Parcela 15"},
                    }
                ]))

        with patch("httpx.AsyncClient.get", side_effect=mock_get):
            resp = client.get("/api/crop-health/parcels")
            assert resp.status_code == 200
            data = resp.json()
            assert len(data["parcels"]) == 1
            parcel = data["parcels"][0]
            assert parcel["parcelId"] == "Parcela-15"
            assert parcel["hasData"] is False

    def test_parcels_sorted_by_severity(self, client):
        call_count = [0]

        def mock_get(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                return MagicMock(status_code=200, json=MagicMock(return_value=[
                    {
                        "id": "urn:ngsi-ld:CropHealthAssessment:low",
                        "type": "CropHealthAssessment",
                        "hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:parcel-low"},
                        "overallSeverity": "LOW",
                        "assessedAt": "2026-06-03T10:00:00Z",
                    },
                    {
                        "id": "urn:ngsi-ld:CropHealthAssessment:crit",
                        "type": "CropHealthAssessment",
                        "hasAgriParcel": {"type": "Relationship", "object": "urn:ngsi-ld:AgriParcel:parcel-crit"},
                        "overallSeverity": "CRITICAL",
                        "assessedAt": "2026-06-03T10:00:00Z",
                    },
                ]))
            else:
                return MagicMock(status_code=200, json=MagicMock(return_value=[]))

        with patch("httpx.AsyncClient.get", side_effect=mock_get):
            resp = client.get("/api/crop-health/parcels")
            assert resp.status_code == 200
            data = resp.json()
            assert data["parcels"][0]["parcelId"] == "parcel-crit"
            assert data["parcels"][1]["parcelId"] == "parcel-low"

    def test_parcels_orion_failure_graceful(self, client):
        with patch("httpx.AsyncClient.get", side_effect=Exception("Connection refused")):
            resp = client.get("/api/crop-health/parcels")
            assert resp.status_code == 200
            data = resp.json()
            assert data == {"parcels": []}
