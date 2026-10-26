"""Pure rules for the per-parcel work list. No I/O."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional

from app.schemas import RecommendedAction

ACTIVE_PROVENANCES = ("actual", "declared")
ALERT_SEVERITIES = frozenset({"HIGH", "CRITICAL"})
FRESH_HOURS = 48
AGING_HOURS = 7 * 24
VIGOR_SURPRISE = frozenset({"below_expected", "anomalous_senescence"})
PHENOLOGY_SURPRISE = frozenset({"ahead", "behind", "early", "late"})
CWSI_RISE_THRESHOLD = 0.2
BALANCE_DROP_MM = 10.0
BASELINE_POINTS = 3
SEVERITY_ORDER = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
UNKNOWN_SEVERITY_RANK = len(SEVERITY_ORDER)
DEFAULT_LANG = "es"


def _cycle_date(cycle: Optional[dict]) -> Optional[str]:
    start = (cycle or {}).get("start") or {}
    return start.get("date") or None


_CLOSED_STATUSES = frozenset({"harvested", "terminated", "cancelled"})
_FACT_PROVENANCES = frozenset(ACTIVE_PROVENANCES)


def _after(day: Optional[str], today: date) -> bool:
    try:
        return date.fromisoformat(str(day)[:10]) > today
    except ValueError:
        return False


def planned_cycle(timeline: Optional[dict], today: Optional[date] = None) -> Optional[dict]:
    """The crop still to be sown: overdue plan, else the next cycle (planned, or declared for a
    future day), else an undated plan."""
    tl = timeline or {}
    pending = tl.get("pending")
    if pending:
        return pending
    nxt = tl.get("next")
    if nxt:
        start = nxt.get("start") or {}
        if start.get("provenance") == "planned":
            return nxt
        if start.get("provenance") == "declared" and _after(start.get("date"), today or date.today()):
            return nxt
    for cy in tl.get("cycles") or []:
        start = cy.get("start") or {}
        # ASSUMPTION: the SDK leaves provenance None on a cycle with no dates at all;
        # an undated plan is any main crop with no start date and no field fact.
        if (cy.get("role") == "main_crop" and not start.get("date")
                and start.get("provenance") not in _FACT_PROVENANCES
                and cy.get("status") not in _CLOSED_STATUSES):
            return cy
    return None


def crop_status(timeline: Optional[dict]) -> str:
    current = (timeline or {}).get("current") or {}
    start = current.get("start") or {}
    if start.get("provenance") in ACTIVE_PROVENANCES and start.get("date"):
        return "active"
    return "none"


def freshness(assessed_at: Optional[str], now: datetime) -> str:
    if not assessed_at:
        return "none"
    try:
        ts = datetime.fromisoformat(str(assessed_at).replace("Z", "+00:00"))
    except ValueError:
        return "none"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    hours = (now - ts).total_seconds() / 3600
    if hours <= FRESH_HOURS:
        return "fresh"
    if hours <= AGING_HOURS:
        return "aging"
    return "stale"


def _severity(alert: dict) -> str:
    return str(alert.get("risk_level") or "").upper()


def _high_alerts(alerts: Optional[list]) -> list[dict]:
    return [a for a in (alerts or []) if _severity(a) in ALERT_SEVERITIES]


def _pending_crop(pending: dict, lang: str) -> Optional[str]:
    species = pending.get("species") or pending.get("crop_id") or pending.get("crop")
    names = pending.get("names") or {}
    return names.get(lang) or species


def _when(iso: Optional[str], today: date) -> Optional[str]:
    """Overdue or same-day dates are today's work; later dates stay ISO."""
    if not iso:
        return None
    try:
        due = date.fromisoformat(str(iso)[:10])
    except ValueError:
        return iso
    return "today" if due <= today else iso


def next_job(*, assessment: Optional[dict], timeline: Optional[dict], agro: Optional[dict],
             alerts: list[dict], forecast: Optional[dict], today: date,
             lang: str = DEFAULT_LANG) -> Optional[dict]:
    # ASSUMPTION: `lang` is not in the brief signature; optional kwarg, default "es".
    high = _high_alerts(alerts)
    if high:
        return {"kind": "treat", "when": "today", "detail": {"disease": high[0].get("disease")}}

    action = str((assessment or {}).get("recommendedAction") or "")
    if action == RecommendedAction.IRRIGATE_IMMEDIATE.value:
        return {"kind": "irrigate", "when": "today", "detail": {}}
    if action == RecommendedAction.IRRIGATE_SCHEDULED.value:
        return {"kind": "irrigate", "when": None, "detail": {"scheduled": True}}

    status = crop_status(timeline)
    planned = planned_cycle(timeline, today) or {}
    planned_date = _cycle_date(planned)

    if status == "none" and (planned.get("species") or planned.get("crop_id") or planned.get("crop")):
        detail: dict[str, Any] = {
            "crop": _pending_crop(planned, lang),
            "species": planned.get("species") or planned.get("crop_id") or planned.get("crop"),
        }
        if agro:
            detail["workability"] = ((agro.get("semaphores") or {}).get("workability"))
        return {"kind": "sow", "when": _when(planned_date, today), "detail": detail}

    harvest_date = ((forecast or {}).get("season") or {}).get("harvest_date")
    if (forecast or {}).get("status") == "done" and harvest_date:
        season_start = _cycle_date((timeline or {}).get("current"))
        if not season_start or str(harvest_date)[:10] >= season_start:
            return {"kind": "harvest", "when": _when(harvest_date, today), "detail": {"date": harvest_date}}

    if status == "active" and assessment is None:
        return {"kind": "pending_assessment", "when": None, "detail": {}}

    # ASSUMPTION: "none_until" = nothing to do now; reached for an active crop with an
    # assessment, or a crop-less parcel whose planned cycle has a date but no species.
    until = planned_date or _cycle_date((timeline or {}).get("next"))
    if status == "active" or until:
        return {"kind": "none_until", "when": until,
                "detail": {"date": until} if until else {}}
    return None


def _num(point: dict, key: str) -> Optional[float]:
    v = point.get(key)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def _water_drop(history: list[dict]) -> Optional[dict]:
    if len(history) < 2:
        return None
    last, prior = history[-1], history[-1 - BASELINE_POINTS:-1]
    for key, delta_ok in (("cwsi", lambda d: d >= CWSI_RISE_THRESHOLD),
                          ("balance", lambda d: -d >= BALANCE_DROP_MM)):
        current = _num(last, key)
        base = [v for v in (_num(p, key) for p in prior) if v is not None]
        if current is None or not base:
            continue
        mean = sum(base) / len(base)
        if delta_ok(round(current - mean, 9)):
            return {"metric": key, "current": current, "baseline": round(mean, 3)}
    return None


def surprise(*, assessment: Optional[dict], history: list[dict], alerts: list[dict],
             previous_alert_ids: Optional[set] = None) -> Optional[dict]:
    a = assessment or {}
    if a.get("vigorCondition") in VIGOR_SURPRISE:
        return {"code": "vigor_below_expected", "detail": {"vigor": a.get("vigorCondition")}}
    drop = _water_drop(history or [])
    if drop:
        return {"code": "water_drop", "detail": drop}
    if a.get("phenologyDeviation") in PHENOLOGY_SURPRISE:
        return {"code": "phenology_deviation", "detail": {"deviation": a.get("phenologyDeviation")}}
    if previous_alert_ids is not None:
        for alert in _high_alerts(alerts):
            if alert.get("id") not in previous_alert_ids:
                return {"code": "new_high_alert",
                        "detail": {"id": alert.get("id"), "disease": alert.get("disease")}}
    return None


def _group(row: dict) -> int:
    if row.get("surprise"):
        return 0
    job = row.get("nextJob")
    if job and job.get("kind") == "pending_assessment":
        return 5
    # ASSUMPTION: a none_until entry is "nothing to do", so it is not work (calm group).
    if job and job.get("kind") != "none_until":
        return 1 if job.get("when") == "today" else 2
    if row.get("cropStatus") == "none":
        return 4
    if not row.get("hasData"):
        return 5
    return 3


def rank(row: dict) -> tuple:
    sev = str(row.get("overallSeverity") or "").upper()
    name = str(row.get("parcelName") or row.get("name") or "")
    return (_group(row), SEVERITY_ORDER.get(sev, UNKNOWN_SEVERITY_RANK), name.casefold(), name)
