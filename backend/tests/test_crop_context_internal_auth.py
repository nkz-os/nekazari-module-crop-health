"""crop-context calls to BioOrchestrator must carry the internal service secret."""
import pytest
import respx
from httpx import Response

from app.config import get_settings
from app.services import context_client


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "bioorchestrator_url", "http://bioorch.test")
    monkeypatch.setattr(s, "internal_service_secret", "s3cret")
    context_client._crop_context_cache.clear()
    yield


@respx.mock
async def test_crop_context_sends_internal_secret_and_tenant():
    route = respx.get("http://bioorch.test/api/graph/agriculture/crop-context").mock(
        return_value=Response(404)
    )
    await context_client.get_crop_context("urn:ngsi-ld:AgriParcel:tenant-a:p1", tenant_id="tenant-a")
    req = route.calls.last.request
    assert req.headers["X-Internal-Service-Secret"] == "s3cret"
    assert req.headers["X-Tenant-ID"] == "tenant-a"
    assert req.headers["X-User-ID"] == "crop-health-worker"


@respx.mock
async def test_crop_context_without_tenant_sends_no_identity():
    route = respx.get("http://bioorch.test/api/graph/agriculture/crop-context").mock(
        return_value=Response(404)
    )
    await context_client.get_crop_context("urn:ngsi-ld:AgriParcel:tenant-a:p1", tenant_id="")
    req = route.calls.last.request
    assert "X-Internal-Service-Secret" not in req.headers
    assert "X-Tenant-ID" not in req.headers
