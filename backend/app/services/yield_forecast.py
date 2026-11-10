"""Store rules for the in-season forecast record (spec §4.2, decision D6).

A failure, busy or a timeout never overwrites a stored forecast; season_ended
keeps the last one; any other reason is the current truth and replaces it.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from app.services import prediction_log as plog
from app.services.in_season_client import fetch_in_season
from app.services.redis_state import StoreError

logger = logging.getLogger(__name__)

RECORD_TTL_S = 400 * 86400  # covers the 366-day season_ended window
LOCK_TTL_S = 300
_URN_PREFIX = "urn:ngsi-ld:AgriParcel:"


def parcel_urn(parcel_id: str) -> str:
    return parcel_id if parcel_id.startswith(_URN_PREFIX) else f"{_URN_PREFIX}{parcel_id}"


def record_key(tenant: str, urn: str) -> str:
    return f"yield-forecast:{tenant}:{urn}"


def lock_key(tenant: str, urn: str) -> str:
    return f"yield-forecast-lock:{tenant}:{urn}"


def _first_reason(answer: dict) -> tuple[str, str | None]:
    items = answer.get("unavailable") or []
    if not items:
        return "unknown", None
    return items[0].get("reason") or "unknown", items[0].get("code")


def next_record(previous: dict | None, answer: dict, now: datetime) -> dict | None:
    at = now.isoformat()
    state = answer.get("state")
    if state == "done":
        return {"status": "done", "estimates": answer.get("estimates") or [], "season": answer.get("season"),
                "unavailable": answer.get("unavailable") or [], "computed_at": at, "attempted_at": at,
                "last_error": None}
    if state == "unavailable":
        reasons = {u.get("reason") for u in answer.get("unavailable") or []}
        if "busy" in reasons:
            return None
        if "season_ended" in reasons:
            if previous and previous.get("status") in ("done", "season_ended") and previous.get("estimates"):
                return {**previous, "status": "season_ended", "attempted_at": at}
            return {"status": "season_ended", "estimates": [], "season": None, "computed_at": at,
                    "attempted_at": at, "last_error": None}
        reason, code = _first_reason(answer)
        return {"status": "unavailable", "reason": reason, "code": code, "season": answer.get("season"),
                "estimates": [], "computed_at": at, "attempted_at": at, "last_error": None}
    if state == "failed":
        reason, code = _first_reason(answer)
        if previous:
            return {**previous, "last_error": {"reason": reason, "code": code, "at": at}}
        return {"status": "failed", "reason": reason, "code": code, "estimates": [], "season": None,
                "attempted_at": at, "last_error": None}
    return None



def _is_unknown_parcel(answer: dict) -> bool:
    return answer.get("state") == "failed" and any(
        u.get("code") == "404" for u in answer.get("unavailable") or [])


def _iso_date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def build_prediction_record(tenant: str, urn: str, answer: dict) -> plog.PredictionRecord | None:
    """Map a done in-season answer to a log row, or None when a key field is missing.

    Only fields the answer really carries are stored; nothing is invented.
    """
    estimates = answer.get("estimates") or []
    season = answer.get("season") or {}
    first = estimates[0] if estimates else {}
    model = first.get("provider_id") or answer.get("provider_id")
    model_version = season.get("provider_version") or first.get("provider_version")
    season_start = _iso_date((season.get("sowing") or {}).get("date"))
    as_of = _iso_date(season.get("as_of"))
    crop = season.get("crop")
    if not (model and model_version and season_start and as_of and crop):
        return None
    payload = {"estimates": estimates, "season_status": season.get("status"),
               "harvest_date": season.get("harvest_date"), "n_years": season.get("n_years")}
    inputs = {"contract_version": answer.get("contract_version"), "regime": season.get("regime"),
              "sowing": season.get("sowing"), "sowing_method": season.get("sowing_method"),
              "sowing_method_source": season.get("sowing_method_source"),
              "weather_source": season.get("weather_source"), "computed_at": season.get("computed_at")}
    return plog.PredictionRecord(tenant_id=tenant, parcel_id=urn, season_start=season_start, crop=str(crop),
                                 kind="yield", model=str(model), model_version=str(model_version),
                                 as_of=as_of, payload=payload, inputs=inputs)


async def _log_prediction(tenant: str, urn: str, answer: dict) -> None:
    """Append one row for an answer that carries an estimate. Never raises."""
    model = answer.get("provider_id")
    try:
        if answer.get("state") != "done" or not answer.get("estimates"):
            return
        record = build_prediction_record(tenant, urn, answer)
        if record is None:
            logger.warning("prediction_log skipped: season/crop/as_of missing tenant=%s parcel=%s model=%s",
                           tenant, urn, model)
            return
        log = plog.get_prediction_log()
        if log is None:
            return
        inserted = await log.append(record)
        logger.info("prediction_log append tenant=%s parcel=%s model=%s as_of=%s inserted=%s",
                    tenant, urn, record.model, record.as_of, inserted)
    except Exception:
        logger.exception("prediction_log append failed tenant=%s parcel=%s model=%s", tenant, urn, model)


async def compute_and_store(state, tenant: str, parcel_id: str, *, hold_lock: bool = True,
                            retry: bool = False) -> str:
    """Fetch one parcel's forecast and apply the store rules.

    hold_lock=True takes the parcel lock (the nightly worker, which skips a
    parcel someone is refreshing); False when the caller already holds it.
    """
    urn = parcel_urn(parcel_id)
    lk = lock_key(tenant, urn)
    if hold_lock:
        got = await state.try_lock(lk, LOCK_TTL_S)
        if got is False:
            return "skipped_locked"
    try:
        answer = await fetch_in_season(urn, tenant, retry=retry)
        try:
            previous = await state.get_json(record_key(tenant, urn))
        except StoreError:
            logger.error("yield_forecast previous unreadable tenant=%s parcel=%s: not written", tenant, urn)
            return "store_error"
        if previous is None and _is_unknown_parcel(answer):
            # A made-up or deleted parcel: no record, so ids cannot fill the shared store.
            logger.info("yield_forecast unknown parcel tenant=%s parcel=%s", tenant, urn)
            return "kept"
        await _log_prediction(tenant, urn, answer)
        record = next_record(previous, answer, datetime.now(timezone.utc))
        if record is None:
            return "kept"
        if not await state.set_json(record_key(tenant, urn), record, RECORD_TTL_S):
            logger.error("yield_forecast store failed tenant=%s parcel=%s", tenant, urn)
            return "store_error"
        logger.info("yield_forecast stored tenant=%s parcel=%s status=%s", tenant, urn, record["status"])
        return "written"
    finally:
        if hold_lock:
            await state.unlock(lk)
