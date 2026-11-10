"""GET /parcels/{id}/predictions: tenant-scoped JSON/CSV export from the log."""
import csv
import io
import json
from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services import prediction_log as plog
from app.services.prediction_log import MemoryPredictionLog, PredictionRecord

H = {"X-Tenant-ID": "tenant-a", "X-User-ID": "u1"}
URN = "urn:ngsi-ld:AgriParcel:p1"
URL = "/api/crop-health/parcels/p1/predictions"


def _rec(**kw):
    base = dict(tenant_id="tenant-a", parcel_id=URN, season_start=date(2026, 3, 1), crop="TRZAX", kind="yield",
                model="aquacrop", model_version="1.0", as_of=date(2026, 5, 1), payload={"p": [1]}, inputs={"i": "é"})
    base.update(kw)
    return PredictionRecord(**base)


@pytest.fixture
def log(monkeypatch):
    m = MemoryPredictionLog()
    monkeypatch.setattr(plog, "get_prediction_log", lambda: m)
    return m


@pytest.fixture
def client():
    return TestClient(app)


def test_requires_identity(client, log):
    assert client.get(URL).status_code == 401


def test_503_when_log_off(client, monkeypatch):
    monkeypatch.setattr(plog, "get_prediction_log", lambda: None)
    r = client.get(URL, headers=H)
    assert r.status_code == 503 and r.json() == {"detail": {"code": "prediction_log_unavailable"}}


@pytest.mark.anyio
async def test_json_tenant_scoped_and_ordered(client, log):
    await log.append(_rec(as_of=date(2026, 5, 3)))
    await log.append(_rec(as_of=date(2026, 5, 1)))
    await log.append(_rec(tenant_id="tenant-b"))
    r = client.get(URL, headers=H)
    body = r.json()
    assert r.status_code == 200 and body["parcel_id"] == URN and body["count"] == 2
    assert [i["as_of"] for i in body["items"]] == ["2026-05-01", "2026-05-03"]
    assert body["items"][0]["payload"] == {"p": [1]} and "tenant_id" not in body["items"][0]


@pytest.mark.anyio
async def test_filters(client, log):
    await log.append(_rec())
    await log.append(_rec(kind="phenology"))
    await log.append(_rec(model="other"))
    await log.append(_rec(season_start=date(2025, 3, 1)))
    assert client.get(URL, headers=H, params={"kind": "phenology"}).json()["count"] == 1
    assert client.get(URL, headers=H, params={"model": "other"}).json()["count"] == 1
    assert client.get(URL, headers=H, params={"season_start": "2025-03-01"}).json()["count"] == 1
    assert client.get(URL, headers=H, params={"kind": "bad"}).status_code == 422
    assert client.get(URL, headers=H, params={"format": "xml"}).status_code == 422
    assert client.get(URL, headers=H, params={"season_start": "nope"}).status_code == 422


@pytest.mark.anyio
async def test_csv_export(client, log):
    await log.append(_rec())
    r = client.get(URL, headers=H, params={"format": "csv"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    rows = list(csv.reader(io.StringIO(r.text)))
    assert rows[0] == ["id", "parcel_id", "season_start", "crop", "kind", "model", "model_version", "as_of",
                       "emitted_at", "payload", "inputs"]
    assert len(rows) == 2 and rows[1][1] == URN and rows[1][4] == "yield"
    assert json.loads(rows[1][9]) == {"p": [1]} and json.loads(rows[1][10]) == {"i": "é"}


def test_invalid_parcel_id(client, log):
    assert client.get("/api/crop-health/parcels/a%20b/predictions", headers=H).status_code == 422
