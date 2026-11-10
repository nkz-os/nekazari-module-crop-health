"""Milestone dates and observed stages, compared (pure).

The cereal calendar answers with the dates of a few milestones. A stage of the
table starts where a milestone has the same thermal time as the stage's lower
bound, or at sowing when that bound is 0. Nothing is invented: a stage whose
start is not known gives no model stage for the days it may cover.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from app.schemas import StageTable

_GDD_TOL = 0.05

# BBCH code -> comparable milestone (contract A4, item 6).
_BBCH_MILESTONES = ((9, 10, "emergence"), (51, 59, "flowering_start"), (87, 92, "maturity"))


def _iso(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except (TypeError, ValueError):
        return None


def milestone_date(milestone: Any) -> date | None:
    """``date`` of a reached milestone, ``date_p50`` of a projected one; None otherwise."""
    if not isinstance(milestone, dict):
        return None
    if milestone.get("status") == "reached":
        return _iso(milestone.get("date"))
    if milestone.get("status") == "projected":
        return _iso(milestone.get("date_p50"))
    return None


def stage_for_bbch(code: str, table: StageTable) -> str | None:
    try:
        n = int(code)
    except (TypeError, ValueError):
        return None
    for name, (lo, hi) in table.stage_bbch.items():
        if lo <= n <= hi:
            return name
    return None


def milestone_for_bbch(code: str) -> str | None:
    try:
        n = int(code)
    except (TypeError, ValueError):
        return None
    for lo, hi, name in _BBCH_MILESTONES:
        if lo <= n <= hi:
            return name
    return None


def _stage_starts(table: StageTable, milestones: dict, sowing: date | None) -> list[tuple[str, date | None]]:
    ordered = sorted(table.stages.items(), key=lambda kv: kv[1][0])
    dated = [(m.get("gdd"), milestone_date(m)) for m in (milestones or {}).values() if isinstance(m, dict)]
    out: list[tuple[str, date | None]] = []
    for name, (gdd_min, _gdd_max) in ordered:
        start = None
        if gdd_min <= 0:
            start = sowing
        else:
            for gdd, day in dated:
                if isinstance(gdd, (int, float)) and abs(gdd - gdd_min) <= _GDD_TOL and day is not None:
                    start = day
                    break
        out.append((name, start))
    return out


def model_stage_on_date(day: date, table: StageTable, milestones: dict, sowing: date | None) -> str | None:
    """Stage the dated milestones put on ``day``, or None when they cannot say."""
    starts = _stage_starts(table, milestones, sowing)
    chosen = None
    for i, (_name, start) in enumerate(starts):
        if start is not None and start <= day:
            chosen = i
    if chosen is None:
        return None
    for _name, start in starts[chosen + 1:]:
        if start is not None and start > day:
            break
        if start is None:  # a stage of unknown start lies between: it may already have begun
            return None
    return starts[chosen][0]


def observation_rows(observed: list[dict], table: StageTable, milestones: dict | None,
                     sowing: date | None) -> list[dict]:
    milestones = milestones or {}
    rows = []
    for obs in observed:
        day = _iso(obs.get("date"))
        code = obs.get("bbch")
        ms_name = milestone_for_bbch(code)
        model_day = milestone_date(milestones.get(ms_name)) if ms_name else None
        rows.append({
            "date": obs.get("date"),
            "bbch": code,
            "stage": stage_for_bbch(code, table),
            "modelStageOnDate": model_stage_on_date(day, table, milestones, sowing) if day else None,
            "milestone": ms_name,
            "deltaDays": (model_day - day).days if model_day and day else None,
        })
    return rows


def _calendar_stage_dates(stages: list, table: StageTable, milestones: dict | None) -> None:
    """Date the stages of a calendar table from the milestone dates only, in place.

    The base status projects stage dates at a fixed daily rate; for the calendar that would show a
    second, different date for an event the milestones already date. A stage not reached yet starts
    on the date of the milestone with its lower bound; the current stage ends where the next one
    begins; anything the milestones do not date gets no date.
    """
    starts = dict(_stage_starts(table, milestones or {}, None))
    names = [item.get("stage") for item in stages]
    for i, item in enumerate(stages):
        start = starts.get(item.get("stage"))
        nxt = starts.get(names[i + 1]) if i + 1 < len(names) else None
        if "projectedDate" in item:
            item["projectedDate"] = start.isoformat() if start and not item.get("reached") else None
        if "projectedEnd" in item:
            item["projectedEnd"] = nxt.isoformat() if nxt and item.get("current") else None


def extend_status(status: dict, table: StageTable, record: dict | None, observed: list[dict] | None) -> dict:
    """Add the cereal-calendar fields to a phenology-status dict, in place.

    Table fields appear only when the table carries them; milestones only with a stored answer;
    ``observations`` only when the table is the calendar's or something was observed. For a
    calendar table the projected stage dates are replaced by the milestone dates (or cleared);
    for every other crop the existing keys are never touched.
    """
    if table.model is not None:
        status["model"] = table.model
        status["calibration"] = table.calibration
        status["validation"] = table.validation
        status["sources"] = table.sources
        status["experimental"] = True
        status["basis"] = "thermal_time"
    block = (record or {}).get("phenology") or {}
    season = (record or {}).get("season") or {}
    if record:
        status["milestones"] = block.get("milestones") or {}
        status["notes"] = block.get("notes") or []
        if block.get("basis"):
            status["basis"] = block["basis"]
    if table.model is not None and isinstance(status.get("stages"), list):
        _calendar_stage_dates(status["stages"], table, block.get("milestones"))
    if table.stage_bbch and isinstance(status.get("stages"), list):
        for item in status["stages"]:
            rng = table.stage_bbch.get(item.get("stage"))
            if rng:
                item["bbchFrom"], item["bbchTo"] = rng
    if table.model is not None or observed:
        sowing = _iso((season.get("sowing") or {}).get("date")) or _iso(status.get("seasonStart"))
        status["observations"] = observation_rows(observed or [], table, block.get("milestones"), sowing)
    return status
