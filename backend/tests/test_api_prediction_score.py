"""GET /parcels/{id}/predictions/score: logged yield rows vs the recorded harvest."""
import csv
import io
from datetime import date

import pytest
from fastapi.testclient import TestClient
from nkz_platform_sdk.crop_timeline import CropDataUnavailable

from app.main import app
from app.services import harvest_source
from app.services import prediction_log as plog
from app.services.prediction_log import MemoryPredictionLog, PredictionRecord

H = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u1"}
URN = "urn:ngsi-ld:AgriParcel:p1"
URL = "/api/crop-health/parcels/p1/predictions/score"

WL = {"basis": "water_limited", "unit": "t/ha", "range": None, "provider_id": "aquacrop",
      "percentiles": {"p10": 10.44, "p50": 11.83, "p90": 12.84},
      "moisture": {"pct": 13.0, "basis": "commercial"}, "validation": {"status": "not_applicable"}}
GC = {"basis": "gap_corrected", "unit": "t/ha", "range": {"low": 1.05, "high": 6.79}, "percentiles": None,
      "provider_id": "aquacrop", "moisture": {"pct": 13.0, "basis": "commercial"},
      "validation": {"status": "experimental"}}
HEADER = ("parcel_id,season_start,crop,as_of,emitted_at,model,model_version,lead_days,provider_id,basis,"
          "validation_status,unit,moisture_pct,p10,p50,p90,low,high,observed_t_ha,error_t_ha,error_pct,"
          "within_p10_p90,within_range,distance_to_range_t_ha")


def _rec(**kw):
    base = dict(tenant_id="tenant-a", parcel_id=URN, season_start=date(2026, 10, 20), crop="TRZAX", kind="yield",
                model="aquacrop", model_version="v1", as_of=date(2027, 5, 1),
                payload={"estimates": [WL, GC]}, inputs={})
    base.update(kw)
    return PredictionRecord(**base)


def cycles(weight):
    return [{"crop_id": "c", "species": "TRZAX", "lifecycle": "annual",
             "start": {"date": "2026-10-20", "provenance": "actual"},
             "end": {"date": "2027-07-05", "provenance": "actual"}, "harvested_weight_kg": weight}]


@pytest.fixture
def log(monkeypatch):
    m = MemoryPredictionLog()
    monkeypatch.setattr(plog, "get_prediction_log", lambda: m)
    return m


@pytest.fixture
def client():
    return TestClient(app)


@pytest.fixture
def source(monkeypatch):
    """Install a fake harvest source; returns a holder with .result and .calls."""
    class Src:
        result = ({"area": 8.0}, cycles(40000.0))
        calls: list = []

    async def fake(tenant_id, parcel_urn):
        Src.calls.append((tenant_id, parcel_urn))
        return Src.result

    Src.calls = []
    monkeypatch.setattr(harvest_source, "load_parcel_cycles", fake)
    return Src


def test_requires_identity(client, log):
    assert client.get(URL).status_code == 401


def test_503_when_log_off(client, monkeypatch):
    monkeypatch.setattr(plog, "get_prediction_log", lambda: None)
    r = client.get(URL, headers=H)
    assert r.status_code == 503 and r.json() == {"detail": {"code": "prediction_log_unavailable"}}


def test_no_predictions(client, log, monkeypatch):
    async def boom(*a, **k):
        raise AssertionError("broker must not be called without predictions")

    monkeypatch.setattr(harvest_source, "load_parcel_cycles", boom)
    r = client.get(URL, headers=H)
    b = r.json()
    assert r.status_code == 200 and b["count"] == 0 and b["observed"] is None
    assert b["reason"] == "no_predictions" and b["season_start"] is None and b["items"] == []


@pytest.mark.anyio
async def test_scores_against_harvest(client, log, source):
    await log.append(_rec())
    r = client.get(URL, headers=H)
    b = r.json()
    assert r.status_code == 200 and b["season_start"] == "2026-10-20"
    assert b["cycle_match"] == "exact" and b["reason"] is None
    assert b["observed"]["yield_t_ha"] == 5.0
    assert b["items"][0]["lead_days"] == 65
    assert b["items"][0]["estimates"][0]["error_t_ha"] == 6.83
    assert b["items"][0]["estimates"][1]["within_range"] is True


@pytest.mark.anyio
async def test_no_harvest_yet(client, log, source):
    source.result = ({"area": 8.0}, cycles(None))
    await log.append(_rec())
    b = client.get(URL, headers=H).json()
    assert b["observed"] is None and b["reason"] == "no_harvest_recorded" and b["count"] == 1
    est = b["items"][0]["estimates"][0]
    assert est["p50"] == 11.83 and est["error_t_ha"] is None


@pytest.mark.anyio
async def test_broker_down_still_lists_rows(client, log, source):
    source.result = None
    await log.append(_rec())
    r = client.get(URL, headers=H)
    b = r.json()
    assert r.status_code == 200 and b["reason"] == "harvest_source_unavailable" and b["count"] == 1
    assert b["observed"] is None


@pytest.mark.anyio
async def test_default_season_is_the_latest(client, log, source):
    await log.append(_rec(season_start=date(2025, 11, 1), as_of=date(2026, 5, 1)))
    await log.append(_rec())
    b = client.get(URL, headers=H).json()
    assert b["season_start"] == "2026-10-20" and b["count"] == 1
    b = client.get(URL, headers=H, params={"season_start": "2025-11-01"}).json()
    assert b["count"] == 1 and b["season_start"] == "2025-11-01"


@pytest.mark.anyio
async def test_other_tenant_rows_are_invisible(client, log, source):
    await log.append(_rec())
    await log.append(_rec(tenant_id="tenant-b"))
    b = client.get(URL, headers=H).json()
    assert b["count"] == 1
    assert source.calls == [("tenant-a", URN)]


@pytest.mark.anyio
async def test_csv(client, log, source):
    await log.append(_rec())
    r = client.get(URL, headers=H, params={"format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    assert r.headers["content-disposition"] == 'attachment; filename="prediction-score.csv"'
    assert r.text.splitlines()[0] == HEADER
    rows = list(csv.DictReader(io.StringIO(r.text)))
    assert len(rows) == 2
    wl = next(x for x in rows if x["basis"] == "water_limited")
    assert (wl["p50"], wl["error_t_ha"], wl["within_p10_p90"], wl["low"], wl["high"]) == \
        ("11.83", "6.83", "false", "", "")
    assert wl["observed_t_ha"] == "5.0" and wl["season_start"] == "2026-10-20"


def test_invalid_inputs(client, log, source):
    assert client.get(URL, headers=H, params={"format": "xml"}).status_code == 422
    assert client.get(URL, headers=H, params={"season_start": "nope"}).status_code == 422
    assert client.get("/api/crop-health/parcels/a%20b/predictions/score", headers=H).status_code == 422


@pytest.mark.anyio
async def test_load_parcel_cycles(monkeypatch):
    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def close(self):
            pass

    monkeypatch.setattr(harvest_source, "OrionClient", FakeClient)

    async def down(client, urn):
        raise CropDataUnavailable("down")

    monkeypatch.setattr(harvest_source, "load_crop_data", down)
    assert await harvest_source.load_parcel_cycles("tenant-a", URN) is None

    parcel = {"id": URN, "area": 8.0}

    async def ok(client, urn):
        return parcel, [], []

    monkeypatch.setattr(harvest_source, "load_crop_data", ok)
    assert await harvest_source.load_parcel_cycles("tenant-a", URN) == (parcel, [])
