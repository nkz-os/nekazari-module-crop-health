"""GET /parcels and /assessments/latest: crop status, next job, surprise."""
import asyncio
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient
from nkz_platform_sdk.crop_cycles import resolve_crop_cycles

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


def _sdk(*crops):
    """Timeline exactly as the SDK resolver returns it (resolve_crop_cycles(...).to_dict())."""
    parcel = PREFIX + "p1"
    full = [{"id": f"urn:ngsi-ld:AgriCrop:{i}", "hasAgriParcel": parcel, "species": "TRZAX",
             "cropRole": "main_crop", **c} for i, c in enumerate(crops)]
    return resolve_crop_cycles(parcel, full, [], date.today()).to_dict()


def _active(day="2026-03-01"):
    return _sdk({"plantingDate": day, "plantingDateSource": "manual"})


NONE_TL = _sdk()
SOW_TL = _sdk({"sowingWindowStart": "2099-10-20"})
UNDATED_TL = _sdk({})


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
    assert (row["nextJob"]["kind"], row["nextJob"]["when"]) == ("sow", "2099-10-20")
    assert row["lastAssessment"]["cropName"] == "SECCE"
    assert row["plannedCrop"] == {"species": "TRZAX", "sowingDate": "2099-10-20"}


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
           "p-none": NONE_TL, "p-nodata": _active(), "p-nocrop-new": NONE_TL}
    assessments = [
        _assessment("p-surprise", vigorCondition="below_expected"),
        _assessment("p-today", recommendedAction="IRRIGATE_IMMEDIATE"),
        _assessment("p-quiet"),
        _assessment("p-none", hours=24 * 30),
    ]
    with respx.mock as mock, patch("app.services.worklist_sources.fetch_crop_timeline", _timelines(tls)):
        _setup(mock, assessments, list(tls))
        resp = await _get("/api/crop-health/parcels")
    data = resp.json()
    assert data["summary"] == {"surprises": 1, "jobsToday": 1, "noData": 1}
    assert [p["parcelId"] for p in data["parcels"]] == ["p-surprise", "p-today", "p-quiet", "p-none", "p-nocrop-new", "p-nodata"]
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
    assert one["nextJob"]["when"] == "2099-10-20"
    assert {"freshness", "surprise", "plannedCrop"} <= set(one) and one["assessments"]
    assert set(allr) == {"assessments"}


@pytest.mark.anyio
async def test_old_assessment_of_cropless_parcel_does_not_drive_job_or_surprise():
    old = _assessment("p1", hours=24 * 30, recommendedAction="IRRIGATE_IMMEDIATE", vigorCondition="below_expected")
    with respx.mock as mock, patch("app.services.worklist_sources.fetch_crop_timeline",
                                   _timelines({"p1": SOW_TL})):
        _setup(mock, [old], ["p1"])
        row = (await _get("/api/crop-health/parcels")).json()["parcels"][0]
    assert row["nextJob"]["kind"] == "sow" and row["surprise"] is None
    assert row["stale"] is True and row["lastAssessment"]["cropName"] == "SECCE"


@pytest.mark.anyio
async def test_malformed_timeline_degrades_row_not_endpoint():
    with respx.mock as mock, patch("app.services.worklist_sources.fetch_crop_timeline",
                                   _timelines({"p1": "garbage"})):
        _setup(mock, [_assessment("p1", hours=2)], ["p1"])
        resp = await _get("/api/crop-health/parcels")
    assert resp.status_code == 200
    row = resp.json()["parcels"][0]
    assert (row["cropStatus"], row["nextJob"], row["surprise"], row["freshness"]) == ("none", None, None, "fresh")


@pytest.mark.anyio
async def test_latest_without_entities_still_returns_work_fields():
    with respx.mock as mock, patch("app.services.worklist_sources.fetch_crop_timeline",
                                   _timelines({"p1": _active(), "p2": SOW_TL})):
        _setup(mock, [], ["p1", "p2"])
        new = (await _get("/api/crop-health/assessments/latest?parcelId=p1")).json()
        plan = (await _get("/api/crop-health/assessments/latest?parcelId=p2")).json()
    assert new["assessments"] == []
    assert (new["cropStatus"], new["nextJob"]["kind"], new["freshness"]) == ("active", "pending_assessment", "none")
    assert (plan["cropStatus"], plan["nextJob"]["kind"], plan["nextJob"]["when"]) == ("none", "sow", "2099-10-20")


@pytest.mark.anyio
async def test_undated_plan_sows_without_when():
    with respx.mock as mock, patch("app.services.worklist_sources.fetch_crop_timeline",
                                   _timelines({"p1": UNDATED_TL})):
        _setup(mock, [], ["p1"])
        row = (await _get("/api/crop-health/parcels")).json()["parcels"][0]
    assert (row["nextJob"]["kind"], row["nextJob"]["when"]) == ("sow", None)


@pytest.mark.anyio
async def test_cropless_parcel_ignores_old_forecast_and_history():
    done = {"status": "done", "season": {"harvest_date": "2026-06-01"}}
    rising = [{"cwsi": 0.1}, {"cwsi": 0.1}, {"cwsi": 0.1}, {"cwsi": 0.9}]
    inputs = {"timeline": NONE_TL, "agro": None, "forecast": done, "history": rising}
    from app.api.assessments import _worklist_fields
    f = _worklist_fields(assessment=None, assessed_at=None, crop_name=None, inputs=inputs, alerts=[],
                         now=datetime.now(timezone.utc))
    assert f["nextJob"] is None and f["surprise"] is None
    inputs["timeline"] = _active()
    f = _worklist_fields(assessment={}, assessed_at=_ago(1), crop_name=None, inputs=inputs, alerts=[],
                         now=datetime.now(timezone.utc))
    assert f["surprise"]["code"] == "water_drop"


@pytest.mark.anyio
async def test_summary_nodata_counts_active_parcels_without_data_only():
    with respx.mock as mock, patch("app.services.worklist_sources.fetch_crop_timeline",
                                   _timelines({"a": _active(), "b": NONE_TL})):
        _setup(mock, [], ["a", "b"])
        data = (await _get("/api/crop-health/parcels")).json()
    assert data["summary"]["noData"] == 1


@pytest.mark.anyio
async def test_hanging_timeline_fetch_answers_within_deadline():
    async def hang(*a, **kw):
        await asyncio.sleep(30)

    with respx.mock as mock, patch("app.services.worklist_sources.fetch_crop_timeline", hang), \
         patch("app.api.assessments.WORKLIST_PARCEL_TIMEOUT_S", 0.2):
        _setup(mock, [_assessment("p1")], ["p1"])
        resp = await asyncio.wait_for(_get("/api/crop-health/parcels"), timeout=5)
    assert resp.status_code == 200
    assert resp.json()["parcels"][0]["cropStatus"] == "none"


@pytest.mark.anyio
async def test_assessment_query_pages_twice():
    page_size = 3
    first = [_assessment(f"p{i}") for i in range(page_size)]
    second = [_assessment("p9")]
    with respx.mock as mock, patch("app.api.assessments.ORION_PAGE_SIZE", page_size), \
         patch("app.services.worklist_sources.fetch_crop_timeline", _timelines({"p9": _active()})):
        mock.get(url__regex=r".*type=AgriParcel.*").respond(json=[{"id": PREFIX + "p9", "name": "p9"}])
        mock.get(url__regex=r".*type=Alert.*").respond(json=[])
        mock.get(url__regex=r".*agro-status.*").respond(404)
        mock.get(url__regex=r".*/api/timeseries/.*").respond(json={"data": []})
        route = mock.get(url__regex=r".*type=CropHealthAssessment.*")
        route.side_effect = lambda request: httpx.Response(
            200, json=first if request.url.params["offset"] == "0" else second)
        resp = await _get("/api/crop-health/parcels")
    offsets = [c.request.url.params["offset"] for c in route.calls]
    assert offsets == ["0", "3"]
    assert resp.json()["parcels"][0]["hasData"] is True


@pytest.mark.anyio
async def test_orion_down_returns_zero_summary():
    with respx.mock as mock:
        mock.get(url__regex=r".*type=AgriParcel.*").respond(500)
        mock.get(url__regex=r".*type=CropHealthAssessment.*").respond(500)
        mock.get(url__regex=r".*type=Alert.*").respond(500)
        resp = await _get("/api/crop-health/parcels")
    assert resp.json()["parcels"] == []
    assert resp.json()["summary"] == {"surprises": 0, "jobsToday": 0, "noData": 0}


@pytest.mark.anyio
async def test_declared_future_sowing_sets_planned_crop():
    tl = _sdk({"plantingDate": "2099-11-20", "plantingDateSource": "manual", "species": "HORVU"})
    with respx.mock as mock, patch("app.services.worklist_sources.fetch_crop_timeline", _timelines({"p1": tl})):
        _setup(mock, [], ["p1"])
        mock.get(url__regex=r".*agro-status.*").respond(404)
        mock.get(url__regex=r".*/api/timeseries/.*").respond(json={"data": []})
        resp = await _get("/api/crop-health/parcels")
    row = resp.json()["parcels"][0]
    assert row["nextJob"]["kind"] == "sow" and row["nextJob"]["when"] == "2099-11-20"
    assert row["plannedCrop"]["species"] == "HORVU"
    assert row["plannedCrop"]["sowingDate"] == "2099-11-20"


@pytest.mark.anyio
async def test_request_deadline_bounds_many_hanging_parcels():
    async def hang(*a, **kw):
        await asyncio.sleep(30)

    loop = asyncio.get_running_loop()
    started = loop.time()
    with respx.mock as mock, patch("app.services.worklist_sources.fetch_crop_timeline", hang), \
         patch("app.api.assessments.WORKLIST_PARCEL_TIMEOUT_S", 10.0), \
         patch("app.api.assessments.WORKLIST_REQUEST_DEADLINE_S", 0.5), \
         patch("app.api.assessments.WORKLIST_MAX_CONCURRENCY", 1):
        _setup(mock, [_assessment(f"p{i}") for i in range(4)], [f"p{i}" for i in range(4)])
        resp = await asyncio.wait_for(_get("/api/crop-health/parcels"), timeout=5)
    assert resp.status_code == 200 and len(resp.json()["parcels"]) == 4
    assert loop.time() - started < 3
