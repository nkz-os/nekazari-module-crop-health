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
from app.services.work_alerts import PARCEL_URN, _human_date, _parcel_label, plain_text
from app.services.worklist import job_when

logger = logging.getLogger(__name__)

VERSION = 1
TOTAL_BUDGET_S = 55.0       # the aggregator gives a module 60 s
FIGURES_CONCURRENCY = 5
FIGURES_BUDGET_S = 45.0
WEEK_DAYS = 7
STALE_DROPPED = frozenset({"irrigate", "treat"})
_WHEN_RANK = {"today": 0, "this_week": 1, "date": 2, "undated": 3}

# ASSUMPTION: eu wording is ours — confirm before shipping
_CHANGE_TEXTS = {
    "stale": {
        "es": "{parcel}: sin evaluación reciente",
        "eu": "{parcel}: ez dago ebaluazio berririk",
        "en": "{parcel}: no recent assessment",
    },
    "vigor_below_expected": {
        "es": "{parcel}: el cultivo pierde vigor",
        "eu": "{parcel}: laboreak sasoia galtzen ari da",
        "en": "{parcel}: the crop is losing vigor",
    },
    "phenology_deviation": {
        "es": "{parcel}: el desarrollo del cultivo se desvía de lo esperado",
        "eu": "{parcel}: laboreen garapena espero denetik aldentzen da",
        "en": "{parcel}: crop development differs from what is expected",
    },
}


def _monotonic() -> float:
    return time.monotonic()


def _subject(row: dict) -> dict:
    return {"type": "parcel", "id": PARCEL_URN + str(row["parcelId"]), "name": _parcel_label(row)}


def _link(row: dict) -> dict:
    return {"kind": "open_parcel", "params": {"parcelId": PARCEL_URN + str(row["parcelId"])}}


def _change(row: dict, key: str) -> dict:
    label = _parcel_label(row)
    return {"subject": _subject(row), "link": _link(row),
            "text": {lang: {"title": t.format(parcel=label)} for lang, t in _CHANGE_TEXTS[key].items()}}


# ASSUMPTION: eu wording is ours — confirm before shipping
# (title without crop, title with crop, why); only the report uses these.
_SOW_TEXTS = {
    "sow_dated": {
        "es": ("Siembra prevista en {parcel} hacia el {date}",
               "Siembra prevista de {crop} en {parcel} hacia el {date}", "Prepara la siembra."),
        "eu": ("{parcel} lursailean ereintza aurreikusita {date} inguruan",
               "{parcel} lursailean {crop} ereintza aurreikusita {date} inguruan", "Prestatu ereintza."),
        "en": ("Sowing planned in {parcel} around {date}",
               "Sowing of {crop} planned in {parcel} around {date}", "Get ready for sowing."),
    },
    "sow_undated": {
        "es": ("Siembra prevista en {parcel}, sin fecha",
               "Siembra prevista de {crop} en {parcel}, sin fecha", "Aún no hay fecha de siembra."),
        "eu": ("{parcel} lursailean ereintza aurreikusita, datarik gabe",
               "{parcel} lursailean {crop} ereintza aurreikusita, datarik gabe",
               "Oraindik ez dago ereintza-datarik."),
        "en": ("Sowing planned in {parcel}, no date",
               "Sowing of {crop} planned in {parcel}, no date", "There is no sowing date yet."),
    },
    "sow_today": {
        "es": ("Siembra pendiente en {parcel}", "Siembra pendiente de {crop} en {parcel}",
               "Revisa si el suelo está en condiciones."),
        "eu": ("{parcel} lursailean ereintza egiteke", "{parcel} lursailean {crop} ereintza egiteke",
               "Begiratu lurra egoera onean dagoen."),
        "en": ("Sowing due in {parcel}", "Sowing of {crop} due in {parcel}",
               "Check whether the soil is in good condition."),
    },
    "sow_today_good": {
        "es": ("Toca sembrar en {parcel}", "Toca sembrar {crop} en {parcel}",
               "Las condiciones son buenas para sembrar."),
        "eu": ("{parcel} lursailean ereiteko ordua da", "{parcel} lursailean {crop} ereiteko ordua da",
               "Baldintzak onak dira ereiteko."),
        "en": ("Time to sow in {parcel}", "Time to sow {crop} in {parcel}",
               "Conditions are good for sowing."),
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
        fields = {"parcel": _parcel_label(row), "crop": crop, "date": _human_date(detail, job.get("when"))}
        out[lang] = {"title": (with_crop if crop else plain).format(**fields), "why": why.format(**fields)}
    return out


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
        if kind == "sow":
            text = _sow_text(row, job)
        else:
            text = {lang: {"title": v["title"], "why": v["body"]}
                    for lang, v in plain_text(kind, row, detail, job.get("when")).items()}
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
    for row in rows:
        if row.get("_degraded"):
            complete = False
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
    return {"version": VERSION, "complete": complete, "tasks": tasks, "changes": changes,
            "figures": figures}
