"""Store rules for the in-season forecast record (spec §4.2, decision D6).

A failure, busy or a timeout never overwrites a stored forecast; season_ended
keeps the last one; any other reason is the current truth and replaces it.
"""

from __future__ import annotations

from datetime import datetime

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
