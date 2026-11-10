"""Prediction log: memory semantics, Postgres SQL shape, settings, accessor."""
import json
import logging
from datetime import date

import pytest

from app.config import Settings
from app.services import prediction_log as plog
from app.services.prediction_log import MemoryPredictionLog, PostgresPredictionLog, PredictionRecord


@pytest.fixture
def anyio_backend():
    return "asyncio"


def rec(**kw):
    base = dict(tenant_id="tenant-a", parcel_id="urn:ngsi-ld:AgriParcel:p1", season_start=date(2026, 3, 1),
                crop="TRZAX", kind="yield", model="aquacrop", model_version="1.0",
                as_of=date(2026, 5, 1), payload={"x": 1}, inputs={"y": 2})
    base.update(kw)
    return PredictionRecord(**base)


@pytest.mark.anyio
async def test_memory_append_is_idempotent_first_wins():
    log = MemoryPredictionLog()
    assert await log.append(rec()) is True
    assert await log.append(rec(payload={"x": 99})) is False
    rows = await log.list("tenant-a", "urn:ngsi-ld:AgriParcel:p1")
    assert len(rows) == 1 and rows[0].payload == {"x": 1} and rows[0].emitted_at is not None


@pytest.mark.anyio
async def test_memory_new_as_of_or_version_adds_row():
    log = MemoryPredictionLog()
    await log.append(rec())
    assert await log.append(rec(as_of=date(2026, 5, 2))) is True
    assert await log.append(rec(model_version="1.1")) is True
    assert len(await log.list("tenant-a", "urn:ngsi-ld:AgriParcel:p1")) == 3


@pytest.mark.anyio
async def test_memory_list_is_tenant_scoped_filtered_and_ordered():
    log = MemoryPredictionLog()
    await log.append(rec(as_of=date(2026, 5, 3)))
    await log.append(rec(as_of=date(2026, 5, 1)))
    await log.append(rec(kind="phenology", as_of=date(2026, 5, 2)))
    await log.append(rec(model="other", as_of=date(2026, 5, 4)))
    await log.append(rec(season_start=date(2025, 3, 1)))
    await log.append(rec(tenant_id="tenant-b"))
    pid = "urn:ngsi-ld:AgriParcel:p1"
    rows = await log.list("tenant-a", pid, kind="yield", model="aquacrop", season_start=date(2026, 3, 1))
    assert [r.as_of for r in rows] == [date(2026, 5, 1), date(2026, 5, 3)]
    assert await log.list("tenant-c", pid) == []
    assert len(await log.list("tenant-a", pid)) == 5


def test_record_is_immutable():
    with pytest.raises(Exception):
        rec().crop = "x"


# ── Postgres: SQL shape with a fake pool ─────────────────────────────────────
class FakePool:
    def __init__(self, fetchval_result=1, rows=()):
        self.calls, self.fetchval_result, self.rows, self.closed = [], fetchval_result, rows, False

    async def fetchval(self, sql, *args):
        self.calls.append(("fetchval", sql, args))
        return self.fetchval_result

    async def fetch(self, sql, *args):
        self.calls.append(("fetch", sql, args))
        return self.rows

    async def close(self):
        self.closed = True


@pytest.mark.anyio
async def test_postgres_append_parameterised_on_conflict_do_nothing():
    pool = FakePool(fetchval_result=7)
    log = PostgresPredictionLog("postgresql://u:secret@h/db", pool=pool)
    assert await log.append(rec(tenant_id="evil'; DROP TABLE x;--")) is True
    _, sql, args = pool.calls[0]
    assert "ON CONFLICT" in sql and "DO NOTHING" in sql and "RETURNING id" in sql
    assert "evil" not in sql and "evil'; DROP TABLE x;--" in args
    assert json.loads(args[sql_index(sql, "payload")]) == {"x": 1}
    pool.fetchval_result = None
    assert await log.append(rec()) is False


def sql_index(sql, col):
    cols = sql.split("(", 1)[1].split(")", 1)[0].replace("\n", " ").split(",")
    return [c.strip() for c in cols].index(col)


@pytest.mark.anyio
async def test_postgres_list_filters_tenant_and_decodes_json():
    row = {"id": 1, "tenant_id": "tenant-a", "parcel_id": "p", "season_start": date(2026, 3, 1), "crop": "TRZAX",
           "kind": "yield", "model": "m", "model_version": "v", "as_of": date(2026, 5, 1), "emitted_at": None,
           "payload": '{"a": 1}', "inputs": '{"b": 2}'}
    pool = FakePool(rows=[row])
    log = PostgresPredictionLog("postgresql://u:secret@h/db", pool=pool)
    out = await log.list("tenant-a", "p", kind="yield", model="m", season_start=date(2026, 3, 1))
    _, sql, args = pool.calls[0]
    assert "tenant_id = $1" in sql and "ORDER BY as_of, emitted_at" in sql
    assert args[:2] == ("tenant-a", "p") and len(args) == 5
    assert out[0].payload == {"a": 1} and out[0].inputs == {"b": 2}
    await log.list("tenant-a", "p")
    assert len(pool.calls[1][2]) == 2


@pytest.mark.anyio
async def test_postgres_close_closes_pool():
    pool = FakePool()
    log = PostgresPredictionLog("postgresql://u:secret@h/db", pool=pool)
    await log.close()
    assert pool.closed


# ── Settings and accessor ────────────────────────────────────────────────────
def test_settings_database_url_aliases(monkeypatch):
    for k in ("DATABASE_URL", "POSTGRES_URL"):
        monkeypatch.delenv(k, raising=False)
    assert not Settings(_env_file=None).database_url
    monkeypatch.setenv("POSTGRES_URL", "postgresql://a/b")
    assert Settings(_env_file=None).database_url == "postgresql://a/b"
    monkeypatch.setenv("DATABASE_URL", "postgresql://c/d")
    assert Settings(_env_file=None).database_url in ("postgresql://c/d", "postgresql://a/b")


@pytest.fixture(autouse=False)
def fresh(monkeypatch):
    monkeypatch.setattr(plog, "_instance", None)
    monkeypatch.setattr(plog, "_instance_dsn", None)


def test_accessor_none_and_critical_when_unset(monkeypatch, caplog, fresh):
    monkeypatch.setattr(plog.get_settings(), "database_url", None)
    with caplog.at_level(logging.CRITICAL):
        assert plog.get_prediction_log() is None
        assert plog.get_prediction_log() is None
    crit = [r for r in caplog.records if r.levelno == logging.CRITICAL]
    assert len(crit) == 2  # once per attempted use


def test_accessor_builds_postgres_and_never_logs_dsn(monkeypatch, caplog, fresh):
    monkeypatch.setattr(plog.get_settings(), "database_url", "postgresql://u:topsecret@h/db")
    with caplog.at_level(logging.DEBUG):
        a = plog.get_prediction_log()
        assert isinstance(a, PostgresPredictionLog) and plog.get_prediction_log() is a
    assert "topsecret" not in caplog.text and "topsecret" not in repr(a)


@pytest.mark.anyio
async def test_close_prediction_log(monkeypatch, fresh):
    pool = FakePool()
    monkeypatch.setattr(plog, "_instance", PostgresPredictionLog("postgresql://u:s@h/db", pool=pool))
    await plog.close_prediction_log()
    assert pool.closed and plog._instance is None
