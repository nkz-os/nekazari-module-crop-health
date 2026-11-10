"""Read and export the append-only prediction log for one parcel.

Mounted with the gateway identity dependency; the tenant always comes from
the verified identity (request.state.tenant_id).
"""

from __future__ import annotations

import csv
import io
import json
from datetime import date
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response

from app.api.yield_forecast import _checked_urn
from app.services import prediction_log as plog

router = APIRouter(tags=["predictions"])

CSV_COLUMNS = ["id", "parcel_id", "season_start", "crop", "kind", "model", "model_version", "as_of",
               "emitted_at", "payload", "inputs"]


def _item(r: plog.PredictionRecord) -> dict:
    return {"id": r.id, "parcel_id": r.parcel_id, "season_start": r.season_start.isoformat(), "crop": r.crop,
            "kind": r.kind, "model": r.model, "model_version": r.model_version, "as_of": r.as_of.isoformat(),
            "emitted_at": r.emitted_at.isoformat() if r.emitted_at else None,
            "payload": r.payload, "inputs": r.inputs}


@router.get("/parcels/{parcel_id}/predictions")
async def list_predictions(
    parcel_id: str,
    request: Request,
    kind: Literal["phenology", "yield"] | None = None,
    model: str | None = Query(default=None, max_length=128),
    season_start: date | None = None,
    format: Literal["json", "csv"] = "json",
):
    tenant = request.state.tenant_id
    urn = _checked_urn(parcel_id)
    log = plog.get_prediction_log()
    if log is None:
        raise HTTPException(status_code=503, detail={"code": "prediction_log_unavailable"})
    rows = await log.list(tenant, urn, kind=kind, model=model, season_start=season_start)
    items = [_item(r) for r in rows]
    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(CSV_COLUMNS)
        for it in items:
            writer.writerow([json.dumps(it[c], ensure_ascii=False, sort_keys=True) if c in ("payload", "inputs")
                             else ("" if it[c] is None else it[c]) for c in CSV_COLUMNS])
        return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="predictions.csv"'})
    return {"parcel_id": urn, "count": len(items), "items": items}
