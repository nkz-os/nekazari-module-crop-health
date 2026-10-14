"""Store rules for the in-season forecast record (spec §4.2, decision D6).

A failure, busy or a timeout never overwrites a stored forecast; season_ended
keeps the last one; any other reason is the current truth and replaces it.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from app.services.in_season_client import fetch_in_season

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


async def compute_and_store(state, tenant: str, parcel_id: str, *, hold_lock: bool = True) -> str:
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
        answer = await fetch_in_season(urn, tenant)
        previous = await state.get_json(record_key(tenant, urn))
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
