"""Vegetation monitoring client: fail-safe reads, one candidates call per tenant per window."""
import httpx
import pytest
import respx

from app.services import vegetation_monitoring as vm

BASE = "http://vegetation.test"
URN = "urn:ngsi-ld:AgriParcel:p1"
STATE = {"crop": {"present": True}, "monitoring": "none", "period": {"start": "2026-03-01", "end": None},
         "needs_activation": True, "continuous_by": [], "activation_roles": ["Farmer"]}


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    s = vm.get_settings()
    monkeypatch.setattr(s, "vegetation_internal_url", BASE)
    monkeypatch.setattr(s, "internal_service_secret", "sec")
    vm._candidates_cache.clear()
    vm._down_until.clear()


@pytest.mark.anyio
async def test_parcel_monitoring_sends_secret_and_tenant():
    with respx.mock as m:
        route = m.get(f"{BASE}/api/internal/vegetation/parcels/urn%3Angsi-ld%3AAgriParcel%3Ap1/monitoring").respond(
            200, json=STATE)
        out = await vm.parcel_monitoring("tenant-a", URN)
    assert out == STATE
    req = route.calls[0].request
    assert req.headers["X-Internal-Service-Secret"] == "sec"
    assert req.url.params["tenant_id"] == "tenant-a"


@pytest.mark.anyio
@pytest.mark.parametrize("resp", [
    httpx.Response(500), httpx.Response(404), httpx.Response(200, text="not json"),
    httpx.Response(200, json=["x"]), httpx.ConnectError("down"), httpx.ReadTimeout("slow")])
async def test_parcel_monitoring_failure_is_none_and_warns(resp, caplog):
    with respx.mock as m, caplog.at_level("WARNING"):
        m.get(url__regex=r".*/monitoring.*").mock(side_effect=[resp])
        assert await vm.parcel_monitoring("tenant-a", URN) is None
    assert "vegetation monitoring" in caplog.text


@pytest.mark.anyio
async def test_empty_url_calls_nothing(monkeypatch):
    monkeypatch.setattr(vm.get_settings(), "vegetation_internal_url", "")
    with respx.mock(assert_all_called=False) as m:
        route = m.route().respond(200, json={})
        assert await vm.parcel_monitoring("tenant-a", URN) is None
        assert await vm.tenant_candidates("tenant-a") is None
    assert route.call_count == 0


@pytest.mark.anyio
async def test_candidates_set_and_cached_five_minutes(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(vm, "_monotonic", lambda: now[0])
    body = {"tenant_id": "tenant-a", "candidates": [{"entity_id": URN}, {"entity_id": "urn:ngsi-ld:AgriParcel:p2"}],
            "partial": False, "failed": []}
    with respx.mock as m:
        route = m.get(f"{BASE}/api/internal/vegetation/monitoring/candidates").respond(200, json=body)
        assert await vm.tenant_candidates("tenant-a") == {URN, "urn:ngsi-ld:AgriParcel:p2"}
        assert await vm.tenant_candidates("tenant-a") == {URN, "urn:ngsi-ld:AgriParcel:p2"}
        assert route.call_count == 1
        now[0] += vm.CANDIDATES_TTL_S + 1
        await vm.tenant_candidates("tenant-a")
        assert route.call_count == 2
        await vm.tenant_candidates("tenant-b")
        assert route.call_count == 3


@pytest.mark.anyio
async def test_failure_is_remembered_for_a_minute_then_retried(monkeypatch, caplog):
    now = [1000.0]
    monkeypatch.setattr(vm, "_monotonic", lambda: now[0])
    with respx.mock as m, caplog.at_level("WARNING"):
        route = m.get(f"{BASE}/api/internal/vegetation/monitoring/candidates").mock(
            side_effect=[httpx.ReadTimeout("slow"), httpx.Response(200, json={"candidates": []})])
        assert await vm.tenant_candidates("tenant-a") is None
        assert await vm.tenant_candidates("tenant-a") is None
        assert route.call_count == 1
        # the parcel state shares the tenant's "down" window
        assert await vm.parcel_monitoring("tenant-a", URN) is None
        assert route.call_count == 1
        # another tenant is not affected
        m.get(f"{BASE}/api/internal/vegetation/monitoring/candidates").respond(200, json={"candidates": []})
        assert await vm.tenant_candidates("tenant-b") == set()
        now[0] += vm.FAILURE_TTL_S + 1
        assert await vm.tenant_candidates("tenant-a") == set()
    assert "vegetation monitoring" in caplog.text


@pytest.mark.anyio
async def test_optional_calls_use_a_short_timeout():
    assert vm._TIMEOUT_S <= 3.0


@pytest.mark.anyio
async def test_a_missing_parcel_does_not_mark_the_tenant_down():
    with respx.mock as m:
        m.get(url__regex=r".*/parcels/.*/monitoring.*").respond(404)
        route = m.get(f"{BASE}/api/internal/vegetation/monitoring/candidates").respond(200, json={"candidates": []})
        assert await vm.parcel_monitoring("tenant-a", URN) is None
        assert await vm.tenant_candidates("tenant-a") == set()
    assert route.call_count == 1
