"""Test assessments API endpoints."""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock


@pytest.fixture
def client():
    with patch("app.services.redis_state.RedisState.create", AsyncMock()), \
         patch("app.services.redis_state.RedisState.health_check", AsyncMock(return_value={"redis": "connected"})):
        from app.main import app
        return TestClient(app)


class TestHealth:
    def test_health_endpoint(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "healthy"
        assert data["service"] == "Crop Health Engine"


class TestAssessments:
    def test_latest_empty(self, client):
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value=[])))):
            resp = client.get("/api/crop-health/assessments/latest")
            assert resp.status_code == 200
            assert resp.json() == {"assessments": []}

    def test_export_csv(self, client):
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value=[])))):
            resp = client.get("/api/crop-health/assessments/export")
            assert resp.status_code == 200
            assert "text/csv" in resp.headers["content-type"]

    def test_disease_risks_empty(self, client):
        with patch("httpx.AsyncClient.get", AsyncMock(return_value=MagicMock(status_code=200, json=MagicMock(return_value=[])))):
            resp = client.get("/api/crop-health/diseases/active")
            assert resp.status_code == 200
            assert resp.json() == {"risks": []}
