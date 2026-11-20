"""Water-loss relay: route behaviour and the bioorch client's failure mapping."""
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import water_loss_client

H = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u1"}
BARE = "d2e55461-eeb2-411d-b5f6-2f026e536914"
URN = f"urn:ngsi-ld:AgriParcel:{BARE}"
ANSWER = {"contract_version": "2.11", "state": "done", "stages": [{"gain_pct_of_potential": 3.2}]}


def _route(monkeypatch, result):
    fake = AsyncMock(return_value=result)
    monkeypatch.setattr("app.api.water_loss.fetch_water_loss", fake)
    return TestClient(app), fake


def test_relays_done_answer(monkeypatch):
    c, _ = _route(monkeypatch, ANSWER)
    r = c.get(f"/api/crop-health/parcels/{URN}/water-loss-by-stage", headers=H)
    assert r.status_code == 200 and r.json() == ANSWER


def test_retry_forwarded(monkeypatch):
    c, fake = _route(monkeypatch, ANSWER)
    c.get(f"/api/crop-health/parcels/{URN}/water-loss-by-stage?retry=true", headers=H)
    assert fake.await_args.kwargs == {"retry": True}
    c.get(f"/api/crop-health/parcels/{URN}/water-loss-by-stage", headers=H)
    assert fake.await_args.kwargs == {"retry": False}


def test_bare_id_normalised_to_urn(monkeypatch):
    c, fake = _route(monkeypatch, ANSWER)
    c.get(f"/api/crop-health/parcels/{BARE}/water-loss-by-stage", headers=H)
    assert fake.await_args.args == (URN, "tenant-a")


def test_invalid_id_422(monkeypatch):
    c, fake = _route(monkeypatch, ANSWER)
    r = c.get("/api/crop-health/parcels/bad id!/water-loss-by-stage", headers=H)
    assert r.status_code == 422
    assert fake.await_count == 0


def test_unknown_parcel_404(monkeypatch):
    c, _ = _route(monkeypatch, None)
    assert c.get(f"/api/crop-health/parcels/{URN}/water-loss-by-stage", headers=H).status_code == 404


def test_route_needs_identity(monkeypatch):
    c, _ = _route(monkeypatch, ANSWER)
    assert c.get(f"/api/crop-health/parcels/{URN}/water-loss-by-stage").status_code == 401


# --- client ---------------------------------------------------------------

def _patch_transport(monkeypatch, handler):
    real = httpx.AsyncClient

    def factory(*a, **kw):
        kw["transport"] = httpx.MockTransport(handler)
        return real(*a, **kw)

    monkeypatch.setattr(water_loss_client.httpx, "AsyncClient", factory)


async def test_transport_error_failed(monkeypatch):
    def handler(request):
        raise httpx.ConnectError("boom")

    _patch_transport(monkeypatch, handler)
    out = await water_loss_client.fetch_water_loss(URN, "tenant-a")
    assert out["state"] == "failed"
    assert out["unavailable"][0]["reason"] == "request_failed"
    assert out["unavailable"][0]["code"] == "ConnectError"


async def test_http_500_failed(monkeypatch):
    _patch_transport(monkeypatch, lambda request: httpx.Response(500))
    out = await water_loss_client.fetch_water_loss(URN, "tenant-a")
    assert out["state"] == "failed" and out["unavailable"][0]["code"] == "500"


async def test_http_404_is_none(monkeypatch):
    _patch_transport(monkeypatch, lambda request: httpx.Response(404))
    assert await water_loss_client.fetch_water_loss(URN, "tenant-a") is None


async def test_bad_json_failed(monkeypatch):
    _patch_transport(monkeypatch, lambda request: httpx.Response(200, content=b"<html>"))
    out = await water_loss_client.fetch_water_loss(URN, "tenant-a")
    assert out["state"] == "failed" and out["unavailable"][0]["code"] == "invalid_json"


async def test_bad_json_is_logged(monkeypatch, caplog):
    _patch_transport(monkeypatch, lambda request: httpx.Response(200, content=b"<html>"))
    with caplog.at_level("WARNING"):
        await water_loss_client.fetch_water_loss(URN, "tenant-a")
    assert "tenant-a" in caplog.text and URN in caplog.text


async def test_non_dict_json_failed_and_logged(monkeypatch, caplog):
    _patch_transport(monkeypatch, lambda request: httpx.Response(200, json=[]))
    with caplog.at_level("WARNING"):
        out = await water_loss_client.fetch_water_loss(URN, "tenant-a")
    assert out["state"] == "failed" and out["unavailable"][0]["code"] == "invalid_json"
    assert "tenant-a" in caplog.text and URN in caplog.text


async def test_missing_contract_version_failed(monkeypatch):
    body = {k: v for k, v in ANSWER.items() if k != "contract_version"}
    _patch_transport(monkeypatch, lambda request: httpx.Response(200, json=body))
    out = await water_loss_client.fetch_water_loss(URN, "tenant-a")
    assert out["state"] == "failed" and out["unavailable"][0]["code"] == "contract_mismatch"


async def test_contract_3_failed(monkeypatch):
    _patch_transport(monkeypatch, lambda request: httpx.Response(200, json={**ANSWER, "contract_version": "3.0"}))
    out = await water_loss_client.fetch_water_loss(URN, "tenant-a")
    assert out["state"] == "failed" and out["unavailable"][0]["code"] == "contract_mismatch"


async def test_contract_2_passes_through(monkeypatch):
    _patch_transport(monkeypatch, lambda request: httpx.Response(200, json=ANSWER))
    assert await water_loss_client.fetch_water_loss(URN, "tenant-a") == ANSWER


@pytest.mark.parametrize("retry", [False, True])
async def test_headers_sent(monkeypatch, retry):
    seen = {}

    def handler(request):
        seen["req"] = request
        return httpx.Response(200, json=ANSWER)

    _patch_transport(monkeypatch, handler)
    await water_loss_client.fetch_water_loss(URN, "tenant-a", retry=retry)
    req = seen["req"]
    assert req.headers["X-Tenant-ID"] == "tenant-a"
    assert req.headers["X-User-ID"] == "crop-health-worker"
    assert "X-Internal-Service-Secret" in req.headers
    assert "estimates/water-loss-by-stage" in str(req.url)
    assert ("retry" in dict(req.url.params)) is retry
    if retry:
        assert req.url.params["retry"] == "true"
