"""GET /parcels and /assessments/latest: crop status, next job, surprise."""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app

HEADERS = {"X-Tenant-ID": "tenant-a", "X-User-ID": "user-a"}
PREFIX = "urn:ngsi-ld:AgriParcel:"


def _ago(hours):
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _assessment(pid, hours=2, **extra):
    return {
        "id": f"urn:ngsi-ld:CropHealthAssessment:{pid}",
        "hasAgriParcel": {"type": "Relationship", "object": PREFIX + pid},
        "overallSeverity": "LOW",
        "assessedAt": _ago(hours),
        "cropName": "SECCE",
        **extra,
    }


def _active(date="2026-03-01"):
    return {"current": {"start": {"provenance": "actual", "date": date}}, "pending": None}


NONE_TL = {"current": None, "pending": None}
SOW_TL = {"current": None, "pending": {"species": "TRZAX", "names": {"es": "Trigo"},
                                       "start": {"provenance": "planned", "date": "2099-10-20"}}}


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _setup(mock, assessments, parcels, alerts=()):
    mock.get(url__regex=r".*type=CropHealthAssessment.*").respond(json=assessments)
    mock.get(url__regex=r".*type=AgriParcel.*").respond(json=[
        {"id": PREFIX + p, "name": p} for p in parcels])
    mock.get(url__regex=r".*type=Alert.*").respond(json=list(alerts))
    mock.get(url__regex=r".*agro-status.*").respond(404)
    mock.get(url__regex=r".*/api/timeseries/.*").respond(json={"data": []})


def _timelines(table):
    async def fake(tenant, urn, **kw):
        return table[urn.replace(PREFIX, "")]
    return AsyncMock(side_effect=fake)


async def _get(path):
    state = MagicMock()
    state.get_json = AsyncMock(return_value=None)
    with patch("app.api.assessments.get_redis_state", return_value=state):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test",
                               headers=HEADERS) as c:
            return await c.get(path)


@pytest.mark.anyio
async def test_parcel_without_active_crop_is_stale_and_sows_next():
    with respx.mock as mock, patch("app.services.worklist_sources.fetch_crop_timeline",
                                   _timelines({"p1": SOW_TL})):
        _setup(mock, [_assessment("p1", hours=2)], ["p1"])
        resp = await _get("/api/crop-health/parcels")
    row = next(p for p in resp.json()["parcels"] if p["parcelId"] == "p1")
    assert row["cropStatus"] == "none" and row["stale"] is True
    assert row["nextJob"]["kind"] == "sow" and row["lastAssessment"]["cropName"] == "SECCE"
    assert row["plannedCrop"] == {"species": "TRZAX", "names": {"es": "Trigo"}, "sowingDate": "2099-10-20"}


@pytest.mark.anyio
async def test_newly_activated_parcel_is_pending_assessment():
    with respx.mock as mock, patch("app.services.worklist_sources.fetch_crop_timeline",
                                   _timelines({"p1": _active()})):
        _setup(mock, [], ["p1"])
        resp = await _get("/api/crop-health/parcels")
    row = resp.json()["parcels"][0]
    assert (row["cropStatus"], row["freshness"], row["nextJob"]["kind"]) == ("active", "none", "pending_assessment")
    assert row["lastAssessment"] is None and row["plannedCrop"] is None


@pytest.mark.anyio
async def test_summary_counts_and_order():
    tls = {"p-surprise": _active(), "p-today": _active(), "p-quiet": _active(),
           "p-none": NONE_TL, "p-nodata": _active()}
    assessments = [
        _assessment("p-surprise", vigorCondition="below_expected"),
        _assessment("p-today", recommendedAction="IRRIGATE_NOW"),
        _assessment("p-quiet"),
        _assessment("p-none", hours=24 * 30),
    ]
    with respx.mock as mock, patch("app.services.worklist_sources.fetch_crop_timeline", _timelines(tls)):
        _setup(mock, assessments, list(tls))
        resp = await _get("/api/crop-health/parcels")
    data = resp.json()
    assert data["summary"] == {"surprises": 1, "jobsToday": 1, "noData": 1}
    assert [p["parcelId"] for p in data["parcels"]] == ["p-surprise", "p-today", "p-quiet", "p-none", "p-nodata"]
    assert all({"cropStatus", "freshness", "stale", "nextJob", "surprise", "plannedCrop", "lastAssessment"} <= set(p)
               for p in data["parcels"])


@pytest.mark.anyio
async def test_failing_timeline_never_fails_endpoint_and_alert_is_per_parcel():
    alert = {"id": "urn:ngsi-ld:Alert:a1", "type": "Alert", "alertSource": "x"}
    with respx.mock as mock, patch("app.services.worklist_sources.fetch_crop_timeline",
                                   AsyncMock(side_effect=RuntimeError("boom"))), \
         patch("app.api.assessments._active_alert_rows", AsyncMock(return_value=[
             {"id": "a1", "parcelId": "p1", "risk_level": "HIGH", "disease": "rust"}])):
        _setup(mock, [_assessment("p1"), _assessment("p2")], ["p1", "p2"], [alert])
        resp = await _get("/api/crop-health/parcels")
    assert resp.status_code == 200
    rows = {p["parcelId"]: p for p in resp.json()["parcels"]}
    assert rows["p1"]["nextJob"]["kind"] == "treat" and rows["p2"]["nextJob"] is None


@pytest.mark.anyio
async def test_latest_with_parcel_id_adds_root_fields_and_without_does_not():
    with respx.mock as mock, patch("app.services.worklist_sources.fetch_crop_timeline",
                                   _timelines({"p1": SOW_TL})):
        _setup(mock, [_assessment("p1")], ["p1"])
        one = (await _get("/api/crop-health/assessments/latest?parcelId=p1")).json()
        allr = (await _get("/api/crop-health/assessments/latest")).json()
    assert one["cropStatus"] == "none" and one["stale"] is True and one["nextJob"]["kind"] == "sow"
    assert {"freshness", "surprise", "plannedCrop"} <= set(one) and one["assessments"]
    assert set(allr) == {"assessments"}
