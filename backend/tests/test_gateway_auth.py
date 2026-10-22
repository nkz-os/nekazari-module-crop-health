"""User routes trust only a gateway-signed identity (X-Auth-Signature)."""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from nkz_platform_sdk import auth as sdk_auth
from nkz_platform_sdk.crypto import generate_hmac_signature

from app.auth import ensure_signature_enforced, gateway_identity
from app.main import app

SECRET = "test-hmac-secret"
TOKEN = "user-jwt"
PATH = "/api/crop-health/parcels/p1/phenology-status"
# Routes that authenticate by their own credential, not the gateway identity.
OWN_AUTH_PREFIXES = ("/api/crop-health/internal/", "/api/crop-health/webhooks/")
PUBLIC = {"/health", "/api/crop-health/docs", "/api/crop-health/redoc",
          "/api/crop-health/openapi.json", "/api/crop-health/docs/oauth2-redirect"}


def _dependency_calls(dependant):
    for dep in dependant.dependencies:
        yield dep.call
        yield from _dependency_calls(dep)


def test_every_user_route_requires_gateway_identity():
    unguarded = []
    for route in app.routes:
        if not isinstance(route, APIRoute) or route.path in PUBLIC:
            continue
        if route.path.startswith(OWN_AUTH_PREFIXES):
            continue
        if gateway_identity not in set(_dependency_calls(route.dependant)):
            unguarded.append(route.path)
    assert unguarded == []


@pytest.fixture
def signed_mode(monkeypatch):
    monkeypatch.setattr(sdk_auth, "REQUIRE_HMAC", True)
    monkeypatch.setattr(sdk_auth, "HMAC_SECRET", SECRET)


@pytest.fixture
def client(monkeypatch):
    from app.api import phenology

    seen = {}

    async def _latest(parcel_id, tenant_id):
        seen["tenant_id"] = tenant_id
        return None

    monkeypatch.setattr(phenology, "_read_latest_assessment", _latest)
    with patch("app.services.redis_state.RedisState.create", AsyncMock()):
        c = TestClient(app)
        c.seen = seen
        yield c


def _headers(tenant, signature=None):
    h = {"X-Tenant-ID": tenant, "X-User-ID": "user-1", "Authorization": f"Bearer {TOKEN}"}
    if signature is not None:
        h["X-Auth-Signature"] = signature
    return h


def test_unsigned_identity_rejected(signed_mode, client):
    resp = client.get(PATH, headers=_headers("tenant-a"))
    assert resp.status_code == 401
    assert "tenant_id" not in client.seen


def test_signature_for_other_tenant_rejected(signed_mode, client):
    sig = generate_hmac_signature(SECRET, TOKEN, "tenant-b")
    resp = client.get(PATH, headers=_headers("tenant-a", sig))
    assert resp.status_code == 401
    assert "tenant_id" not in client.seen


def test_signed_identity_accepted(signed_mode, client):
    sig = generate_hmac_signature(SECRET, TOKEN, "tenant-a")
    resp = client.get(PATH, headers=_headers("tenant-a", sig))
    assert resp.status_code == 200
    assert client.seen["tenant_id"] == "tenant-a"


def test_missing_identity_rejected(client):
    resp = client.get(PATH)
    assert resp.status_code == 401


def test_startup_refuses_without_signature_check(monkeypatch):
    monkeypatch.setattr(sdk_auth, "REQUIRE_HMAC", False)
    monkeypatch.setattr(sdk_auth, "HMAC_SECRET", SECRET)
    with pytest.raises(RuntimeError):
        ensure_signature_enforced()
    monkeypatch.setattr(sdk_auth, "REQUIRE_HMAC", True)
    monkeypatch.setattr(sdk_auth, "HMAC_SECRET", "")
    with pytest.raises(RuntimeError):
        ensure_signature_enforced()


def test_startup_accepts_enforced_signature(signed_mode):
    ensure_signature_enforced()


def test_internal_route_rejects_wrong_secret(client, monkeypatch):
    from app.api import setup

    monkeypatch.setattr(setup, "INTERNAL_SECRET", "real-secret")
    resp = client.post(
        "/api/crop-health/internal/run-scheduled-assessments",
        json={"tenant_id": "tenant-a"},
        headers={"X-Internal-Service-Secret": "wrong-secret"},
    )
    assert resp.status_code == 401
