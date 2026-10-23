"""Shapes the real Orion-LD sends and returns (tenant header, links, orderBy, throttling)."""

import os
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("POSTGRES_URL", "postgresql://test:test@localhost:5432/test")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("INTERNAL_SERVICE_SECRET", "test-secret")
os.environ.setdefault("API_PREFIX", "/api/crop-health")
os.environ.setdefault("KEYCLOAK_URL", "http://keycloak:8080/auth")

DEVICE_URN = "urn:ngsi-ld:Device:acme:probe-01"
PARCEL_URN = "urn:ngsi-ld:AgriParcel:acme:p1"


# --- B4: tenant header -------------------------------------------------------

def _post_with(headers):
    from fastapi.testclient import TestClient

    from app.main import app

    payload = {"data": [{
        "id": "urn:ngsi-ld:DeviceMeasurement:acme:probe-01:leafTemperature",
        "type": "DeviceMeasurement",
        "refDevice": {"type": "Relationship", "object": DEVICE_URN},
        "controlledProperty": {"type": "Property", "value": "leafTemperature"},
        "numValue": {"type": "Property", "value": 28.5},
        "dateObserved": {"type": "Property", "value": "2026-08-29T09:00:00Z"},
    }]}
    return TestClient(app).post("/api/crop-health/webhooks/fiware-sensors", json=payload, headers=headers)


@pytest.mark.parametrize(
    "headers,expected",
    [
        ({"NGSILD-Tenant": "acme"}, "acme"),
        ({"NGSILD-Tenant": "Acme"}, "acme"),
        ({"Fiware-Service": "acme"}, "acme"),
        ({"NGSILD-Tenant": "acme", "Fiware-Service": "other"}, "acme"),
    ],
)
def test_webhook_tenant_header(monkeypatch, headers, expected):
    from app.api import webhooks
    import app.main as _main

    class _R:
        async def store_reading(self, **k):
            pass

    monkeypatch.setattr(_main, "get_redis_state", lambda: _R(), raising=False)
    seen = []

    async def _trigger(entity_id, metric_type, redis_state, parcel_id, tenant_id):
        seen.append(tenant_id)

    async def _record(**k):
        pass

    monkeypatch.setattr(webhooks.pipeline, "trigger", _trigger, raising=False)
    monkeypatch.setattr(webhooks.pipeline, "record_parcel_reading", _record, raising=False)
    assert _post_with(headers).status_code == 204
    assert seen == [expected]


# --- B2: device -> parcel link forms ----------------------------------------

@pytest.mark.parametrize("attr", ["controlledAsset", "hasAgriParcel", "refAgriParcel"])
@pytest.mark.parametrize(
    "link",
    [
        PARCEL_URN,
        {"type": "Property", "value": PARCEL_URN},
        {"type": "Relationship", "object": PARCEL_URN},
    ],
)
@pytest.mark.asyncio
async def test_resolve_parcel_accepts_every_link_form(monkeypatch, attr, link):
    from app.services import pipeline

    class _Client:
        def __init__(self, *a, **k):
            pass

        async def get_entity(self, entity_id, options=None):
            return {"id": DEVICE_URN, "type": "Device", attr: link}

        async def close(self):
            pass

    import nkz_platform_sdk.orion as orion_mod

    monkeypatch.setattr(orion_mod, "OrionClient", _Client)
    assert await pipeline._resolve_parcel_from_device(DEVICE_URN, "acme") == "acme:p1"


def test_parcel_link_target_forms():
    from app.services.parcel_link import parcel_link_target

    assert parcel_link_target(PARCEL_URN) == PARCEL_URN
    assert parcel_link_target({"value": PARCEL_URN}) == PARCEL_URN
    assert parcel_link_target({"object": PARCEL_URN}) == PARCEL_URN
    assert parcel_link_target({"object": ""}) == ""
    assert parcel_link_target(None) == ""
    assert parcel_link_target({"value": 3}) == ""


# --- B3: regional meteo ------------------------------------------------------

class _Resp:
    def __init__(self, status, payload):
        self.status_code = status
        self._p = payload

    def json(self):
        return self._p


def _client(payload, calls):
    class _Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, params=None, headers=None):
            calls.append(params)
            if "orderBy" in params and params.get("local") != "true":
                return _Resp(501, {"detail": "The URL parameter 'orderBy' only works if also 'local' is set"})
            return _Resp(200, payload)

    return lambda **kw: _Client()


@pytest.mark.asyncio
async def test_regional_meteo_sends_local_and_reads_observed_shape(monkeypatch):
    from app.services import pipeline
    import httpx

    observed = [{
        "id": "urn:ngsi-ld:WeatherObserved:t:s1", "type": "WeatherObserved",
        "refAgriParcel": PARCEL_URN, "dateObserved": "2026-10-23T08:27:37Z",
        "solarRadiation": 800, "airTemperature": 24,
    }]
    calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _client(observed, calls))
    out = await pipeline._regional_meteo("p1", "test-tenant")
    assert out["air_temp_c"] == 24.0
    assert out["solar_radiation_wm2"] == 800.0
    assert out["observed_at_ts"] == 1792744057.0
    assert all(c.get("local") == "true" for c in calls if "orderBy" in c)


@pytest.mark.asyncio
async def test_regional_meteo_fallback_query_sends_local(monkeypatch):
    from app.services import pipeline
    import httpx

    calls = []
    monkeypatch.setattr(httpx, "AsyncClient", _client([], calls))
    await pipeline._regional_meteo("p1", "test-tenant")
    assert len(calls) == 2
    assert all(c.get("local") == "true" for c in calls)


@pytest.mark.asyncio
async def test_regional_meteo_humidity_alias(monkeypatch):
    from app.services import pipeline
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _client([{"humidity": 55}], []))
    out = await pipeline._regional_meteo("p1", "test-tenant")
    assert out["rh_pct"] == 55.0


# --- B5: throttling ----------------------------------------------------------

@pytest.mark.asyncio
async def test_subscription_spec_has_no_throttling():
    from app.api import setup

    with patch.object(setup, "INTERNAL_SECRET", "s3cr3t"), \
         patch("app.api.setup.ModuleActivation") as MA, \
         patch("app.api.setup.SubscriptionRegistrar") as SR:
        MA.return_value.ensure_entities = AsyncMock(
            return_value={"created": 0, "skipped": 2, "errors": [], "entity_ids": []})
        MA.return_value.close = AsyncMock()
        SR.return_value.ensure_all = AsyncMock(return_value={"created": 0, "skipped": 1, "errors": []})
        body = setup.SetupParcelRequest(parcel_id="p1", tenant_id="test-tenant", action="activate")
        req = type("R", (), {"headers": {"X-Internal-Service-Secret": "s3cr3t"}, "client": None})()
        await setup.setup_parcel(req, body)  # type: ignore[arg-type]
    # The SDK defaults a missing key to 30 s: "none" must be an explicit None.
    from nkz_platform_sdk.subscriptions import SubscriptionRegistrar as Real

    real = Real(
        orion_url="http://orion:1026",
        notification_url="http://self/api/crop-health/webhooks/fiware-sensors",
        subscriptions=SR.call_args.kwargs["subscriptions"],
        module_name="crop-health",
    )
    assert "throttling" not in real._body(real._subs[0], "test-tenant")
