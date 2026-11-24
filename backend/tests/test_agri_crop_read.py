"""Reading the parcel's AgriCrop: cache scope and broker failures."""

import pytest
from fastapi.testclient import TestClient

from app.api import setup as setup_mod
from app.main import app
from app.services import context_client, pipeline

PARCEL = "6f9619ff-8b86-4011-b42d-00c04fc964ff"


class FakeOrion:
    """Broker double: one answer (rows or an exception) per tenant, counting reads."""

    answers: dict = {}
    reads: list = []

    def __init__(self, tenant_id, **_kw):
        self.tenant_id = tenant_id

    async def query_entities(self, **_kw):
        FakeOrion.reads.append(self.tenant_id)
        answer = FakeOrion.answers.get(self.tenant_id, [])
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def close(self):
        pass


@pytest.fixture(autouse=True)
def _broker(monkeypatch):
    FakeOrion.answers, FakeOrion.reads = {}, []
    context_client._agri_crop_cache.clear()
    monkeypatch.setattr(context_client, "OrionClient", FakeOrion)
    yield
    context_client._agri_crop_cache.clear()


@pytest.mark.asyncio
async def test_the_cached_crop_of_one_tenant_is_not_served_to_another():
    FakeOrion.answers = {"tenant-a": [{"id": "urn:a", "species": "TRZAX"}],
                         "tenant-b": [{"id": "urn:b", "species": "HORVX"}]}

    first = await context_client.get_agri_crop(PARCEL, "tenant-a")
    second = await context_client.get_agri_crop(PARCEL, "tenant-b")

    assert (first["species"], second["species"]) == ("TRZAX", "HORVX")


@pytest.mark.asyncio
async def test_a_parcel_without_crop_is_still_cached():
    assert await context_client.get_agri_crop(PARCEL, "tenant-a") is None
    assert await context_client.get_agri_crop(PARCEL, "tenant-a") is None

    assert FakeOrion.reads == ["tenant-a"]


@pytest.mark.asyncio
async def test_a_failed_read_is_not_reported_as_no_crop():
    FakeOrion.answers = {"tenant-a": TimeoutError("broker")}

    with pytest.raises(context_client.CropUnavailable):
        await context_client.get_agri_crop(PARCEL, "tenant-a")


@pytest.mark.asyncio
async def test_a_failed_read_is_not_cached():
    FakeOrion.answers = {"tenant-a": TimeoutError("broker")}
    with pytest.raises(context_client.CropUnavailable):
        await context_client.get_agri_crop(PARCEL, "tenant-a")

    FakeOrion.answers = {"tenant-a": [{"id": "urn:a", "species": "TRZAX"}]}

    assert (await context_client.get_agri_crop(PARCEL, "tenant-a"))["species"] == "TRZAX"


@pytest.mark.asyncio
async def test_compute_assessment_fails_when_the_crop_cannot_be_read():
    FakeOrion.answers = {"tenant-a": TimeoutError("broker")}

    with pytest.raises(context_client.CropUnavailable):
        await pipeline.compute_assessment(f"urn:ngsi-ld:AgriParcel:{PARCEL}", "tenant-a")


def test_the_nightly_run_reports_an_unreadable_crop_as_an_error(monkeypatch):
    FakeOrion.answers = {"tenant-a": TimeoutError("broker")}
    urn = f"urn:ngsi-ld:AgriParcel:{PARCEL}"

    async def _one_parcel(tenant_id, cursor, batch_size):
        return [urn], None

    monkeypatch.setattr(setup_mod, "INTERNAL_SECRET", "s")
    monkeypatch.setattr(setup_mod, "_list_active_crop_parcels", _one_parcel)

    body = TestClient(app).post(
        "/api/crop-health/internal/run-scheduled-assessments",
        headers={"X-Internal-Service-Secret": "s"}, json={"tenant_id": "tenant-a"},
    ).json()

    assert body["written"] == 0
    assert [e["parcel"] for e in body["errors"]] == [urn]
