"""«Toca hacer» alerts: pure builder, lifecycle against a mocked Orion, internal route."""
import json
from datetime import date
from unittest.mock import patch

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import work_alerts
from app.services.work_alerts import build_work_alert, emit_work_alerts

T = "acmefarm"
TODAY = date(2026, 11, 4)
PURN = "urn:ngsi-ld:AgriParcel:p1"


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _row(kind, when, detail=None, name="Olive grove", planned=None):
    return {"parcelId": "p1", "parcelName": name, "plannedCrop": planned,
            "nextJob": {"kind": kind, "when": when, "detail": detail or {}}}


def _v(alert, key):
    return alert[key]["value"]


# ---- build_work_alert -------------------------------------------------------

def test_irrigate_today_is_high_vibrate_with_today_id():
    a = build_work_alert(T, _row("irrigate", "today"), TODAY)
    assert a["id"] == f"urn:ngsi-ld:Alert:{T}:work_irrigate:p1:today-20261104"
    assert a["type"] == "Alert"
    assert _v(a, "category") == "agronomic" and _v(a, "alertType") == "work_irrigate"
    assert _v(a, "severity") == "high" and _v(a, "urgency") == "vibrate"
    assert a["refEntity"] == {"type": "Relationship", "object": PURN}
    assert _v(a, "refEntityType") == "AgriParcel" and _v(a, "status") == "active"
    assert a["observedAt"]["value"]
    assert _v(a, "evaluationData") == {"kind": "irrigate", "when": "today", "detail": {}}
    assert _v(a, "action") == {"kind": "record_operation",
                               "params": {"parcelId": PURN, "kind": "irrigate"}}
    plain = _v(a, "plain")
    assert plain["es"] == {"title": "Toca regar Olive grove",
                           "body": "Según el balance de agua, hoy conviene regar."}
    assert set(plain) == {"es", "eu", "en"}
    assert all(plain[l]["title"] and plain[l]["body"] for l in plain)


def test_irrigate_scheduled_without_date_is_silent_medium_dated_today():
    a = build_work_alert(T, _row("irrigate", None, {"scheduled": True}), TODAY)
    assert a["id"].endswith(":work_irrigate:p1:20261104")
    assert _v(a, "severity") == "medium" and _v(a, "urgency") == "silent"


def test_sow_today_uses_crop_name_and_future_date_is_silent():
    planned = {"species": "TRZAX", "names": {"es": "Trigo", "en": "Wheat", "eu": "Garia"}}
    a = build_work_alert(T, _row("sow", "today", {"crop": "Trigo"}, planned=planned), TODAY)
    p = _v(a, "plain")
    assert p["es"]["title"] == "Toca sembrar Trigo en Olive grove"
    assert p["en"]["title"].endswith("Wheat in Olive grove") or "Wheat" in p["en"]["title"]
    assert _v(a, "urgency") == "vibrate" and _v(a, "severity") == "high"
    f = build_work_alert(T, _row("sow", "2026-11-10", planned=planned), TODAY)
    assert f["id"].endswith(":work_sow:p1:20261110")
    assert _v(f, "urgency") == "silent" and _v(f, "severity") == "medium"


def test_treat_with_and_without_disease():
    a = build_work_alert(T, _row("treat", "today", {"disease": "mildew"}), TODAY)
    assert _v(a, "plain")["es"] == {"title": "Toca tratar Olive grove: mildew",
                                    "body": "Riesgo alto; conviene tratar hoy."}
    assert _v(a, "urgency") == "vibrate"
    b = build_work_alert(T, _row("treat", "today", {"disease": None}), TODAY)
    assert _v(b, "plain")["es"]["title"] == "Toca tratar Olive grove"


def test_harvest_is_silent_and_opens_parcel():
    a = build_work_alert(T, _row("harvest", "2026-11-20", {"date": "2026-11-20"}), TODAY)
    assert a["id"].endswith(":work_harvest:p1:20261120")
    assert _v(a, "urgency") == "silent" and _v(a, "severity") == "medium"
    assert _v(a, "action") == {"kind": "open_parcel", "params": {"parcelId": PURN}}
    assert _v(a, "plain")["es"] == {"title": "Cosecha prevista en Olive grove",
                                    "body": "Prepara la cosecha hacia el 20/11/2026."}
    h = build_work_alert(T, _row("harvest", "today", {"date": "2026-11-01"}), TODAY)
    assert _v(h, "urgency") == "silent"  # harvest never vibrates


def test_sow_without_crop_name_and_disease_code_use_nameless_wording():
    a = build_work_alert(T, _row("sow", "today", {}), TODAY)
    assert _v(a, "plain")["es"]["title"] == "Toca sembrar en Olive grove"
    assert all("  " not in x["title"] for x in _v(a, "plain").values())
    b = build_work_alert(T, _row("treat", "today", {"disease": "xylella_fastidiosa"}), TODAY)
    assert _v(b, "plain")["es"]["title"] == "Toca tratar Olive grove"


def test_parcel_without_name_uses_short_id_never_the_full_one():
    pid = "0a1b2c3d-1111-2222-3333-444455556666"
    row = {"parcelId": pid, "parcelName": pid,
           "nextJob": {"kind": "irrigate", "when": "today", "detail": {}}}
    a = build_work_alert(T, row, TODAY)
    assert _v(a, "plain")["es"]["title"] == "Toca regar 0a1b2c3d"
    assert pid[8:] not in json.dumps(_v(a, "plain"))


@pytest.mark.parametrize("kind", ["pending_assessment", "none_until", "other"])
def test_other_kinds_and_missing_job_give_nothing(kind):
    assert build_work_alert(T, _row(kind, None), TODAY) is None
    assert build_work_alert(T, {"parcelId": "p1", "parcelName": "x", "nextJob": None}, TODAY) is None
    assert build_work_alert(T, {"parcelId": "p1", "parcelName": "x"}, TODAY) is None


def test_non_irrigate_without_date_gives_nothing():
    assert build_work_alert(T, _row("sow", None), TODAY) is None


# ---- emit_work_alerts -------------------------------------------------------

def _existing(kind="irrigate", suffix="today-20261104", status="active", parcel="p1"):
    return {"id": f"urn:ngsi-ld:Alert:{T}:work_{kind}:{parcel}:{suffix}",
            "type": "Alert", "alertType": f"work_{kind}", "status": status,
            "refEntity": f"urn:ngsi-ld:AgriParcel:{parcel}"}


async def _emit(rows, existing, today=TODAY):
    with respx.mock(assert_all_called=False) as mock, \
            patch.object(work_alerts, "build_parcel_rows", return_value=rows) as _b, \
            patch.object(work_alerts, "_today", return_value=today):
        mock.get(url__regex=r".*type=Alert.*").respond(json=existing)
        up = mock.post(url__regex=r".*entityOperations/upsert.*").respond(204)
        pt = mock.patch(url__regex=r".*/attrs.*").respond(204)
        out = await emit_work_alerts(T)
        return out, up, pt


@pytest.mark.anyio
async def test_new_task_is_upserted():
    out, up, pt = await _emit([_row("irrigate", "today")], [])
    assert out == {"emitted": 1, "resolved": 0, "unchanged": 0}
    body = json.loads(up.calls[0].request.content)
    assert body[0]["id"].endswith("work_irrigate:p1:today-20261104")
    assert not pt.called


@pytest.mark.anyio
async def test_same_task_is_unchanged_and_writes_nothing():
    out, up, pt = await _emit([_row("irrigate", "today")], [_existing()])
    assert out == {"emitted": 0, "resolved": 0, "unchanged": 1}
    assert not up.called and not pt.called


@pytest.mark.anyio
async def test_gone_task_is_resolved_by_patch():
    out, up, pt = await _emit([{"parcelId": "p1", "parcelName": "x", "nextJob": None}], [_existing()])
    assert out == {"emitted": 0, "resolved": 1, "unchanged": 0}
    req = pt.calls[0].request
    assert req.url.path.endswith(f"{_existing()['id']}/attrs")
    assert json.loads(req.content) == {"status": {"type": "Property", "value": "resolved"}}
    assert not up.called


@pytest.mark.anyio
async def test_resolved_alert_is_ignored_when_listing_active():
    out, up, pt = await _emit([], [_existing(status="resolved")])
    assert out == {"emitted": 0, "resolved": 0, "unchanged": 0}


@pytest.mark.anyio
async def test_task_reappearing_a_week_later_gets_a_new_id():
    old = _existing(kind="sow", suffix="20261104", status="resolved")
    later = date(2026, 11, 11)
    out, up, _ = await _emit([_row("sow", "2026-11-11", {"crop": "Trigo"})], [old], today=later)
    assert out["emitted"] == 1
    assert json.loads(up.calls[0].request.content)[0]["id"].endswith("work_sow:p1:20261111")


@pytest.mark.anyio
async def test_changed_date_resolves_old_and_emits_new():
    old = _existing(kind="sow", suffix="20261110")
    out, up, pt = await _emit([_row("sow", "2026-11-12", {"crop": "Trigo"})], [old])
    assert out == {"emitted": 1, "resolved": 1, "unchanged": 0}


@pytest.mark.anyio
async def test_parcel_without_job_and_no_alerts_does_nothing():
    out, up, pt = await _emit([{"parcelId": "p1", "parcelName": "x", "nextJob": None}], [])
    assert out == {"emitted": 0, "resolved": 0, "unchanged": 0}
    assert not up.called and not pt.called


@pytest.mark.anyio
async def test_other_alert_types_are_never_touched():
    risk = {"id": f"urn:ngsi-ld:Alert:{T}:frost:p1", "type": "Alert",
            "alertType": "frost", "status": "active"}
    out, up, pt = await _emit([], [risk])
    assert out["resolved"] == 0 and not pt.called


@pytest.mark.anyio
async def test_orion_unreadable_aborts_without_resolving():
    with respx.mock(assert_all_called=False) as mock, \
            patch.object(work_alerts, "build_parcel_rows", return_value=[]):
        mock.get(url__regex=r".*type=Alert.*").respond(500)
        pt = mock.patch(url__regex=r".*/attrs.*").respond(204)
        with pytest.raises(httpx.HTTPStatusError):
            await emit_work_alerts(T)
        assert not pt.called


# ---- internal route ---------------------------------------------------------

@pytest.mark.anyio
async def test_internal_route_without_secret_is_401():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        r = await c.post("/api/crop-health/internal/work-alerts/run", json={"tenant_id": T})
    assert r.status_code == 401


@pytest.mark.anyio
async def test_internal_route_with_secret_runs_emit():
    async def fake(tenant):
        assert tenant == T
        return {"emitted": 2, "resolved": 1, "unchanged": 0}

    with patch("app.api.setup.INTERNAL_SECRET", "s3"), \
            patch("app.api.setup.emit_work_alerts", fake):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.post("/api/crop-health/internal/work-alerts/run", json={"tenant_id": T},
                             headers={"X-Internal-Service-Secret": "s3"})
    assert r.status_code == 200 and r.json() == {"emitted": 2, "resolved": 1, "unchanged": 0}


@pytest.mark.anyio
async def test_resolved_alert_with_same_id_same_day_is_reupserted():
    out, up, pt = await _emit([_row("irrigate", "today")], [_existing(status="resolved")])
    assert out == {"emitted": 1, "resolved": 0, "unchanged": 0}
    assert json.loads(up.calls[0].request.content)[0]["status"]["value"] == "active"


@pytest.mark.anyio
async def test_alert_read_filters_active_server_side_and_ignores_foreign_tenant_ids():
    other = {**_existing(), "id": "urn:ngsi-ld:Alert:other:work_irrigate:p1:today-20261104"}
    with respx.mock(assert_all_called=False) as mock, \
            patch.object(work_alerts, "build_parcel_rows", return_value=[]), \
            patch.object(work_alerts, "_today", return_value=TODAY):
        get = mock.get(url__regex=r".*type=Alert.*").respond(json=[other])
        pt = mock.patch(url__regex=r".*/attrs.*").respond(204)
        out = await emit_work_alerts(T)
    assert "status" in str(get.calls[0].request.url) and "active" in str(get.calls[0].request.url)
    assert out["resolved"] == 0 and not pt.called


@pytest.mark.anyio
async def test_alert_read_cap_raises(monkeypatch):
    monkeypatch.setattr(work_alerts, "ORION_PAGE_SIZE", 1)
    monkeypatch.setattr(work_alerts, "ORION_MAX_PAGES", 2)
    with respx.mock(assert_all_called=False) as mock, \
            patch.object(work_alerts, "build_parcel_rows", return_value=[]):
        mock.get(url__regex=r".*type=Alert.*").respond(json=[_existing()])
        with pytest.raises(RuntimeError):
            await emit_work_alerts(T)


# ---- degraded rows are unknown, never "no task" -------------------------------

@pytest.mark.anyio
async def test_degraded_row_neither_emits_nor_resolves():
    row = {"parcelId": "p1", "parcelName": "x", "nextJob": None, "_degraded": True}
    out, up, pt = await _emit([row], [_existing()])
    assert out == {"emitted": 0, "resolved": 0, "unchanged": 0}
    assert not up.called and not pt.called


@pytest.mark.anyio
async def test_degraded_parcel_does_not_shield_other_parcels():
    rows = [{"parcelId": "p1", "parcelName": "x", "nextJob": None, "_degraded": True},
            {"parcelId": "p2", "parcelName": "y", "nextJob": None}]
    out, up, pt = await _emit(rows, [_existing(), _existing(parcel="p2")])
    assert out["resolved"] == 1 and "p2" in pt.calls[0].request.url.path


def _orion_for_rows(mock, alerts_status=200):
    mock.get(url__regex=r".*type=CropHealthAssessment.*").respond(json=[])
    mock.get(url__regex=r".*type=AgriParcel.*").respond(json=[
        {"id": "urn:ngsi-ld:AgriParcel:p1", "name": "x"}])
    mock.get(url__regex=r".*type=Alert.*").respond(alerts_status, json=[])


@pytest.mark.anyio
async def test_parcel_timeout_marks_row_degraded_in_strict_mode(monkeypatch):
    import asyncio
    from app.api import assessments
    from app.services import worklist_sources

    async def hang(*a, **kw):
        await asyncio.sleep(30)

    monkeypatch.setattr(assessments, "WORKLIST_PARCEL_TIMEOUT_S", 0.05)
    monkeypatch.setattr(worklist_sources, "gather_parcel_inputs", hang)
    with respx.mock(assert_all_called=False) as mock:
        _orion_for_rows(mock)
        rows = await assessments.build_parcel_rows(None, T, with_history=False, strict=True)
        plain = await assessments.build_parcel_rows(None, T, with_history=False)
    assert rows[0]["_degraded"] is True
    assert "_degraded" not in plain[0]  # the public route's rows are unchanged


@pytest.mark.anyio
async def test_alerts_read_failure_marks_every_row_degraded_in_strict_mode():
    from app.api import assessments
    from app.services import worklist_sources

    async def ok(*a, **kw):
        return {"timeline": None, "agro": None, "forecast": None, "history": []}

    with respx.mock(assert_all_called=False) as mock, \
            patch.object(worklist_sources, "gather_parcel_inputs", ok):
        _orion_for_rows(mock, alerts_status=500)
        strict_rows = await assessments.build_parcel_rows(None, T, with_history=False, strict=True)
    assert strict_rows[0]["_degraded"] is True
