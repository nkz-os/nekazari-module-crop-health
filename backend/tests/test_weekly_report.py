"""Weekly report contribution of crop-health: tasks, changes, figures."""
import asyncio
from datetime import date
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app
from app.services import weekly_report

T = "acme"
WEEK = date(2026, 11, 9)  # a Monday


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _row(pid="p1", name="Olive grove", jobs=None, **kw):
    row = {"parcelId": pid, "parcelName": name, "freshness": "fresh", "cropStatus": "active",
           "jobs": jobs or [], "surprise": None, "plannedCrop": None}
    row.update(kw)
    return row


async def _build(rows, figures=None):
    async def fake_rows(*a, **k):
        return rows

    async def fake_fig(tenant, week, parcel_id):
        return (figures or {}).get(parcel_id)

    with patch.object(weekly_report, "build_parcel_rows", fake_rows), \
            patch.object(weekly_report, "_parcel_figures", fake_fig):
        return await weekly_report.build(T, WEEK)


@pytest.mark.anyio
async def test_three_languages():
    rows = [_row(jobs=[
        {"kind": "treat", "when": "today", "detail": {"disease": "roya", "alertId": "urn:ngsi-ld:Alert:x"}},
        {"kind": "irrigate", "when": None, "detail": {"scheduled": True}},
        {"kind": "harvest", "when": "2026-11-14", "detail": {"date": "2026-11-14"}},
    ]), _row(pid="p2", name="Vega", freshness="stale", jobs=[])]
    out = await _build(rows)
    assert out["version"] == 1 and out["complete"] is True
    assert [t["kind"] for t in out["tasks"]] == ["treat", "irrigate", "harvest"]
    assert out["tasks"][0]["relatedAlertId"] == "urn:ngsi-ld:Alert:x"
    assert out["tasks"][1]["when"] == {"type": "this_week", "date": None}
    assert out["tasks"][0]["subject"] == {"type": "parcel", "id": "urn:ngsi-ld:AgriParcel:p1", "name": "Olive grove"}
    items = out["tasks"] + out["changes"]
    assert items and out["changes"]
    for item in items:
        assert set(item["text"]) == {"es", "eu", "en"}
        for lang in item["text"].values():
            for s in lang.values():
                assert s and "urn:" not in s and "_" not in s


@pytest.mark.anyio
async def test_stale_drops_irrigate_treat():
    rows = [_row(freshness="stale", jobs=[
        {"kind": "treat", "when": "today", "detail": {"disease": "roya"}},
        {"kind": "irrigate", "when": "today", "detail": {}},
        {"kind": "sow", "when": "2026-11-10", "detail": {"crop": "Trigo"}},
        {"kind": "harvest", "when": "2026-11-12", "detail": {"date": "2026-11-12"}},
    ])]
    out = await _build(rows)
    assert [t["kind"] for t in out["tasks"]] == ["sow", "harvest"]
    assert len(out["changes"]) == 1 and out["changes"][0]["subject"]["id"].endswith(":p1")


@pytest.mark.anyio
async def test_degraded_sets_complete_false():
    rows = [_row(pid="bad", _degraded=True, jobs=[]),
            _row(pid="ok", jobs=[{"kind": "irrigate", "when": "today", "detail": {}}])]
    out = await _build(rows)
    assert out["complete"] is False
    assert [t["subject"]["id"] for t in out["tasks"]] == ["urn:ngsi-ld:AgriParcel:ok"]


@pytest.mark.anyio
async def test_horizon_and_order():
    rows = [_row(jobs=[
        {"kind": "harvest", "when": "2027-07-01", "detail": {"date": "2027-07-01"}},
        {"kind": "sow", "when": None, "detail": {"crop": "Trigo"}},
        {"kind": "harvest", "when": "2026-11-20", "detail": {"date": "2026-11-20"}},
        {"kind": "irrigate", "when": "today", "detail": {}},
    ])]
    out = await _build(rows)
    assert [(t["kind"], t["when"]["type"]) for t in out["tasks"]] == \
        [("irrigate", "today"), ("harvest", "date"), ("sow", "undated")]


@pytest.mark.anyio
async def test_orion_down_returns_502():
    async def boom(*a, **k):
        assert k.get("strict") is True
        raise RuntimeError("orion down")

    with patch.object(weekly_report, "build_parcel_rows", boom), \
            patch("app.api.setup.INTERNAL_SECRET", "s3"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/crop-health/internal/weekly-report",
                            params={"tenant_id": T, "week_start": "2026-11-09"},
                            headers={"X-Internal-Service-Secret": "s3"})
    assert r.status_code == 502


@pytest.mark.anyio
@pytest.mark.parametrize("params,secret,code", [
    ({"tenant_id": T, "week_start": "2026-11-09"}, None, 401),
    ({"tenant_id": T, "week_start": "2026-11-09"}, "bad", 401),
    ({"week_start": "2026-11-09"}, "s3", 400),
    ({"tenant_id": "A cme!", "week_start": "2026-11-09"}, "s3", 400),
    ({"tenant_id": T, "week_start": "2026-11-10"}, "s3", 400),
    ({"tenant_id": T, "week_start": "nope"}, "s3", 400),
    ({"tenant_id": T}, "s3", 400),
])
async def test_route_rejects(params, secret, code):
    headers = {"X-Internal-Service-Secret": secret} if secret else {}
    with patch("app.api.setup.INTERNAL_SECRET", "s3"):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/crop-health/internal/weekly-report", params=params, headers=headers)
    assert r.status_code == code


@pytest.mark.anyio
async def test_route_ok():
    async def fake(tenant, week):
        assert (tenant, week) == (T, WEEK)
        return {"version": 1, "complete": True, "tasks": [], "changes": [], "figures": []}

    with patch("app.api.setup.INTERNAL_SECRET", "s3"), patch.object(weekly_report, "build", fake):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
            r = await c.get("/api/crop-health/internal/weekly-report",
                            params={"tenant_id": T, "week_start": "2026-11-09"},
                            headers={"X-Internal-Service-Secret": "s3"})
    assert r.status_code == 200 and r.json()["version"] == 1


# ---- figures ---------------------------------------------------------------

def _days(n=7, start=date(2026, 11, 2), **over):
    out = []
    for i in range(n):
        d = date.fromordinal(start.toordinal() + i)
        rec = {"date": d.isoformat(), "precip_mm": 1.0, "et0_mm": 2.0, "tmin_c": 4.0, "tmax_c": 20.0,
               "source": "model_analysis",
               "sources": {"precip_mm": "model_analysis", "et0_mm": "model_analysis",
                           "tmin_c": "model_analysis", "tmax_c": "model_analysis",
                           "hours_below_zero": None}}
        rec.update(over)
        out.append(rec)
    return out


KW = dict(base_temp=10.0, upper_cutoff=30.0, week_start=WEEK)


def _m(days, today=date(2026, 11, 9)):
    return {m["key"]: m for m in weekly_report._figures_from_days(days, **KW, today=today)}


def test_figures_closed_only():
    # forecast kind excluded even inside the window: 6 closed days left, metric omitted
    days = _days()
    days[6]["kind"] = "forecast"
    assert _m(days) == {}
    # kind closed on all days: included
    days = _days()
    for d in days:
        d["kind"] = "closed"
    m = _m(days)
    assert m["rain_mm"]["value"] == 7.0 and m["et0_mm"]["value"] == 14.0 and m["gdd"]["value"] == 14.0
    # no kind, last day not before local today: excluded
    assert _m(_days(), today=date(2026, 11, 8)) == {}
    # no kind, all dates past: included
    assert _m(_days())["rain_mm"]["value"] == 7.0


def test_figures_origin():
    m = _m([{k: v for k, v in d.items() if k != "sources"} for d in _days()])
    assert {x["origin"] for x in m.values()} == {"estimated"}
    days = _days()
    for d in days:
        d["sources"].update(precip_mm="iot_sensor", et0_mm="iot_sensor",
                            tmin_c="iot_sensor", tmax_c="iot_sensor")
    assert {x["origin"] for x in _m(days).values()} == {"sensor"}
    # only rain measured: the parcel mixes origins, so every metric says estimated
    days = _days()
    for d in days:
        d["sources"]["precip_mm"] = "iot_sensor"
    assert {x["origin"] for x in _m(days).values()} == {"estimated"}
    # one day not from a sensor is not "sensor"
    days = _days()
    for d in days[:6]:
        d["sources"]["precip_mm"] = "iot_sensor"
    assert _m(days)["rain_mm"]["origin"] == "estimated"


def test_figures_coverage():
    assert _m(_days(6)) == {}
    days = _days()
    days[3]["et0_mm"] = None
    m = _m(days)
    assert "et0_mm" not in m and m["rain_mm"]["value"] == 7.0


@pytest.mark.anyio
async def test_parcel_figures_signed_call_and_failure_is_none():
    import httpx
    import respx

    from app.services import context_client

    async def no_ctx(**k):
        return None

    async def table(species):
        return context_client._DEFAULT_STAGE_TABLE

    with respx.mock(assert_all_called=False) as mock, \
            patch.object(weekly_report, "_hmac_secret", lambda: "k"), \
            patch.object(weekly_report, "_utc_today", lambda: WEEK), \
            patch.object(context_client, "get_crop_context", no_ctx), \
            patch.object(context_client, "get_phenology_stages", table):
        route = mock.get(url__regex=r".*/api/weather/parcel/p1/daily.*").respond(
            200, json={"days": _days()})
        out = await weekly_report._parcel_figures(T, WEEK, "p1")
        req = route.calls[0].request
        assert req.headers["X-Auth-Signature"] and req.headers["X-Tenant-ID"] == T
        assert req.url.params["start"] == "2026-11-02" and req.url.params["end"] == "2026-11-08"
        assert {m["key"] for m in out} == {"rain_mm", "et0_mm", "gdd"}
        route.respond(500)
        assert await weekly_report._parcel_figures(T, WEEK, "p1") is None
        route.mock(side_effect=httpx.ConnectError("down"))
        assert await weekly_report._parcel_figures(T, WEEK, "p1") is None
