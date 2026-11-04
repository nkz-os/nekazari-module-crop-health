"""«Toca hacer» alerts: one Alert per parcel, task and day, from the parcel work list.

The id carries the due day (`today-YYYYMMDD` for work due now, `YYYYMMDD` for a dated
task), so a task that reappears on another day is a new delivery for the notifier,
which dedups on (id, severity). Writes go to Orion-LD only, through OrionClient.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone

from nkz_platform_sdk.orion import OrionClient

from app.api.assessments import ORION_MAX_PAGES, ORION_PAGE_SIZE, build_parcel_rows
from app.config import get_settings

logger = logging.getLogger(__name__)

PARCEL_URN = "urn:ngsi-ld:AgriParcel:"
KINDS = ("irrigate", "sow", "treat", "harvest")
DUE_KINDS = ("irrigate", "sow", "treat")  # severity "high" when due today
# Only these vibrate on the day: work_treat derives from risk's active high disease
# Alert, which already vibrates that morning, so treat stays silent.
VIBRATING = ("irrigate", "sow")
ALERT_PREFIX = "work_"

# ASSUMPTION: eu/en wording is ours (es is the owner-approved text) — confirm before shipping.
_TEXTS = {
    "irrigate": {
        "es": ("Toca regar {parcel}", "Según el balance de agua, hoy conviene regar."),
        "eu": ("{parcel} ureztatzeko ordua da", "Ur-balantzearen arabera, gaur ureztatzea komeni da."),
        "en": ("Time to irrigate {parcel}", "Based on the water balance, irrigating today is advisable."),
    },
    "sow_plain": {
        "es": ("Toca sembrar en {parcel}", "Las condiciones son buenas para sembrar."),
        "eu": ("{parcel} lursailean ereiteko ordua da", "Baldintzak onak dira ereiteko."),
        "en": ("Time to sow in {parcel}", "Conditions are good for sowing."),
    },
    "sow": {
        "es": ("Toca sembrar {crop} en {parcel}", "Las condiciones son buenas para sembrar."),
        "eu": ("{parcel} lursailean {crop} ereiteko ordua da", "Baldintzak onak dira ereiteko."),
        "en": ("Time to sow {crop} in {parcel}", "Conditions are good for sowing."),
    },
    "treat": {
        "es": ("Toca tratar {parcel}: {disease}", "Riesgo alto; conviene tratar hoy."),
        "eu": ("{parcel} tratatzeko ordua da: {disease}", "Arrisku handia; gaur tratatzea komeni da."),
        "en": ("Time to treat {parcel}: {disease}", "High risk; treating today is advisable."),
    },
    "treat_plain": {
        "es": ("Toca tratar {parcel}", "Riesgo alto; conviene tratar hoy."),
        "eu": ("{parcel} tratatzeko ordua da", "Arrisku handia; gaur tratatzea komeni da."),
        "en": ("Time to treat {parcel}", "High risk; treating today is advisable."),
    },
    "harvest": {
        "es": ("Cosecha prevista en {parcel}", "Prepara la cosecha hacia el {date}."),
        "eu": ("{parcel} lursailean uzta aurreikusita", "Prestatu uzta {date} inguruan."),
        "en": ("Harvest expected in {parcel}", "Get ready to harvest around {date}."),
    },
}


def _today() -> date:
    return datetime.now(timezone.utc).date()


def _prop(value) -> dict:
    return {"type": "Property", "value": value}


def _crop_name(row: dict, detail: dict, lang: str) -> str:
    planned = row.get("plannedCrop") or {}
    names = planned.get("names") or {}
    return names.get(lang) or detail.get("crop") or planned.get("species") or ""


def _parcel_label(row: dict) -> str:
    """The parcel's name; the short id when it has none (the row falls back to the full id).

    ASSUMPTION: the short form is the first 8 characters of the parcel id.
    """
    pid = str(row.get("parcelId") or "")
    name = str(row.get("parcelName") or "")
    return name if name and name != pid else pid[:8]


def _human_date(detail: dict, when: str | None) -> str:
    raw = str(detail.get("date") or (when if when and when != "today" else "") or "")[:10]
    try:
        return date.fromisoformat(raw).strftime("%d/%m/%Y")
    except ValueError:
        return raw


def _plain(kind: str, row: dict, detail: dict, when: str | None) -> dict:
    key = kind
    disease = str(detail.get("disease") or "")
    # A bare code (snake_case) is not a name a farmer reads: use the nameless wording.
    if kind == "treat" and (not disease or "_" in disease):
        key = "treat_plain"
    if kind == "sow" and not _crop_name(row, detail, "es"):
        key = "sow_plain"
    out = {}
    for lang, (title, body) in _TEXTS[key].items():
        fields = {"parcel": _parcel_label(row), "crop": _crop_name(row, detail, lang),
                  "disease": disease, "date": _human_date(detail, when)}
        out[lang] = {"title": title.format(**fields), "body": body.format(**fields)}
    return out


def build_work_alert(tenant_id: str, row: dict, today: date) -> dict | None:
    """The normalized NGSI-LD Alert of one work-list row, or None when it has no task to flag."""
    job = row.get("nextJob") or {}
    kind = job.get("kind")
    if kind not in KINDS:
        return None
    when = job.get("when")
    detail = job.get("detail") or {}
    if when == "today":
        suffix = f"today-{today:%Y%m%d}"
    elif when:
        try:
            suffix = date.fromisoformat(str(when)[:10]).strftime("%Y%m%d")
        except ValueError:
            return None
    elif kind == "irrigate":
        suffix = f"{today:%Y%m%d}"
    else:
        return None
    due_now = when == "today" and kind in DUE_KINDS
    vibrates = when == "today" and kind in VIBRATING
    parcel = row["parcelId"]
    urn = PARCEL_URN + parcel
    # ASSUMPTION: harvest opens the parcel (nothing to record yet) — owner ruling, confirm in review.
    action = ({"kind": "open_parcel", "params": {"parcelId": urn}} if kind == "harvest"
              else {"kind": "record_operation", "params": {"parcelId": urn, "kind": kind}})
    return {
        "id": f"urn:ngsi-ld:Alert:{tenant_id}:{ALERT_PREFIX}{kind}:{parcel}:{suffix}",
        "type": "Alert",
        "category": _prop("agronomic"),
        "alertType": _prop(f"{ALERT_PREFIX}{kind}"),
        "severity": _prop("high" if due_now else "medium"),
        "refEntity": {"type": "Relationship", "object": urn},
        "refEntityType": _prop("AgriParcel"),
        "status": _prop("active"),
        "observedAt": {"type": "Property",
                       "value": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
        "evaluationData": _prop({"kind": kind, "when": when, "detail": detail}),
        "plain": _prop(_plain(kind, row, detail, when)),
        "urgency": _prop("vibrate" if vibrates else "silent"),
        "action": _prop(action),
    }


def _v(value):
    return value.get("value") if isinstance(value, dict) and "value" in value else value


async def _active_work_alerts(client: OrionClient, tenant_id: str) -> list[dict]:
    """Active `work_*` Alerts of the tenant.

    Orion filters `status`; the id prefix is checked here because the SDK's
    query_entities has no idPattern. Reaching the page cap raises: a truncated list
    would make the job re-emit or skip alerts silently.
    """
    prefix = f"urn:ngsi-ld:Alert:{tenant_id}:{ALERT_PREFIX}"
    rows: list[dict] = []
    for page in range(ORION_MAX_PAGES):
        batch = await client.query_entities(type="Alert", q='status=="active"', options="keyValues",
                                            limit=ORION_PAGE_SIZE, offset=page * ORION_PAGE_SIZE)
        rows.extend(batch)
        if len(batch) < ORION_PAGE_SIZE:
            break
    else:
        raise RuntimeError(f"work_alerts: more than {ORION_MAX_PAGES * ORION_PAGE_SIZE} active alerts")
    return [r for r in rows
            if str(r.get("id", "")).startswith(prefix) and _v(r.get("status")) == "active"]


def _parcel_of(alert: dict) -> str:
    ref = alert.get("refEntity")
    ref = ref.get("object") if isinstance(ref, dict) else ref
    return str(ref or "").replace(PARCEL_URN, "")


async def emit_work_alerts(tenant_id: str) -> dict:
    """Converge the tenant's active work Alerts on its parcels' current next jobs.

    Raises when the parcels or the Alerts cannot be read: an outage must not look like
    "no tasks" and resolve everything. A parcel whose inputs were unreliable (`_degraded`)
    is unknown: its alerts are neither emitted nor resolved this run.
    """
    today = _today()
    rows = await build_parcel_rows(None, tenant_id, with_history=False, strict=True)
    desired: dict[str, dict] = {}
    degraded: set[str] = set()
    for row in rows:
        if row.get("_degraded"):
            degraded.add(str(row.get("parcelId")))
            continue
        try:
            alert = build_work_alert(tenant_id, row, today)
        except Exception as exc:  # noqa: BLE001 — one malformed row never stops the rest
            logger.warning("work_alerts: row skipped tenant=%s parcel=%s: %s",
                           tenant_id, row.get("parcelId"), exc)
            degraded.add(str(row.get("parcelId")))
            continue
        if alert:
            desired[alert["id"]] = alert

    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        active = {a["id"]: a for a in await _active_work_alerts(client, tenant_id)}
        new = [a for i, a in desired.items() if i not in active]
        unchanged = sum(1 for i in desired if i in active)
        stale = [i for i, a in active.items() if i not in desired and _parcel_of(a) not in degraded]
        if new:
            await client.upsert_entities_batch(new)
        resolved = 0
        for alert_id in stale:
            try:
                await client.update_entity_attrs(alert_id, {"status": _prop("resolved")})
                resolved += 1
            except Exception as exc:  # noqa: BLE001 — retried by the next run
                logger.warning("work_alerts: resolve failed tenant=%s id=%s: %s", tenant_id, alert_id, exc)
    finally:
        await client.close()
    result = {"emitted": len(new), "resolved": resolved, "unchanged": unchanged}
    logger.info("work_alerts: tenant=%s degraded=%d %s", tenant_id, len(degraded), result)
    return result
