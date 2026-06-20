"""Integration test: pipeline._fetch_gdd → timeseries-reader contract."""

import pytest

from app.config import get_settings
from app.services import pipeline


@pytest.mark.asyncio
async def test_fetch_gdd_returns_none_when_no_url(monkeypatch):
    """weather_api_url not configured → None."""
    settings = get_settings()
    monkeypatch.setattr(settings, "weather_api_url", "")
    result = await pipeline._fetch_gdd("tenant", "2026-03-01", "parcel:123", base_temp=10.0)
    assert result is None


@pytest.mark.asyncio
async def test_fetch_gdd_passes_correct_params(monkeypatch):
    """Verify _fetch_gdd builds the right URL and params."""
    captured = {}

    class _Resp:
        status_code = 200
        def json(self):
            return {"gdd_total": 450.0, "mean_daily_gdd": 5.0, "days_count": 90}

    class _MockClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a, **k):
            return False
        async def get(self, url, *, params, headers):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            return _Resp()

    settings = get_settings()
    monkeypatch.setattr(settings, "weather_api_url", "http://ts:5000")
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _MockClient())

    result = await pipeline._fetch_gdd(
        "tenant-x", "2026-03-01", "urn:ngsi-ld:AgriParcel:test:p1",
        base_temp=8.0, upper_cutoff=28.0,
    )
    assert result is not None
    assert result["gdd_total"] == 450.0
    # Verify all expected params are present
    assert captured["params"].get("parcel_id") == "urn:ngsi-ld:AgriParcel:test:p1"
    assert captured["params"].get("base_temp") == "8.0"
    assert captured["params"].get("upper_cutoff") == "28.0"
    assert captured["params"].get("season_start") == "2026-03-01"
    assert captured["headers"].get("X-Tenant-ID") == "tenant-x"


@pytest.mark.asyncio
async def test_fetch_gdd_without_upper_cutoff(monkeypatch):
    """When upper_cutoff is None, it should NOT be sent as a param."""
    captured = {}

    class _Resp:
        status_code = 200
        def json(self):
            return {"gdd_total": 300.0}

    class _MockClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a, **k):
            return False
        async def get(self, url, *, params, headers):
            captured["params"] = params
            return _Resp()

    settings = get_settings()
    monkeypatch.setattr(settings, "weather_api_url", "http://ts:5000")
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _MockClient())

    result = await pipeline._fetch_gdd("t", "2026-03-01", "p1", base_temp=10.0)
    assert result is not None
    # upper_cutoff should NOT be in params when None
    assert "upper_cutoff" not in captured["params"]
    assert captured["params"]["base_temp"] == "10.0"
    assert captured["params"]["parcel_id"] == "p1"


@pytest.mark.asyncio
async def test_fetch_gdd_returns_none_on_404(monkeypatch):
    """HTTP 404 → None (graceful degradation)."""
    class _Resp:
        status_code = 404

    class _MockClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a, **k):
            return False
        async def get(self, *a, **k):
            return _Resp()

    settings = get_settings()
    monkeypatch.setattr(settings, "weather_api_url", "http://ts:5000")
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _MockClient())

    result = await pipeline._fetch_gdd("t", "2026-03-01", "p1")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_gdd_returns_none_on_timeout(monkeypatch):
    """HTTP timeout → None (graceful degradation)."""
    class _MockClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a, **k):
            return False
        async def get(self, *a, **k):
            raise __import__("httpx").TimeoutException("timeout")

    settings = get_settings()
    monkeypatch.setattr(settings, "weather_api_url", "http://ts:5000")
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _MockClient())

    result = await pipeline._fetch_gdd("t", "2026-03-01", "p1")
    assert result is None


@pytest.mark.asyncio
async def test_fetch_gdd_with_default_base_temp(monkeypatch):
    """When base_temp not passed, default is 10.0."""
    captured = {}

    class _Resp:
        status_code = 200
        def json(self):
            return {"gdd_total": 100.0}

    class _MockClient:
        def __init__(self, *a, **k):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *a, **k):
            return False
        async def get(self, url, *, params, headers):
            captured["params"] = params
            return _Resp()

    settings = get_settings()
    monkeypatch.setattr(settings, "weather_api_url", "http://ts:5000")
    monkeypatch.setattr("httpx.AsyncClient", lambda *a, **k: _MockClient())

    result = await pipeline._fetch_gdd("t", "2026-03-01", "p1")
    assert result is not None
    assert captured["params"]["base_temp"] == "10.0"
