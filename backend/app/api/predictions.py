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
from app.services import harvest_source
from app.services import prediction_log as plog
from app.services import prediction_score as pscore

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


SCORE_CSV_COLUMNS = ["parcel_id", "season_start", "crop", "as_of", "emitted_at", "model", "model_version",
                     "lead_days", "provider_id", "basis", "validation_status", "unit", "moisture_pct", "p10",
                     "p50", "p90", "low", "high", "observed_t_ha", "error_t_ha", "error_pct", "within_p10_p90",
                     "within_range", "distance_to_range_t_ha"]


def _cell(v):
    if v is None:
        return ""
    if isinstance(v, bool):
        return "true" if v else "false"
    return v


@router.get("/parcels/{parcel_id}/predictions/score")
async def score_predictions(
    parcel_id: str,
    request: Request,
    season_start: date | None = None,
    format: Literal["json", "csv"] = "json",
):
    tenant = request.state.tenant_id
    urn = _checked_urn(parcel_id)
    log = plog.get_prediction_log()
    if log is None:
        raise HTTPException(status_code=503, detail={"code": "prediction_log_unavailable"})
    rows = await log.list(tenant, urn, kind="yield")
    season = season_start or (max(r.season_start for r in rows) if rows else None)
    rows = [r for r in rows if r.season_start == season]
    observed = cycle = match = None
    crop = None
    if not rows:
        reason = "no_predictions"
    else:
        crop = rows[-1].crop
        source = await harvest_source.load_parcel_cycles(tenant, urn)
        if source is None:
            reason = "harvest_source_unavailable"
        else:
            parcel, cycles = source
            cycle, match = pscore.pick_cycle(cycles, season, max(r.as_of for r in rows))
            observed, reason = pscore.observed_harvest(cycle, parcel)
    items = pscore.score_rows(rows, observed)
    if format == "csv":
        buf = io.StringIO()
        writer = csv.writer(buf, lineterminator="\n")
        writer.writerow(SCORE_CSV_COLUMNS)
        obs_yield = observed["yield_t_ha"] if observed else None
        for it in items:
            for est in it["estimates"]:
                values = {"parcel_id": urn, "season_start": season.isoformat(), "crop": crop, **it, **est,
                          "observed_t_ha": obs_yield}
                writer.writerow([_cell(values[c]) for c in SCORE_CSV_COLUMNS])
        return Response(content=buf.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": 'attachment; filename="prediction-score.csv"'})
    return {"parcel_id": urn, "season_start": season.isoformat() if season else None, "crop": crop,
            "count": len(items), "cycle_match": match, "observed": observed, "reason": reason, "items": items}
