"""pipeline._fetch_daily_water: daily rain and ET0 from weather-api."""

from datetime import date

import httpx
import pytest

from app.config import get_settings
from app.services import pipeline
from tests.test_gdd_integration import SECRET, _Resp, _client

START = date(2026, 10, 20)
END = date(2026, 10, 21)


@pytest.fixture
def env(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "weather_daily_url", "http://wx:8000")
    monkeypatch.setattr(pipeline, "_hmac_secret", lambda: SECRET)
    return settings


@pytest.mark.asyncio
async def test_daily_water_maps_days(env, monkeypatch):
    captured = {}
    payload = {"days": [
        {"date": "2026-10-20", "precip_mm": 3.2, "et0_mm": 2.1},
        {"date": "2026-10-21", "precip_mm": None, "et0_mm": 1.9},
    ]}
    monkeypatch.setattr(httpx, "AsyncClient", _client(captured, _Resp(200, payload)))

    result = await pipeline._fetch_daily_water("tenant-a", "urn:ngsi-ld:AgriParcel:p-1", START, END)

    assert result == {"2026-10-20": (3.2, 2.1), "2026-10-21": (None, 1.9)}
    assert captured["url"].endswith("/api/weather/parcel/p-1/daily")
    assert captured["params"] == {"start": "2026-10-20", "end": "2026-10-21", "fill": "open_meteo"}
    assert captured["headers"]["X-Tenant-ID"] == "tenant-a"
    assert captured["headers"]["X-Auth-Signature"]


@pytest.mark.asyncio
async def test_daily_water_http_error_is_none(env, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _client({}, _Resp(503)))
    assert await pipeline._fetch_daily_water("tenant-a", "p-1", START, END) is None


@pytest.mark.asyncio
async def test_daily_water_exception_is_none(env, monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _client({}, exc=httpx.ConnectError("down")))
    assert await pipeline._fetch_daily_water("tenant-a", "p-1", START, END) is None
