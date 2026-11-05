"""Crop-health's contribution to the weekly farm report: tasks, changes and figures.

Contract: version 1, GET with `tenant_id` and `week_start`. An unreadable Orion raises
(the route answers 502): an outage must never look like "nothing to do". A parcel whose
inputs were unreliable sets `complete: false`; figures are support, so those left out
for time or fetch reasons do not.
"""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import date, timedelta
from typing import Any

import httpx
from nkz_platform_sdk.crypto import generate_hmac_signature

from app.api.assessments import build_parcel_rows
from app.config import get_settings
from app.services import context_client
from app.services.pipeline import (
    _DAILY_TIMEOUT_S,
    _DEFAULT_UPPER_CUTOFF,
    _hmac_secret,
    _utc_today,
)
from app.services.work_alerts import PARCEL_URN, _human_date, _parcel_label
from app.services.worklist import job_when

logger = logging.getLogger(__name__)

VERSION = 1
TOTAL_BUDGET_S = 55.0       # the aggregator gives a module 60 s
FIGURES_CONCURRENCY = 5
FIGURES_BUDGET_S = 45.0
WEEK_DAYS = 7
STALE_DROPPED = frozenset({"irrigate", "treat"})
_WHEN_RANK = {"today": 0, "this_week": 1, "date": 2, "undated": 3}

# Titles carry neither the parcel name nor the time: the renderer prints
# "{name}: {title} — {when}" itself.
# ASSUMPTION: eu wording is ours — confirm before shipping
_CHANGE_TEXTS = {
    "stale": {"es": "Sin evaluación reciente", "eu": "Ebaluazio berririk ez",
              "en": "No recent assessment"},
    "vigor_below_expected": {"es": "El cultivo pierde vigor", "eu": "Laboreak sasoia galtzen ari da",
                             "en": "The crop is losing vigor"},
    "phenology_deviation": {"es": "El desarrollo del cultivo se desvía de lo esperado",
                            "eu": "Laboreen garapena espero denetik aldentzen da",
                            "en": "Crop development differs from what is expected"},
}


def _monotonic() -> float:
    return time.monotonic()


def _subject(row: dict) -> dict:
    return {"type": "parcel", "id": PARCEL_URN + str(row["parcelId"]), "name": _parcel_label(row)}


def _link(row: dict) -> dict:
    return {"kind": "open_parcel", "params": {"parcelId": PARCEL_URN + str(row["parcelId"])}}


def _change(row: dict, key: str) -> dict:
    return {"subject": _subject(row), "link": _link(row),
            "text": {lang: {"title": t} for lang, t in _CHANGE_TEXTS[key].items()}}


# ASSUMPTION: eu wording is ours — confirm before shipping
# Report-only wording: (title without crop, title with crop, why). No parcel name, no time in titles.
_SOW_TEXTS = {
    "sow_dated": {
        "es": ("Sembrar", "Sembrar {crop}", "Prepara la siembra hacia el {date}."),
        "eu": ("Ereitea", "Ereitea: {crop}", "Prestatu ereintza {date} inguruan."),
        "en": ("Sow", "Sow {crop}", "Get ready for sowing around {date}."),
    },
    "sow_undated": {
        "es": ("Sembrar", "Sembrar {crop}", "Aún no hay fecha de siembra."),
        "eu": ("Ereitea", "Ereitea: {crop}", "Oraindik ez dago ereintza-datarik."),
        "en": ("Sow", "Sow {crop}", "There is no sowing date yet."),
    },
    "sow_today": {
        "es": ("Sembrar", "Sembrar {crop}", "Revisa si el suelo está en condiciones."),
        "eu": ("Ereitea", "Ereitea: {crop}", "Begiratu lurra egoera onean dagoen."),
        "en": ("Sow", "Sow {crop}", "Check whether the soil is in good condition."),
    },
    "sow_today_good": {
        "es": ("Sembrar", "Sembrar {crop}", "Las condiciones son buenas para sembrar."),
        "eu": ("Ereitea", "Ereitea: {crop}", "Baldintzak onak dira ereiteko."),
        "en": ("Sow", "Sow {crop}", "Conditions are good for sowing."),
    },
}

# (title without disease, title with disease, why)
_OTHER_TEXTS = {
    "irrigate": {
        "es": ("Regar", None, "Según el balance de agua, hoy conviene regar."),
        "eu": ("Ureztatu", None, "Ur-balantzearen arabera, gaur ureztatzea komeni da."),
        "en": ("Irrigate", None, "Based on the water balance, irrigating today is advisable."),
    },
    "irrigate_week": {
        "es": ("Regar", None, "Según el balance de agua, conviene regar esta semana."),
        "eu": ("Ureztatu", None, "Ur-balantzearen arabera, aste honetan ureztatzea komeni da."),
        "en": ("Irrigate", None, "Based on the water balance, irrigating this week is advisable."),
    },
    "treat": {
        "es": ("Tratar", "Tratar: {disease}", "Riesgo alto; conviene tratar hoy."),
        "eu": ("Tratatu", "Tratatu: {disease}", "Arrisku handia; gaur tratatzea komeni da."),
        "en": ("Treat", "Treat: {disease}", "High risk; treating today is advisable."),
    },
    "harvest": {
        "es": ("Cosecha prevista", None, "Prepara la cosecha hacia el {date}."),
        "eu": ("Uzta aurreikusita", None, "Prestatu uzta {date} inguruan."),
        "en": ("Harvest expected", None, "Get ready to harvest around {date}."),
    },
}


def _sow_text(row: dict, job: dict) -> dict:
    """Report wording of a sowing: good conditions are claimed only when due today and workable."""
    detail = job.get("detail") or {}
    if job.get("when") == "today":
        key = "sow_today_good" if detail.get("workability") == "optimal" else "sow_today"
    elif job_when(job)["type"] == "date" and _human_date(detail, job.get("when")):
        key = "sow_dated"
    else:
        key = "sow_undated"
    names = (row.get("plannedCrop") or {}).get("names") or {}
    out = {}
    for lang, (plain, with_crop, why) in _SOW_TEXTS[key].items():
        # Only a localized name is printed, never a species code.
        crop = str(names.get(lang) or "")
        fields = {"crop": crop, "date": _human_date(detail, job.get("when"))}
        out[lang] = {"title": (with_crop if crop else plain).format(**fields), "why": why.format(**fields)}
    return out


def _report_text(kind: str, job: dict) -> dict:
    """Report wording of irrigate, treat and harvest: parcel-free titles, a sentence in `why`."""
    detail = job.get("detail") or {}
    key = "irrigate_week" if kind == "irrigate" and not job.get("when") else kind
    disease = str(detail.get("disease") or "")
    # A bare code (snake_case) is not a name a farmer reads: use the nameless wording.
    named = bool(disease) and "_" not in disease
    out = {}
    for lang, (plain, with_disease, why) in _OTHER_TEXTS[key].items():
        fields = {"disease": disease, "date": _human_date(detail, job.get("when"))}
        title = with_disease if (with_disease and named) else plain
        out[lang] = {"title": title.format(**fields), "why": why.format(**fields)}
    return out


def _is_unknown(row: dict) -> bool:
    """An active-crop parcel with no recent assessment, or one still waiting for its first."""
    if row.get("cropStatus") != "active":
        return False
    return row.get("freshness") == "stale" or (row.get("nextJob") or {}).get("kind") == "pending_assessment"


def _tasks_and_changes(row: dict, week_start: date) -> tuple[list[dict], list[dict]]:
    tasks: list[dict] = []
    changes: list[dict] = []
    stale = row.get("freshness") == "stale"
    for job in row.get("jobs") or []:
        kind = job.get("kind")
        if stale and kind in STALE_DROPPED:
            continue
        when = job_when(job)
        detail = job.get("detail") or {}
        text = _sow_text(row, job) if kind == "sow" else _report_text(kind, job)
        tasks.append({
            "id": f"{kind}:{row['parcelId']}",
            "subject": _subject(row),
            "kind": kind,
            "when": when,
            "text": text,
            "link": _link(row),
            "relatedAlertId": detail.get("alertId") or None,
        })
    if stale and row.get("cropStatus") == "active":
        changes.append(_change(row, "stale"))
    elif not stale:
        code = (row.get("surprise") or {}).get("code")
        if code in _CHANGE_TEXTS:
            changes.append(_change(row, code))
    return tasks, changes


# ---- figures ----------------------------------------------------------------

def _closed(days: list[dict], start: date, end: date, today: date) -> dict[date, dict]:
    """The closed days of the window by date. A record without `kind` is closed only before today."""
    out: dict[date, dict] = {}
    for rec in days or []:
        try:
            day = date.fromisoformat(str(rec.get("date"))[:10])
        except ValueError:
            continue
        if not start <= day <= end:
            continue
        kind = rec.get("kind")
        if (kind is not None and kind != "closed") or (kind is None and day >= today):
            continue
        out[day] = rec
    return out


def _sensor_all(closed: list[dict], variables: tuple[str, ...]) -> bool:
    # Only the named variables are read from `sources`, never iterated: it may carry
    # keys that are None or not a source name.
    for rec in closed:
        sources = rec.get("sources") or {}
        if any(sources.get(v) != "iot_sensor" for v in variables):
            return False
    return True


def _figures_from_days(days: list[dict], *, base_temp: float, upper_cutoff: float | None,
                       today: date, week_start: date) -> list[dict]:
    """Rain, evapotranspiration and growing degree days over the 7 closed days of the week.

    A metric without a value on every one of the 7 days is omitted, not shown as a partial
    total. If the parcel's origins are mixed, every metric says "estimated".
    """
    start, end = week_start - timedelta(days=WEEK_DAYS), week_start - timedelta(days=1)
    by_day = _closed(days, start, end, today)
    if len(by_day) < WEEK_DAYS:
        return []
    recs = [by_day[d] for d in sorted(by_day)]

    metrics: list[tuple[str, float, tuple[str, ...]]] = []
    for key, field in (("rain_mm", "precip_mm"), ("et0_mm", "et0_mm")):
        vals = [r.get(field) for r in recs]
        if all(isinstance(v, (int, float)) for v in vals):
            metrics.append((key, round(sum(vals), 1), (field,)))
    temps = [(r.get("tmin_c"), r.get("tmax_c")) for r in recs]
    if all(isinstance(a, (int, float)) and isinstance(b, (int, float)) for a, b in temps):
        cap = upper_cutoff if upper_cutoff is not None else _DEFAULT_UPPER_CUTOFF
        gdd = sum(max(0.0, (min(b, cap) + a) / 2.0 - base_temp) for a, b in temps)
        metrics.append(("gdd", round(gdd, 1), ("tmin_c", "tmax_c")))

    all_sensor = bool(metrics) and all(_sensor_all(recs, v) for _, _, v in metrics)
    origin = "sensor" if all_sensor else "estimated"
    return [{"key": k, "value": v, "origin": origin} for k, v, _ in metrics]


async def _base_temp(tenant_id: str, parcel_id: str) -> tuple[float, float | None]:
    """Base temperature and Tmax cap of the parcel's crop, resolved as the assessment pipeline does."""
    species = "generic"
    try:
        ctx = await context_client.get_crop_context(parcel_id=parcel_id, tenant_id=tenant_id)
        if ctx and ctx.crop and ctx.crop.eppo != "unknown":
            species = ctx.crop.eppo
        elif ctx and ctx.crop and ctx.crop.name:
            species = ctx.crop.name
    except Exception as exc:  # noqa: BLE001 — same fail-safe as the pipeline: generic crop
        logger.warning("weekly_report: crop context failed parcel=%s: %s", parcel_id, exc)
    table = await context_client.get_phenology_stages(species)
    return (table.base_temp if table else 10.0), (table.upper_cutoff if table else None)


async def _parcel_figures(tenant_id: str, week_start: date, parcel_id: str) -> list[dict] | None:
    """The parcel's weekly metrics, or None when weather-api could not be read."""
    settings = get_settings()
    secret = _hmac_secret()
    if not settings.weather_daily_url or not secret:
        logger.warning("weekly_report: weather-api url or signing secret unset — no figures")
        return None
    base_temp, upper_cutoff = await _base_temp(tenant_id, parcel_id)
    start, end = week_start - timedelta(days=WEEK_DAYS), week_start - timedelta(days=1)
    params = {
        "start": start.isoformat(), "end": end.isoformat(), "fill": "open_meteo",
        "base_temp": str(base_temp),
        "upper_cutoff": str(upper_cutoff if upper_cutoff is not None else _DEFAULT_UPPER_CUTOFF),
    }
    headers = {"X-Tenant-ID": tenant_id,
               "X-Auth-Signature": generate_hmac_signature(secret, "", tenant_id)}
    short = parcel_id.split(":")[-1]
    try:
        async with httpx.AsyncClient(timeout=_DAILY_TIMEOUT_S) as client:
            resp = await client.get(f"{settings.weather_daily_url}/api/weather/parcel/{short}/daily",
                                    params=params, headers=headers)
        if resp.status_code != 200:
            logger.warning("weekly_report: weather-api HTTP %d parcel=%s", resp.status_code, parcel_id)
            return None
        days = (resp.json() or {}).get("days") or []
    except Exception as exc:  # noqa: BLE001 — figures are support: omitted, never fatal
        logger.warning("weekly_report: weather-api failed parcel=%s: %s", parcel_id, exc)
        return None
    return _figures_from_days(days, base_temp=base_temp, upper_cutoff=upper_cutoff,
                              today=_utc_today(), week_start=week_start)


async def _all_figures(tenant_id: str, week_start: date, rows: list[dict],
                       budget_s: float = FIGURES_BUDGET_S) -> list[dict]:
    """Figures of every parcel, 5 at a time within 45 s in total; the rest are left out."""
    semaphore = asyncio.Semaphore(FIGURES_CONCURRENCY)

    async def one(row: dict):
        async with semaphore:
            return await _parcel_figures(tenant_id, week_start, str(row["parcelId"]))

    tasks = [asyncio.ensure_future(one(r)) for r in rows]
    if tasks:
        await asyncio.wait(tasks, timeout=budget_s)
    out: list[dict] = []
    for row, task in zip(rows, tasks):
        if not task.done():
            task.cancel()
            logger.warning("weekly_report: figures timed out parcel=%s", row["parcelId"])
            continue
        if task.cancelled() or task.exception() is not None:
            continue
        metrics = task.result()
        if metrics:
            out.append({"subject": _subject(row), "metrics": metrics})
    return out


async def build(tenant_id: str, week_start: date) -> dict[str, Any]:
    """The contribution of the tenant's parcels. Raises when Orion cannot be read."""
    started = _monotonic()
    rows = await build_parcel_rows(None, tenant_id, with_history=False, strict=True)
    tasks: list[dict] = []
    changes: list[dict] = []
    complete = True
    unknown = 0
    for row in rows:
        if row.get("_degraded"):
            complete = False
        if _is_unknown(row):
            unknown += 1
        try:
            t, c = _tasks_and_changes(row, week_start)
        except Exception as exc:  # noqa: BLE001 — one malformed row never hides the rest
            logger.warning("weekly_report: row skipped tenant=%s parcel=%s: %s",
                           tenant_id, row.get("parcelId"), exc)
            complete = False
            continue
        tasks += t
        changes += c
    tasks.sort(key=lambda t: (_WHEN_RANK[t["when"]["type"]], t["when"]["date"] or ""))
    budget = min(FIGURES_BUDGET_S, TOTAL_BUDGET_S - (_monotonic() - started))
    if budget > 0:
        figures = await _all_figures(tenant_id, week_start, rows, budget)
    else:
        logger.warning("weekly_report: no time left for figures tenant=%s", tenant_id)
        figures = []
    return {"version": VERSION, "complete": complete, "unknown_count": unknown,
            "tasks": tasks, "changes": changes,
            "figures": figures}
