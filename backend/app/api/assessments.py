"""Assessments API — query CropHealthAssessment entities from Orion-LD."""

from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone

import httpx
from fastapi import APIRouter, Query, Request

from app.api.assessment_mapper import (
    dedupe_latest_per_parcel,
    PARCEL_VALUE_KEYS,
    dedupe_latest_per_zone,
    differs_from_parcel,
    extract_parcel_id,
    extract_zone_id,
    extract_zone_urn,
    map_entity_to_assessment,
    map_entity_to_zone_assessment,
    prop_value,
)
from app.config import get_settings
from app.services import worklist
from app.services.zonation import is_whole_parcel, resolve_zones
from nkz_platform_sdk.orion import OrionClient

router = APIRouter()

logger = logging.getLogger(__name__)

# Gateway-injected identity the timeseries-reader needs to authorize a call
# made on behalf of the user (its routes sit behind require_auth).
_READER_FORWARDED_HEADERS = ("Authorization", "X-Tenant-ID", "X-Auth-Signature")

_WORKLIST_KEYS = ("recommendedAction", "vigorCondition", "phenologyDeviation")


def get_redis_state():
    """Late import: app.main imports this package. None when the app is not started."""
    try:
        from app.main import get_redis_state as _get

        return _get()
    except Exception as exc:  # noqa: BLE001 — forecast is optional input to the work list
        logger.warning("worklist: redis state unavailable: %s", exc)
        return None


def _flat(entity: dict | None) -> dict | None:
    """Plain values of the assessment attributes the work-list rules read."""
    if not entity:
        return None
    return {k: prop_value(entity, k, None) for k in _WORKLIST_KEYS}


def _planned_crop(timeline: dict | None) -> dict | None:
    pending = (timeline or {}).get("pending") or {}
    species = pending.get("species")
    if not species:
        return None
    out: dict = {"species": species}
    if pending.get("names"):
        out["names"] = pending["names"]
    sowing = (pending.get("start") or {}).get("date")
    out["sowingDate"] = sowing or None
    return out


def _worklist_fields(*, assessment: dict | None, assessed_at: str | None, crop_name: str | None,
                     inputs: dict, alerts: list[dict], now: datetime) -> dict:
    """Crop status, freshness, next job and surprise of one parcel (pure over its inputs)."""
    timeline = inputs.get("timeline")
    status = worklist.crop_status(timeline)
    fresh = worklist.freshness(assessed_at, now)
    return {
        "cropStatus": status,
        "freshness": fresh,
        "stale": fresh == "stale" or (status == "none" and assessed_at is not None),
        "nextJob": worklist.next_job(
            assessment=assessment, timeline=timeline, agro=inputs.get("agro"),
            alerts=alerts, forecast=inputs.get("forecast"), today=now.date(),
        ),
        "surprise": worklist.surprise(
            assessment=assessment, history=inputs.get("history") or [], alerts=alerts,
        ),
        "plannedCrop": _planned_crop(timeline),
        "lastAssessment": (
            {"assessedAt": assessed_at, "cropName": crop_name}
            if status == "none" and assessed_at is not None else None
        ),
    }


async def _alerts_safe(tenant_id: str) -> list[dict]:
    try:
        return await _active_alert_rows(tenant_id)
    except Exception as exc:  # noqa: BLE001
        logger.warning("worklist: alerts failed tenant=%s: %s", tenant_id, exc)
        return []


def _reader_headers(request: Request) -> dict[str, str]:
    """Forward the caller's auth context to the timeseries-reader (only headers present)."""
    return {
        name: value
        for name in _READER_FORWARDED_HEADERS
        if (value := request.headers.get(name))
    }


async def _fetch_assessment_entities(tenant_id: str, parcel_id: str = "", limit: int = 100) -> list[dict]:
    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        q = None
        if parcel_id:
            q = (
                f'(hasAgriParcel=="urn:ngsi-ld:AgriParcel:{parcel_id}"'
                f'|refAgriParcel=="urn:ngsi-ld:AgriParcel:{parcel_id}")'
            )
        entities = await client.query_entities(
            type="CropHealthAssessment",
            q=q,
            limit=limit,
            options="keyValues",
        )
        # Exclude activation scaffolding placeholders (provenance == "placeholder"):
        # they carry no data and out-rank real dated assessments by assessedAt.
        return [e for e in entities if e.get("provenance") != "placeholder"]
    except Exception as e:
        logger.warning("Orion CropHealthAssessment query failed: %s", e)
        return []
    finally:
        await client.close()


async def _fetch_parcel_names(tenant_id: str) -> dict[str, str]:
    """Fetch AgriParcel display names keyed by short parcel id.

    The assessment mapper only sees the CropHealthAssessment entity, so it
    cannot know the human-readable parcel name (AgriParcel.name). Widgets
    fall back to the bare UUID without this lookup.
    """
    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        parcels = await client.query_entities(
            type="AgriParcel",
            limit=200,
            options="keyValues",
        )
    except Exception as e:
        logger.warning("Orion AgriParcel query failed (names): %s", e)
        return {}
    finally:
        await client.close()

    names: dict[str, str] = {}
    for p in parcels:
        pid = str(p.get("id", "")).replace("urn:ngsi-ld:AgriParcel:", "")
        if not pid:
            continue
        name = p.get("name")
        if isinstance(name, dict):
            name = name.get("value")
        names[pid] = name or pid
    return names


async def _fetch_zone_assessment_entities(tenant_id: str, parcel_id: str = "", limit: int = 100) -> list[dict]:
    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        q = None
        if parcel_id:
            q = (
                f'(hasAgriParcel=="urn:ngsi-ld:AgriParcel:{parcel_id}"'
                f'|refAgriParcel=="urn:ngsi-ld:AgriParcel:{parcel_id}")'
            )
        return await client.query_entities(
            type="CropHealthZoneAssessment",
            q=q,
            limit=limit,
            options="keyValues",
        )
    except Exception as e:
        logger.warning("Orion CropHealthZoneAssessment query failed: %s", e)
        return []
    finally:
        await client.close()


def _zone_geometry_lookup(zones: list) -> dict[str, dict]:
    """Map zoneId and zone URN to AgriParcelZone geometry metadata."""
    by_id: dict[str, dict] = {}
    for z in zones:
        entry = {
            "geometry": z.geometry,
            "sensorNearby": z.sensor_nearby,
        }
        by_id[z.zone_id] = entry
        if z.urn:
            by_id[z.urn] = entry
    return by_id


async def _map_zone_entities_with_geometry(
    tenant_id: str,
    entities: list[dict],
) -> tuple[list[dict], bool]:
    """Attach AgriParcelZone geometry to zone assessment entities."""
    if not entities:
        return [], False

    parcel_ids = sorted({extract_parcel_id(e) for e in entities if extract_parcel_id(e)})
    lookup: dict[str, dict] = {}
    whole_by_parcel: dict[str, bool] = {}

    for pid in parcel_ids:
        zones = await resolve_zones(f"urn:ngsi-ld:AgriParcel:{pid}", tenant_id, {})
        whole_by_parcel[pid] = is_whole_parcel(zones)
        lookup.update(_zone_geometry_lookup(zones))

    mapped: list[dict] = []
    for entity in entities:
        pid = extract_parcel_id(entity)
        zid = extract_zone_id(entity)
        zurn = extract_zone_urn(entity)
        meta = lookup.get(zurn) or lookup.get(zid) or {}
        mapped.append(
            map_entity_to_zone_assessment(
                entity,
                geometry=meta.get("geometry"),
                sensor_nearby=meta.get("sensorNearby"),
            )
        )

    is_whole = len(parcel_ids) == 1 and whole_by_parcel.get(parcel_ids[0], True)
    return mapped, is_whole


async def _parcel_values(tenant_id: str, parcel_id: str) -> dict:
    """Four headline values of the parcel's latest assessment ({} if none)."""
    entities = await _fetch_assessment_entities(tenant_id, parcel_id=parcel_id, limit=100)
    if not entities:
        return {}
    latest = map_entity_to_assessment(max(entities, key=lambda e: prop_value(e, "assessedAt", "")))
    return {k: latest.get(k) for k in PARCEL_VALUE_KEYS}


def _live_zone_assessments(entities: list[dict], live: list, parcel_values: dict) -> list[dict]:
    """Latest assessment per live zone, mapped and flagged against the parcel.

    Assessments of zones not in ``live`` are dropped before deduplicating.
    """
    live_keys = {z.zone_id for z in live} | {z.urn for z in live if z.urn}
    kept = [
        e for e in entities
        if extract_zone_id(e) in live_keys or extract_zone_urn(e) in live_keys
    ]
    lookup = _zone_geometry_lookup(live)
    zones: list[dict] = []
    for entity in dedupe_latest_per_zone(kept):
        meta = lookup.get(extract_zone_urn(entity)) or lookup.get(extract_zone_id(entity)) or {}
        zone = map_entity_to_zone_assessment(
            entity,
            geometry=meta.get("geometry"),
            sensor_nearby=meta.get("sensorNearby"),
        )
        zone["differsFromParcel"] = differs_from_parcel(zone, parcel_values)
        zones.append(zone)
    return zones


@router.get("/assessments/zones/all")
async def all_zone_assessments(request: Request):
    """Latest assessment per live zone of every parcel — map-layer compat."""
    tenant_id = getattr(request.state, "tenant_id", "")
    entities = await _fetch_zone_assessment_entities(tenant_id, limit=200)
    by_parcel: dict[str, list[dict]] = {}
    for e in entities:
        pid = extract_parcel_id(e)
        if pid:
            by_parcel.setdefault(pid, []).append(e)

    zones: list[dict] = []
    parcel_values: dict[str, dict] = {}
    for pid in sorted(by_parcel):
        live = await resolve_zones(f"urn:ngsi-ld:AgriParcel:{pid}", tenant_id, {})
        values = await _parcel_values(tenant_id, pid)
        parcel_values[pid] = values
        if is_whole_parcel(live):
            continue
        zones.extend(_live_zone_assessments(by_parcel[pid], live, values))
    zones.sort(key=lambda z: (z.get("parcelId", ""), z.get("zoneId", "")))
    return {"zones": zones, "parcelValues": parcel_values}


@router.get("/assessments/zones")
async def zone_assessments(
    request: Request,
    parcelId: str = Query("", alias="parcelId"),
):
    """Latest zone assessment per live management zone, flagged against the parcel.

    Assessments of zones that no longer exist are dropped before deduplicating.
    """
    if not parcelId:
        return {"zones": [], "isWholeParcel": True, "parcelValues": {}}

    tenant_id = getattr(request.state, "tenant_id", "")
    live = await resolve_zones(f"urn:ngsi-ld:AgriParcel:{parcelId}", tenant_id, {})

    parcel_values = await _parcel_values(tenant_id, parcelId)

    if is_whole_parcel(live):
        return {"zones": [], "isWholeParcel": True, "parcelValues": parcel_values}

    entities = await _fetch_zone_assessment_entities(tenant_id, parcel_id=parcelId, limit=100)
    zones = _live_zone_assessments(entities, live, parcel_values)
    zones.sort(key=lambda z: z.get("zoneId", ""))
    return {"zones": zones, "isWholeParcel": not zones, "parcelValues": parcel_values}


def _linear_regression_stats(pairs: list[dict]) -> dict:
    valid = [
        (float(p["ndvi"]), float(p["cwsi"]))
        for p in pairs
        if p.get("ndvi") is not None and p.get("cwsi") is not None
    ]
    n = len(valid)
    if n < 3:
        return {"n": n, "r2": None, "slope": None, "intercept": None}

    xs = [x for x, _ in valid]
    ys = [y for _, y in valid]
    mean_x = sum(xs) / n
    mean_y = sum(ys) / n
    ss_xx = sum((x - mean_x) ** 2 for x in xs)
    if ss_xx == 0:
        return {"n": n, "r2": None, "slope": None, "intercept": None}

    ss_xy = sum((x - mean_x) * (y - mean_y) for x, y in valid)
    slope = ss_xy / ss_xx
    intercept = mean_y - slope * mean_x

    ss_tot = sum((y - mean_y) ** 2 for y in ys)
    ss_res = sum((y - (slope * x + intercept)) ** 2 for x, y in valid)
    r2 = 1 - (ss_res / ss_tot) if ss_tot else None
    if r2 is not None and r2 < 0:
        r2 = 0.0

    return {
        "n": n,
        "r2": round(r2, 3) if r2 is not None else None,
        "slope": round(slope, 4),
        "intercept": round(intercept, 4),
    }


async def _latest_worklist(request: Request, tenant_id: str, parcel_id: str,
                           entity: dict, mapped: dict) -> dict:
    """Work-list fields for the single-parcel answer; never raises."""
    try:
        from app.services.worklist_sources import gather_parcel_inputs  # lazy: avoids an import cycle

        inputs, alerts = await asyncio.gather(
            gather_parcel_inputs(request, get_redis_state(), tenant_id, parcel_id, with_history=True),
            _alerts_safe(tenant_id),
        )
        fields = _worklist_fields(
            assessment=_flat(entity), assessed_at=mapped.get("assessedAt"),
            crop_name=mapped.get("cropName"), inputs=inputs,
            alerts=[a for a in alerts if a.get("parcelId") == parcel_id],
            now=datetime.now(timezone.utc),
        )
        fields.pop("lastAssessment")
        return fields
    except Exception as exc:  # noqa: BLE001
        logger.warning("worklist: latest fields failed tenant=%s parcel=%s: %s", tenant_id, parcel_id, exc)
        return {}


@router.get("/assessments/latest")
async def latest_assessments(
    request: Request,
    parcelId: str = Query("", alias="parcelId"),
):
    """Return the latest CropHealthAssessment per parcel, or for one parcel if filtered."""
    tenant_id = getattr(request.state, "tenant_id", "")
    entities = await _fetch_assessment_entities(tenant_id, parcel_id=parcelId, limit=100 if parcelId else 100)

    extra: dict = {}
    if parcelId:
        if not entities:
            return {"assessments": []}
        latest = max(entities, key=lambda e: prop_value(e, "assessedAt", ""))
        assessments = [map_entity_to_assessment(latest)]
        extra = await _latest_worklist(request, tenant_id, parcelId, latest, assessments[0])
    else:
        latest_entities = dedupe_latest_per_parcel(entities)
        assessments = [map_entity_to_assessment(e) for e in latest_entities]
        assessments.sort(key=lambda a: a.get("assessedAt", ""), reverse=True)

    # Resolve human-readable parcel names (AgriParcel.name) so widgets label
    # parcels instead of falling back to the bare UUID.
    parcel_names = await _fetch_parcel_names(tenant_id)
    for a in assessments:
        pid = a.get("parcelId")
        if pid and pid in parcel_names:
            a["parcelName"] = parcel_names[pid]

    return {"assessments": assessments, **extra}


@router.get("/assessments/all")
async def all_assessments(request: Request):
    """Alias for latest assessments without parcel filter (map-layer compat)."""
    return await latest_assessments(request, parcelId="")


async def _history_points(
    request: Request,
    parcel_id: str,
    days: int,
    from_: date | None = None,
    to: date | None = None,
) -> list[dict]:
    """CropHealthAssessment series for a parcel, oldest first; [] on any failure."""
    try:
        settings = get_settings()
        start = from_ or (datetime.now(timezone.utc).date() - timedelta(days=days))
        params = {
            "attrs": "cwsiValue,mdsValue,waterBalanceDeficit,compositeStressIndex,overallSeverity",
            "limit": 500,
            "from": f"{start.isoformat()}T00:00:00Z",
        }
        if to is not None:
            # Reader's upper bound is exclusive: close the day so `to` is inclusive.
            params["to"] = f"{to.isoformat()}T23:59:59.999999Z"
        url = f"{settings.weather_api_url}/api/timeseries/type/CropHealthAssessment/parcel/{parcel_id}/data"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url, params=params, headers=_reader_headers(request))
            resp.raise_for_status()
            result = resp.json()

        points = [
            {
                "date": p.get("observed_at", ""),
                "cwsi": p.get("cwsiValue"),
                "mds": p.get("mdsValue"),
                "balance": p.get("waterBalanceDeficit"),
                "composite": p.get("compositeStressIndex"),
                "severity": p.get("overallSeverity"),
            }
            for p in result.get("data", [])
        ]
        points.sort(key=lambda p: p["date"])
        return points
    except httpx.HTTPStatusError as e:
        logger.error(
            "History query failed: timeseries-reader returned HTTP %s (parcel=%s)",
            e.response.status_code,
            parcel_id,
        )
        return []
    except Exception as e:
        logger.error("History query failed: %s", e)
        return []


@router.get("/assessments/history")
async def assessment_history(
    request: Request,
    parcelId: str = "",
    days: int = 7,
    from_: date | None = Query(None, alias="from"),
    to: date | None = None,
):
    """Return CWSI/MDS/water balance/composite time series for a parcel, oldest first.

    Range: ``from``/``to`` (UTC dates, ``to`` inclusive). Without ``from`` it is
    ``today - days``; without ``to`` the reader's default (now) applies.
    Queries timeseries-reader (no direct DB access), forwarding the caller's auth.
    """
    if not parcelId:
        return {"points": []}
    return {"points": await _history_points(request, parcelId, days, from_=from_, to=to)}


@router.get("/assessments/correlation")
async def ndvi_cwsi_correlation(
    request: Request,
    parcelId: str = "",
    days: int = 30,
):
    """Return paired NDVI/CWSI data points for correlation analysis.

    Queries EOProduct (canonical NDVI) from Orion-LD and CropHealthAssessment
    from telemetry_events, aligns by date.
    """
    if not parcelId:
        return {"pairs": []}

    pairs = []
    try:
        # Query VegetationIndex from Orion-LD
        tenant_id = getattr(request.state, "tenant_id", "")
        settings = get_settings()
        client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
        try:
            vi_data = await client.query_entities(
                type="EOProduct",
                q=f'hasAgriParcel=="urn:ngsi-ld:AgriParcel:{parcelId}"|refAgriParcel=="urn:ngsi-ld:AgriParcel:{parcelId}"',
                limit=30,
                options="keyValues",
            )
        except Exception as e:
            logger.warning("ndvi_cwsi_correlation Orion query failed: %s", e)
            vi_data = []
        finally:
            # Ensure OrionClient is always closed
            await client.close()

        # Query CropHealthAssessment from timeseries-reader (no direct DB)
        settings = get_settings()
        url = (
            f"{settings.weather_api_url}/api/timeseries/type/CropHealthAssessment"
            f"/parcel/{parcelId}/data"
            f"?attrs=cwsiValue&limit=500"
        )
        cwsi_by_date = {}
        async with httpx.AsyncClient(timeout=10.0) as http_client:
            resp = await http_client.get(url, headers=_reader_headers(request))
            resp.raise_for_status()
            result = resp.json()
            for p in result.get("data", []):
                date_str = str(p.get("observed_at", ""))[:10]
                cwsi_val = p.get("cwsiValue")
                if date_str and cwsi_val is not None:
                    cwsi_by_date[date_str] = float(cwsi_val)

            # Align satellite and ground data (EOProduct: ndvi Property + sensingDate)
            for vi in vi_data:
                if vi.get("ndvi") is None:
                    continue  # skip non-optical EOProducts (e.g. SAR/GRD)
                date_str = str(vi.get("sensingDate", ""))[:10]
                ndvi_val = vi.get("ndvi")
                if isinstance(ndvi_val, dict):
                    ndvi_val = ndvi_val.get("value")
                cwsi_val = cwsi_by_date.get(date_str)
                pairs.append({
                    "date": date_str,
                    "ndvi": float(ndvi_val) if ndvi_val else None,
                    "cwsi": cwsi_val,
                })

    except Exception as e:
        logger.error("Correlation query failed: %s", e)

    stats = _linear_regression_stats(pairs)
    return {"pairs": pairs, "stats": stats}


@router.get("/assessments/export")
async def export_assessments(
    request: Request,
    parcelId: str = "",
    days: int = 30,
    format: str = "csv",
):
    """Export crop health indicators as CSV with source metadata and dataFidelity.

    Returns a CSV file with columns:
    date, cwsiValue, mdsValue, waterBalanceDeficit, vigorIndex,
    compositeStressIndex, yieldUtilizationPct, overallSeverity,
    recommendedAction, phenologySource, dataFidelity
    """
    import csv
    import io

    from fastapi.responses import StreamingResponse

    tenant_id = getattr(request.state, "tenant_id", "")
    settings = get_settings()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow([
        "date", "cwsiValue", "mdsValue", "mdsSeverity", "vpdKpa",
        "waterBalanceDeficit_mm", "vigorIndex", "vigorCondition",
        "compositeStressIndex", "dominantStressor",
        "yieldUtilizationPct", "yieldGapConfidence",
        "thermalCondition", "thermalSeverity",
        "overallSeverity", "recommendedAction",
        "phenologySource", "dataFidelity",
    ])

    try:
        q = f'(hasAgriParcel=="urn:ngsi-ld:AgriParcel:{parcelId}"|refAgriParcel=="urn:ngsi-ld:AgriParcel:{parcelId}")' if parcelId else None
        client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
        try:
            entities = await client.query_entities(type="CropHealthAssessment", q=q, limit=100, options="keyValues")
        except Exception as e:
            logger.warning("export_assessments Orion query failed: %s", e)
            entities = []
        finally:
            await client.close()

        for e in entities:
            writer.writerow([
                e.get("assessedAt", ""),
                e.get("cwsiValue", ""),
                e.get("mdsValue", ""),
                e.get("mdsSeverity", ""),
                e.get("vpdKpa", ""),
                e.get("waterBalanceDeficit", ""),
                e.get("vigorIndex", ""),
                e.get("vigorCondition", ""),
                e.get("compositeStressIndex", ""),
                e.get("dominantStressor", ""),
                e.get("yieldUtilizationPct", ""),
                e.get("yieldGapConfidence", ""),
                e.get("thermalCondition", ""),
                e.get("thermalSeverity", ""),
                e.get("overallSeverity", ""),
                e.get("recommendedAction", ""),
                e.get("phenologySource", ""),
                e.get("dataFidelity", ""),
            ])
    except Exception as e:
        logger.error("Export failed: %s", e)
        output.write(f"Error: {e}\n")

    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=crop-health-export-{parcelId or 'all'}.csv"},
    )


@router.get("/parcels")
async def list_parcels(request: Request):
    """Return lightweight list of all tenant parcels with latest crop health status.

    Queries Orion-LD for CropHealthAssessment entities (grouped by parcel,
    latest per parcel) and AgriParcel entities (for name and area).
    Parcels without assessments appear with hasData=false.
    """
    tenant_id = getattr(request.state, "tenant_id", "")
    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)

    try:
        # Query 1: CropHealthAssessment entities
        try:
            assessments_raw = await client.query_entities(
                type="CropHealthAssessment",
                limit=100,
                options="keyValues",
            )
        except Exception as e:
            logger.warning("list_parcels CropHealthAssessment query failed: %s", e)
            assessments_raw = []

        # Query 2: AgriParcel entities
        try:
            parcels_raw = await client.query_entities(
                type="AgriParcel",
                limit=100,
                options="keyValues",
            )
        except Exception as e:
            logger.warning("list_parcels AgriParcel query failed: %s", e)
            parcels_raw = []
    except Exception as e:
        logger.error("Failed to query Orion-LD for parcels: %s", e)
        return {"parcels": []}
    finally:
        await client.close()

    # Build assessment lookup by parcel ID (keep latest per parcel)
    assessment_by_parcel: dict[str, dict] = {}
    for e in assessments_raw:
        parcel = ""
        ref = e.get("hasAgriParcel")
        if isinstance(ref, dict):
            parcel = ref.get("object", "").replace("urn:ngsi-ld:AgriParcel:", "")
        elif isinstance(ref, str):
            parcel = ref.replace("urn:ngsi-ld:AgriParcel:", "")
        if not parcel:
            continue
        existing = assessment_by_parcel.get(parcel)
        if existing is None or (e.get("assessedAt", "") > existing.get("assessedAt", "")):
            assessment_by_parcel[parcel] = e

    # Build parcel info lookup
    parcel_info: dict[str, dict] = {}
    for p in parcels_raw:
        pid = p.get("id", "").replace("urn:ngsi-ld:AgriParcel:", "")
        if not pid:
            continue
        parcel_info[pid] = p

    # Merge: parcels with assessments first, then parcels without
    parcels: list[dict] = []
    seen: set[str] = set()

    for pid, a in assessment_by_parcel.items():
        if pid not in parcel_info:
            continue  # ghost: assessment references a deleted/non-existent AgriParcel
        seen.add(pid)
        info = parcel_info[pid]
        name_val = info.get("name")
        if isinstance(name_val, dict):
            name_val = name_val.get("value")
        area_val = info.get("area")
        if isinstance(area_val, dict):
            area_val = area_val.get("value")
        parcels.append({
            "parcelId": pid,
            "parcelName": name_val or pid,
            "cropName": a.get("cropName") if not isinstance(a.get("cropName"), dict) else a.get("cropName", {}).get("value"),
            "phenologyStage": a.get("phenologyStage") if not isinstance(a.get("phenologyStage"), dict) else a.get("phenologyStage", {}).get("value"),
            "areaHa": area_val,
            "overallSeverity": a.get("overallSeverity", "LOW") if not isinstance(a.get("overallSeverity"), dict) else a.get("overallSeverity", {}).get("value", "LOW"),
            "cwsiValue": a.get("cwsiValue") if not isinstance(a.get("cwsiValue"), dict) else a.get("cwsiValue", {}).get("value"),
            "vigorIndex": a.get("vigorIndex") if not isinstance(a.get("vigorIndex"), dict) else a.get("vigorIndex", {}).get("value"),
            "assessedAt": a.get("assessedAt") if not isinstance(a.get("assessedAt"), dict) else a.get("assessedAt", {}).get("value"),
            "hasData": True,
        })

    for pid, info in parcel_info.items():
        if pid in seen:
            continue
        name_val = info.get("name")
        if isinstance(name_val, dict):
            name_val = name_val.get("value")
        parcels.append({
            "parcelId": pid,
            "parcelName": name_val or pid,
            "hasData": False,
        })

    # Work-list fields: inputs of every parcel gathered in parallel, alerts once per request.
    from app.services.worklist_sources import gather_parcel_inputs  # lazy: avoids an import cycle

    state = get_redis_state()
    now = datetime.now(timezone.utc)
    alerts, inputs_list = await asyncio.gather(
        _alerts_safe(tenant_id),
        asyncio.gather(*(
            gather_parcel_inputs(request, state, tenant_id, p["parcelId"], with_history=True)
            for p in parcels
        )),
    )
    for p, inputs in zip(parcels, inputs_list):
        p.update(_worklist_fields(
            assessment=_flat(assessment_by_parcel.get(p["parcelId"])),
            assessed_at=p.get("assessedAt"), crop_name=p.get("cropName"), inputs=inputs,
            alerts=[a for a in alerts if a.get("parcelId") == p["parcelId"]], now=now,
        ))

    parcels.sort(key=worklist.rank)
    summary = {
        "surprises": sum(1 for p in parcels if p["surprise"]),
        "jobsToday": sum(1 for p in parcels if (p["nextJob"] or {}).get("when") == "today"),
        "noData": sum(1 for p in parcels
                      if not p.get("hasData") or (p["nextJob"] or {}).get("kind") == "pending_assessment"),
    }
    return {"parcels": parcels, "summary": summary}


async def _active_alert_rows(tenant_id: str) -> list[dict]:
    """Active disease Alert rows of the tenant (unfiltered by parcel), each with its Alert id."""
    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        entities = await client.query_entities(type="Alert", limit=100, options="keyValues")
    except Exception as e:
        logger.warning("active_disease_risks Orion query failed: %s", e)
        entities = []
    finally:
        await client.close()

    risks = []
    for e in entities:
        if e.get("category") != "disease":
            continue

        status = e.get("status")
        if status and status != "active":
            continue

        parcel = ""
        ref = e.get("refEntity")
        if isinstance(ref, dict):
            parcel = str(ref.get("object", "")).replace("urn:ngsi-ld:AgriParcel:", "")
        elif isinstance(ref, str):
            parcel = ref.replace("urn:ngsi-ld:AgriParcel:", "")

        eval_data = e.get("evaluationData") or {}
        if isinstance(eval_data, dict) and "value" in eval_data:
            eval_data = eval_data["value"]
        if not isinstance(eval_data, dict):
            eval_data = {}

        confidence = e.get("confidence", "medium")
        if isinstance(confidence, (int, float)):
            confidence = "high" if confidence >= 0.9 else ("medium" if confidence >= 0.7 else "low")

        # `conditions` es un string en los modelos epidemiológicos, pero un
        # árbol de condiciones (list/dict) en los presets threshold. Coercer a
        # texto legible: si es árbol, usar los `factors` humanizables.
        conditions = eval_data.get("conditions", "")
        if isinstance(conditions, (list, dict)):
            factors = eval_data.get("factors")
            conditions = "; ".join(str(f) for f in factors) if isinstance(factors, list) else ""

        risks.append({
            "disease": eval_data.get("disease") or str(e.get("alertType") or "unknown"),
            "crop": eval_data.get("crop", ""),
            "risk_level": str(e.get("severity") or "LOW").upper(),
            "conditions": conditions if isinstance(conditions, str) else "",
            "lwd_method": eval_data.get("lwd_method", ""),
            "confidence": confidence,
            "source_model": eval_data.get("source_model", ""),
            "recommended_action": eval_data.get("recommended_action", ""),
            "parcelId": parcel,
            "id": e.get("id"),
        })

    return risks


@router.get("/diseases/active")
async def active_disease_risks(
    request: Request,
    parcelId: str = "",
):
    """Return active disease risks from Orion-LD.

    Disease risks are published by the risk module as Alert entities with
    category = disease. The disease metadata (code, crop, conditions, model,
    action) lives in evaluationData. The legacy DiseaseRiskAssessment type is
    no longer written.

    Optionally filter by parcelId (refEntity relationship).
    """
    tenant_id = getattr(request.state, "tenant_id", "")
    risks = await _active_alert_rows(tenant_id)
    if parcelId:
        risks = [r for r in risks if r["parcelId"] == parcelId]
    return {"risks": risks}
