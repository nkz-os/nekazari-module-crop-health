"""fetch_in_season: start or join the job, poll until settled, never raise."""
import httpx
import pytest
import respx

from app.services import in_season_client
from app.services.in_season_client import fetch_in_season

URN = "urn:ngsi-ld:AgriParcel:p1"
BASE = "http://bioorch.test"
URL = f"{BASE}/api/graph/planning/parcels/urn%3Angsi-ld%3AAgriParcel%3Ap1/estimates/in-season"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    s = in_season_client.get_settings()
    monkeypatch.setattr(s, "bioorchestrator_url", BASE)
    monkeypatch.setattr(s, "internal_service_secret", "sec")


def _ans(state, **kw):
    return {"contract_version": "2.1", "provider_id": "aquacrop", "state": state, "job_id": "j1", **kw}


@pytest.mark.anyio
async def test_polls_until_done_with_job_id_and_headers():
    with respx.mock as m:
        route = m.get(URL).mock(side_effect=[
            httpx.Response(200, json=_ans("queued")),
            httpx.Response(200, json=_ans("running")),
            httpx.Response(200, json=_ans("done", estimates=[{"provider_id": "aquacrop"}])),
        ])
        out = await fetch_in_season(URN, "tenant-a", poll_interval=0, timeout=5)
    assert out["state"] == "done"
    first, second = route.calls[0].request, route.calls[1].request
    assert first.headers["X-Internal-Service-Secret"] == "sec"
    assert first.headers["X-Tenant-ID"] == "tenant-a"
    assert first.headers["X-User-ID"] == "crop-health-worker"
    assert "job_id" not in str(first.url)
    assert "job_id=j1" in str(second.url)


@pytest.mark.anyio
async def test_unavailable_returned_at_once():
    with respx.mock as m:
        m.get(URL).respond(200, json=_ans("unavailable", unavailable=[{"provider_id": "aquacrop", "reason": "not_sown"}]))
        out = await fetch_in_season(URN, "tenant-a", poll_interval=0, timeout=5)
    assert out["state"] == "unavailable"


@pytest.mark.anyio
async def test_timeout_returns_last_running():
    with respx.mock as m:
        m.get(URL).respond(200, json=_ans("running"))
        out = await fetch_in_season(URN, "tenant-a", poll_interval=0, timeout=0)
    assert out["state"] == "running"


@pytest.mark.anyio
@pytest.mark.parametrize("resp,code", [
    (httpx.Response(503, text="x"), "503"),
    (httpx.Response(200, text="not json"), "invalid_json"),
    (httpx.Response(200, json={"contract_version": "3.0", "state": "done"}), "contract_mismatch"),
])
async def test_failures_are_synthesized(resp, code):
    with respx.mock as m:
        m.get(URL).mock(return_value=resp)
        out = await fetch_in_season(URN, "tenant-a", poll_interval=0, timeout=5)
    assert out["state"] == "failed"
    assert out["unavailable"][0]["reason"] == "request_failed"
    assert out["unavailable"][0]["code"] == code


@pytest.mark.anyio
async def test_network_error_is_synthesized():
    with respx.mock as m:
        m.get(URL).mock(side_effect=httpx.ConnectError("boom"))
        out = await fetch_in_season(URN, "tenant-a", poll_interval=0, timeout=5)
    assert out["unavailable"][0]["code"] == "ConnectError"


@pytest.mark.anyio
async def test_minor_contract_accepted():
    with respx.mock as m:
        m.get(URL).respond(200, json={**_ans("done"), "contract_version": "2.2"})
        out = await fetch_in_season(URN, "tenant-a", poll_interval=0, timeout=5)
    assert out["state"] == "done"


@pytest.fixture
def anyio_backend():
    return "asyncio"
