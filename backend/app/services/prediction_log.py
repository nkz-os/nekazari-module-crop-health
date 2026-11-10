"""Append-only log of every prediction the module emits.

Postgres-backed (asyncpg) with an in-memory twin for tests. A write failure
must never interrupt the caller: producers catch and log it. When no database
URL is configured the log is off: get_prediction_log() returns None and logs
CRITICAL on every attempted use (a peripheral store fails closed and loud).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Any, Protocol

from app.config import get_settings

logger = logging.getLogger(__name__)

KINDS = ("phenology", "yield")


@dataclass(frozen=True)
class PredictionRecord:
    tenant_id: str
    parcel_id: str
    season_start: date
    crop: str
    kind: str
    model: str
    model_version: str
    as_of: date
    payload: dict
    inputs: dict
    id: int | None = None
    emitted_at: datetime | None = None

    @property
    def key(self) -> tuple:
        return (self.tenant_id, self.parcel_id, self.season_start, self.kind, self.model,
                self.model_version, self.as_of)


class PredictionLog(Protocol):
    async def append(self, record: PredictionRecord) -> bool:
        """True if a row was inserted, False if the unique key already existed."""

    async def list(self, tenant_id: str, parcel_id: str, *, kind: str | None = None,
                   model: str | None = None, season_start: date | None = None) -> list[PredictionRecord]:
        ...


class MemoryPredictionLog:
    """Same idempotency and ordering as the Postgres log; for tests."""

    def __init__(self) -> None:
        self._rows: dict[tuple, PredictionRecord] = {}

    async def append(self, record: PredictionRecord) -> bool:
        if record.key in self._rows:
            return False
        self._rows[record.key] = replace(record, id=len(self._rows) + 1, emitted_at=datetime.now(timezone.utc))
        return True

    async def list(self, tenant_id, parcel_id, *, kind=None, model=None, season_start=None):
        rows = [r for r in self._rows.values()
                if r.tenant_id == tenant_id and r.parcel_id == parcel_id
                and (kind is None or r.kind == kind)
                and (model is None or r.model == model)
                and (season_start is None or r.season_start == season_start)]
        return sorted(rows, key=lambda r: (r.as_of, r.emitted_at))

    async def close(self) -> None:
        return None


_INSERT = """
INSERT INTO crop_health.prediction_log
  (tenant_id, parcel_id, season_start, crop, kind, model, model_version, as_of, payload, inputs)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb, $10::jsonb)
ON CONFLICT (tenant_id, parcel_id, season_start, kind, model, model_version, as_of) DO NOTHING
RETURNING id
"""

_COLUMNS = "id, tenant_id, parcel_id, season_start, crop, kind, model, model_version, as_of, emitted_at, payload, inputs"


def _decode(value: Any) -> dict:
    return json.loads(value) if isinstance(value, (str, bytes)) else value


class PostgresPredictionLog:
    """asyncpg-backed log. The pool is created lazily on first use."""

    def __init__(self, dsn: str, *, pool: Any = None) -> None:
        self._dsn = dsn
        self._pool = pool

    def __repr__(self) -> str:  # never expose the DSN
        return "PostgresPredictionLog()"

    async def _get_pool(self):
        if self._pool is None:
            import asyncpg

            self._pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=3)
        return self._pool

    async def append(self, record: PredictionRecord) -> bool:
        pool = await self._get_pool()
        new_id = await pool.fetchval(
            _INSERT, record.tenant_id, record.parcel_id, record.season_start, record.crop, record.kind,
            record.model, record.model_version, record.as_of,
            json.dumps(record.payload, default=str), json.dumps(record.inputs, default=str))
        return new_id is not None

    async def list(self, tenant_id, parcel_id, *, kind=None, model=None, season_start=None):
        pool = await self._get_pool()
        where, args = ["tenant_id = $1", "parcel_id = $2"], [tenant_id, parcel_id]
        for column, value in (("kind", kind), ("model", model), ("season_start", season_start)):
            if value is not None:
                args.append(value)
                where.append(f"{column} = ${len(args)}")
        sql = (f"SELECT {_COLUMNS} FROM crop_health.prediction_log WHERE {' AND '.join(where)} "
               "ORDER BY as_of, emitted_at")
        rows = await pool.fetch(sql, *args)
        return [PredictionRecord(
            id=r["id"], tenant_id=r["tenant_id"], parcel_id=r["parcel_id"], season_start=r["season_start"],
            crop=r["crop"], kind=r["kind"], model=r["model"], model_version=r["model_version"],
            as_of=r["as_of"], emitted_at=r["emitted_at"], payload=_decode(r["payload"]),
            inputs=_decode(r["inputs"])) for r in rows]

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None


_instance: PostgresPredictionLog | None = None
_instance_dsn: str | None = None


def get_prediction_log() -> PostgresPredictionLog | None:
    """The process-wide log, or None (with a CRITICAL log) when no database URL is set."""
    global _instance, _instance_dsn
    dsn = get_settings().database_url
    if not dsn:
        logger.critical("prediction_log disabled: DATABASE_URL/POSTGRES_URL not set; predictions are NOT recorded",
                        extra={"component": "prediction_log"})
        return None
    if _instance is None or _instance_dsn != dsn:
        _instance, _instance_dsn = PostgresPredictionLog(dsn), dsn
    return _instance


async def close_prediction_log() -> None:
    global _instance, _instance_dsn
    inst, _instance, _instance_dsn = _instance, None, None
    if inst is not None:
        await inst.close()
