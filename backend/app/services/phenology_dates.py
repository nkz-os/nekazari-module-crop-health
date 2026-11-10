"""Milestone dates of the cereal calendar: fetch, keep the latest, log the answer.

Scheduled path only. The latest ``done`` answer per parcel is kept in the
shared store (a failure or an unavailable answer never overwrites it); each
``done`` answer also appends one ``kind='phenology'`` row to the prediction
log. Nothing here raises: every failure is logged with tenant and parcel.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.schemas import StageTable
from app.services import parcel_site
from app.services import prediction_log as plog
from app.services.phenology_dates_client import PROVIDER_ID, fetch_phenology_dates
from app.services.yield_forecast import _iso_date, parcel_urn

logger = logging.getLogger(__name__)

RECORD_TTL_S = 30 * 86400  # refreshed by every scheduled run; a stale season must not outlive it long


def record_key(tenant: str, urn: str) -> str:
    return f"phenology-dates:{tenant}:{urn}"


def is_calendar_table(table) -> bool:
    return isinstance(table, StageTable) and bool(table.model) and table.model.get("id") == PROVIDER_ID


def build_prediction_record(tenant: str, urn: str, answer: dict) -> plog.PredictionRecord | None:
    """Map a done answer to a log row, or None when a key field is missing. Nothing is invented."""
    season = answer.get("season") or {}
    block = answer.get("phenology") or {}
    model = block.get("model") or {}
    calibration = block.get("calibration") or {}
    validation = block.get("validation") or {}
    model_id = model.get("id") or answer.get("provider_id")
    model_version = model.get("version")
    if model_version and calibration.get("version"):
        model_version = f"{model_version}+{calibration['version']}"
    season_start = _iso_date((season.get("sowing") or {}).get("date"))
    as_of = _iso_date(season.get("as_of"))
    crop = season.get("crop")
    if not (model_id and model_version and season_start and as_of and crop and block.get("milestones")):
        return None
    payload = {"milestones": block.get("milestones"), "basis": block.get("basis"), "notes": block.get("notes")}
    inputs = {"gdd_method": block.get("gdd_method"), "base_temp": block.get("base_temp"),
              "upper_cutoff": block.get("upper_cutoff"), "calibration": calibration or None,
              "sowing": season.get("sowing"), "regime": season.get("regime"),
              "weather_source": season.get("weather_source"), "validation_version": validation.get("version"),
              "contract_version": answer.get("contract_version")}
    return plog.PredictionRecord(tenant_id=tenant, parcel_id=urn, season_start=season_start, crop=str(crop),
                                 kind="phenology", model=str(model_id), model_version=str(model_version),
                                 as_of=as_of, payload=payload, inputs=inputs)


async def _log_prediction(tenant: str, urn: str, answer: dict) -> None:
    """Append one row for a done answer. Never raises."""
    try:
        if answer.get("state") != "done":
            return
        record = build_prediction_record(tenant, urn, answer)
        if record is None:
            logger.warning("prediction_log skipped: phenology season/crop/as_of missing tenant=%s parcel=%s",
                           tenant, urn)
            return
        log = plog.get_prediction_log()
        if log is None:
            return
        inserted = await log.append(record)
        logger.info("prediction_log append tenant=%s parcel=%s model=%s as_of=%s kind=phenology inserted=%s",
                    tenant, urn, record.model, record.as_of, inserted)
    except Exception:
        logger.exception("prediction_log append failed tenant=%s parcel=%s kind=phenology", tenant, urn)


async def refresh(state, tenant: str, parcel_id: str, species: str) -> str:
    """Scheduled step for one parcel; returns the outcome word. Never raises."""
    urn = parcel_urn(parcel_id)
    try:
        table = await parcel_site.get_parcel_stage_table(species, urn, tenant)
        if not is_calendar_table(table):
            return "not_calendar"
        answer = await fetch_phenology_dates(urn, tenant)
        if answer.get("state") != "done":
            reasons = [u.get("reason") for u in answer.get("unavailable") or []]
            logger.warning("phenology_dates not done tenant=%s parcel=%s state=%s reasons=%s",
                           tenant, urn, answer.get("state"), reasons)
            return "failed" if answer.get("state") == "failed" else "kept"
        await _log_prediction(tenant, urn, answer)
        record = {"status": "done", "contract_version": answer.get("contract_version"),
                  "season": answer.get("season"), "phenology": answer.get("phenology"),
                  "computed_at": datetime.now(timezone.utc).isoformat()}
        if state is None or not getattr(state, "available", False):
            logger.warning("phenology_dates store unavailable tenant=%s parcel=%s", tenant, urn)
            return "store_error"
        if not await state.set_json(record_key(tenant, urn), record, RECORD_TTL_S):
            logger.error("phenology_dates store failed tenant=%s parcel=%s", tenant, urn)
            return "store_error"
        return "written"
    except Exception:
        logger.exception("phenology_dates refresh failed tenant=%s parcel=%s", tenant, urn)
        return "error"
