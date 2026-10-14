"""Integration test: pipeline._fetch_gdd → weather-api parcel daily series contract."""

from datetime import date

import httpx
import pytest
from nkz_platform_sdk.crypto import verify_hmac_signature

from app.config import get_settings
from app.services import pipeline

SECRET = "test-hmac-secret"
TODAY = date(2026, 10, 14)


class _Resp:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload


def _client(captured, resp=None, exc=None):
    class _MockClient:
        def __init__(self, *a, **k):
            captured["timeout"] = k.get("timeout")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a, **k):
            return False

        async def get(self, url, *, params, headers):
            captured["url"] = url
            captured["params"] = params
            captured["headers"] = headers
            if exc is not None:
                raise exc
            return resp

    return _MockClient


def _daily(gdd, days_counted):
    return {"totals": {"gdd": gdd, "days_counted": {"gdd": days_counted}}, "missing_days": []}


@pytest.fixture
def env(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "weather_daily_url", "http://wx:8000")
    monkeypatch.setattr(pipeline, "_hmac_secret", lambda: SECRET)
    monkeypatch.setattr(pipeline, "_utc_today", lambda: TODAY)
    return settings


@pytest.mark.asyncio
async def test_fetch_gdd_reads_signed_daily_totals(env, monkeypatch):
    captured = {}
    # 2026-10-01 .. 2026-10-13 (yesterday) = 13 closed days
    monkeypatch.setattr(httpx, "AsyncClient", _client(captured, _Resp(200, _daily(450.0, 13))))

    result = await pipeline._fetch_gdd(
        "tenant-x", "2026-10-01", "urn:ngsi-ld:AgriParcel:p1",
        base_temp=8.0, upper_cutoff=28.0,
    )

    assert result == {"gdd_total": 450.0, "days_count": 13}
    assert captured["url"] == "http://wx:8000/api/weather/parcel/p1/daily"
    assert captured["params"] == {
        "start": "2026-10-01", "end": "2026-10-13", "fill": "open_meteo",
        "base_temp": "8.0", "upper_cutoff": "28.0",
    }
    headers = captured["headers"]
    assert headers["X-Tenant-ID"] == "tenant-x"
    assert verify_hmac_signature(SECRET, headers["X-Auth-Signature"], "", "tenant-x")


@pytest.mark.asyncio
async def test_fetch_gdd_default_cutoff_and_base(env, monkeypatch):
    """No crop cutoff → 30 °C, the default the season GDD has always used."""
    captured = {}
    monkeypatch.setattr(httpx, "AsyncClient", _client(captured, _Resp(200, _daily(100.0, 13))))

    await pipeline._fetch_gdd("t", "2026-10-01", "p1")

    assert captured["params"]["base_temp"] == "10.0"
    assert captured["params"]["upper_cutoff"] == "30.0"


@pytest.mark.asyncio
async def test_fetch_gdd_none_when_series_does_not_cover_season(env, monkeypatch):
    """A season total from a partial series would understate it: no total."""
    captured = {}
    monkeypatch.setattr(httpx, "AsyncClient", _client(captured, _Resp(200, _daily(300.0, 11))))

    assert await pipeline._fetch_gdd("t", "2026-10-01", "p1") is None


@pytest.mark.asyncio
async def test_fetch_gdd_zero_before_first_closed_day(env, monkeypatch):
    """Sown today: nothing accumulated yet, and nothing to ask for."""
    captured = {}
    monkeypatch.setattr(httpx, "AsyncClient", _client(captured, _Resp(500)))

    assert await pipeline._fetch_gdd("t", "2026-10-14", "p1") == {"gdd_total": 0.0, "days_count": 0}
    assert "url" not in captured


@pytest.mark.asyncio
async def test_fetch_gdd_none_when_season_longer_than_daily_range(env, monkeypatch):
    captured = {}
    monkeypatch.setattr(httpx, "AsyncClient", _client(captured, _Resp(200, _daily(1.0, 1))))

    assert await pipeline._fetch_gdd("t", "2025-01-01", "p1") is None
    assert "url" not in captured


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 404, 503])
async def test_fetch_gdd_none_on_http_error(env, monkeypatch, status):
    monkeypatch.setattr(httpx, "AsyncClient", _client({}, _Resp(status)))

    assert await pipeline._fetch_gdd("t", "2026-10-01", "p1") is None


@pytest.mark.asyncio
async def test_fetch_gdd_none_on_timeout(env, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _client({}, exc=httpx.TimeoutException("timeout")))

    assert await pipeline._fetch_gdd("t", "2026-10-01", "p1") is None


@pytest.mark.asyncio
async def test_fetch_gdd_none_without_url(env, monkeypatch):
    captured = {}
    monkeypatch.setattr(env, "weather_daily_url", "")
    monkeypatch.setattr(httpx, "AsyncClient", _client(captured, _Resp(200, _daily(1.0, 13))))

    assert await pipeline._fetch_gdd("t", "2026-10-01", "p1") is None
    assert "url" not in captured


@pytest.mark.asyncio
async def test_fetch_gdd_none_without_signing_secret(env, monkeypatch):
    """weather-api rejects unsigned calls: do not send one."""
    captured = {}
    monkeypatch.setattr(pipeline, "_hmac_secret", lambda: "")
    monkeypatch.setattr(httpx, "AsyncClient", _client(captured, _Resp(200, _daily(1.0, 13))))

    assert await pipeline._fetch_gdd("t", "2026-10-01", "p1") is None
    assert "url" not in captured
