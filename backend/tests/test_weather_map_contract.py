"""Contract tests for _weather_map_meteo against the real weather-map /stats shape.

Verified live 2026-06-20 against weather-map-backend:8080:
- metrics nested under data["metrics"][name]["mean"]; valid names temperature_avg/eto/...
- no-COG response: {"error": "No COG data available", "metrics": {}}.
"""
import json

import pytest

from app.services import pipeline


class _FakeResp:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, status, payload):
        self._status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, params=None, headers=None):
        # assert we send the live-correct route, valid metrics, and tenant header
        assert "/api/weather-map/stats/urn:ngsi-ld:AgriParcel:" in url
        assert params["metrics"] == "temperature_avg,eto"
        assert headers.get("X-Tenant-ID") == "montiko"
        # weather-map returns 401 "Missing X-User-ID" without this header (AGENTS.md §9)
        assert headers.get("X-User-ID") == "crop-health-worker"
        return _FakeResp(self._status, self._payload)


def _patch(monkeypatch, status, payload):
    import httpx
    monkeypatch.setattr(
        httpx, "AsyncClient", lambda *a, **k: _FakeClient(status, payload)
    )


@pytest.mark.asyncio
async def test_parses_nested_metrics_mean(monkeypatch):
    _patch(monkeypatch, 200, {
        "metrics": {
            "temperature_avg": {"mean": 22.4, "min": 18.0, "max": 27.1},
            "eto": {"mean": 4.1},
        },
        "parcel_id": "x",
    })
    out = await pipeline._weather_map_meteo(
        "urn:ngsi-ld:AgriParcel:62a6e83b", "montiko"
    )
    assert out == {"air_temp_c": 22.4, "et0_mm": 4.1}


@pytest.mark.asyncio
async def test_no_cog_data_returns_empty(monkeypatch):
    _patch(monkeypatch, 200, {"error": "No COG data available", "metrics": {}})
    out = await pipeline._weather_map_meteo(
        "urn:ngsi-ld:AgriParcel:62a6e83b", "montiko"
    )
    assert out == {}


@pytest.mark.asyncio
async def test_non_200_returns_empty(monkeypatch):
    _patch(monkeypatch, 401, {"detail": "Unauthorized"})
    out = await pipeline._weather_map_meteo(
        "urn:ngsi-ld:AgriParcel:62a6e83b", "montiko"
    )
    assert out == {}
