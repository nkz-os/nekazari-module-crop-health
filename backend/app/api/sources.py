"""Sources endpoint — diagnostic dashboard for data source health per parcel."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Query, Request

from app.config import get_settings
from nkz_platform_sdk.orion import OrionClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sources", tags=["sources"])

# Cache for detail responses: key=parcelId, value=(timestamp, data)
_detail_cache: dict[str, tuple[float, dict]] = {}
_DETAIL_CACHE_TTL = 45  # seconds



def _freshness(iso_ts: str | None) -> str:
    if not iso_ts:
        return "none"
    try:
        dt = datetime.fromisoformat(iso_ts.replace("Z", "+00:00"))
        age_h = (datetime.now(timezone.utc) - dt).total_seconds() / 3600
        if age_h < 24:
            return "fresh"
        if age_h < 168:  # 7 days
            return "stale"
        return "none"
    except Exception:
        return "none"


def _health_indicator(
    sources_active: int,
    sources_total: int,
    has_iot: bool,
    freshest_hours: float | None,
) -> str:
    """Determine the health indicator color for a parcel."""
    if sources_active == 0:
        return "grey"
    if freshest_hours is not None and freshest_hours > 168:
        return "red"
    if has_iot and sources_active >= 3:
        return "green"
    if not has_iot and sources_active >= 3:
        return "blue"
    if sources_active >= 1:
        return "yellow"
    return "red"


# ── Public route (dispatches to list or detail) ──────────────────────────

@router.get("")
async def get_sources(request: Request, parcelId: str | None = Query(None)):
    """Get source health for all parcels or detail for one."""
    if parcelId:
        return await _detail_sources(request, parcelId)
    return await _list_sources(request)


# ── List (all parcels) ───────────────────────────────────────────────────

async def _list_sources(request: Request) -> dict:
    """Get health summary for all parcels.

    Derived from existing Orion-LD entities (CropHealthAssessment,
    DeviceMeasurement, AgriParcel) — no per-parcel external calls.
    """
    tenant_id = getattr(request.state, "tenant_id", "")
    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        try:
            assessments = await client.query_entities(type="CropHealthAssessment", limit=500, options="keyValues")
        except Exception as e:
            logger.warning("CropHealthAssessment query failed: %s", e)
            assessments = []
        try:
            parcels = await client.query_entities(type="AgriParcel", limit=500, options="keyValues")
        except Exception as e:
            logger.warning("AgriParcel query failed: %s", e)
            parcels = []
        try:
            iot_devices = await client.query_entities(type="DeviceMeasurement", limit=1000, options="keyValues")
        except Exception as e:
            logger.warning("DeviceMeasurement query failed: %s", e)
            iot_devices = []
    finally:
        await client.close()

    # Build parcel lookup
    parcel_map: dict[str, dict] = {}
    for p in parcels:
        pid = p.get("id", "").replace("urn:ngsi-ld:AgriParcel:", "")
        if pid:
            parcel_map[pid] = {
                "parcelId": pid,
                "parcelName": p.get("name", pid),
                "hasIot": False,
                "sourcesActive": 0,
                "sourcesDegraded": 0,
                "sourcesDown": 0,
                "healthIndicator": "grey",
            }

    # Count IoT devices per parcel
    iot_by_parcel: dict[str, int] = {}
    for d in iot_devices:
        ref_parcel = d.get("hasAgriParcel", "")
        if isinstance(ref_parcel, dict):
            ref_parcel = ref_parcel.get("object", "")
        pid = ref_parcel.replace("urn:ngsi-ld:AgriParcel:", "")
        if pid:
            iot_by_parcel[pid] = iot_by_parcel.get(pid, 0) + 1

    for pid, count in iot_by_parcel.items():
        if pid in parcel_map:
            parcel_map[pid]["hasIot"] = True
            parcel_map[pid]["sourcesActive"] += 1

    # Count assessments as active source
    now = datetime.now(timezone.utc)
    latest_per_parcel: dict[str, datetime] = {}
    for a in assessments:
        ref_p = a.get("hasAgriParcel", "")
        if isinstance(ref_p, dict):
            ref_p = ref_p.get("object", "")
        pid = ref_p.replace("urn:ngsi-ld:AgriParcel:", "")
        if not pid:
            continue

        ts_str = a.get("assessedAt", "")
        try:
            ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        except Exception:
            ts = now
        if pid not in latest_per_parcel or ts > latest_per_parcel[pid]:
            latest_per_parcel[pid] = ts

        if pid in parcel_map:
            fidelity = a.get("dataFidelity", "")
            if fidelity in ("onsite_calibrated", "onsite_uncalibrated"):
                parcel_map[pid]["sourcesActive"] += 1

    # Compute health indicators
    for pid, pdata in parcel_map.items():
        latest = latest_per_parcel.get(pid)
        if latest:
            freshest_h = (now - latest).total_seconds() / 3600
        else:
            freshest_h = None

        pdata["healthIndicator"] = _health_indicator(
            pdata["sourcesActive"], max(pdata["sourcesActive"] + 1, 1), pdata["hasIot"], freshest_h
        )
        pdata["lastCheckedAt"] = now.isoformat()

    return {"parcels": sorted(parcel_map.values(), key=lambda p: p["parcelName"])}


# ── Detail (single parcel) ───────────────────────────────────────────────

async def _detail_sources(request: Request, parcelId: str) -> dict:
    """Get detailed source status for a single parcel.

    Result is cached for 45s to prevent rate-limit abuse on external services.
    """
    # Check cache
    cached = _detail_cache.get(parcelId)
    if cached:
        ts, data = cached
        if (datetime.now(timezone.utc).timestamp() - ts) < _DETAIL_CACHE_TTL:
            return data

    tenant_id = getattr(request.state, "tenant_id", "")
    settings = get_settings()

    now = datetime.now(timezone.utc)
    parcel_urn = f"urn:ngsi-ld:AgriParcel:{parcelId}"

    async def _query(type_: str, q: str = "", limit: int = 1) -> list:
        orion = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
        try:
            result = await orion.query_entities(type=type_, q=q or None, limit=limit, options="keyValues")
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.warning("Source query failed for %s: %s", type_, e)
            return []
        finally:
            await orion.close()

    # Query all sources in parallel with dual relationship check (hasAgriParcel|refAgriParcel)
    rel_q = f'(hasAgriParcel=="{parcel_urn}"|refAgriParcel=="{parcel_urn}")'
    results = await asyncio.gather(
        _query("CropHealthAssessment", rel_q, 1),
        _query("DeviceMeasurement", rel_q, 20),
        _query("EOProduct", f'{rel_q};productType=="NDVI"', 1),
        _query("AgriCrop", rel_q, 1),
        _query("VegetationIndex", rel_q, 1),
        _query("WeatherObserved", f'locatedAt=="{parcel_urn}"', 1),
        return_exceptions=True,
    )

    assessments = results[0] if not isinstance(results[0], BaseException) else []
    iot_devices = results[1] if not isinstance(results[1], BaseException) else []
    veg_indices = results[2] if not isinstance(results[2], BaseException) else []
    agri_crops = results[3] if not isinstance(results[3], BaseException) else []
    vi_fallback = results[4] if not isinstance(results[4], BaseException) else []
    weather_obs = results[5] if not isinstance(results[5], BaseException) else []

    assessment = assessments[0] if assessments else {}

    # ── Soil ──────────────────────────────────────────────────────────
    soil_texture = assessment.get("soilTexture")
    soil_ph = assessment.get("soilPh")
    soil_awc = assessment.get("soilAWCmm")
    soil_fc = assessment.get("soilFieldCapacity")
    soil_wp = assessment.get("soilWiltingPoint")
    soil_source = assessment.get("soilDataSource", "unknown")

    soil_ok = soil_texture is not None
    soil = {
        "status": "ok" if soil_ok else "unavailable",
        "freshness": _freshness(assessment.get("assessedAt")),
        "lastDataAt": assessment.get("assessedAt"),
        "summary": f"{soil_texture or '?'} · pH {soil_ph or '?'} · AWC {soil_awc or '?'}mm",
        "details": {
            "texture": soil_texture,
            "fieldCapacity": soil_fc,
            "wiltingPoint": soil_wp,
            "awcMm": soil_awc,
            "ph": soil_ph,
            "organicCarbonPct": None,
            "source": soil_source,
        },
    }

    # ── IoT ───────────────────────────────────────────────────────────
    iot_sensors = []
    for d in iot_devices:
        for metric in ("leafTemperature", "trunkDiameter", "soilMoisture", "soilTemp", "soilPh", "soilEC"):
            val = d.get(metric)
            if val is not None:
                unit = "°C" if "Temp" in metric else "µm" if "trunk" in metric.lower() else "%" if "Moisture" in metric else ""
                iot_sensors.append({
                    "metric": metric,
                    "lastValue": val,
                    "lastTs": d.get("dateObserved", ""),
                    "unit": unit,
                })
    iot_ok = len(iot_sensors) > 0
    iot_freshness = "none"
    if iot_sensors:
        iot_freshness = _freshness(iot_sensors[0].get("lastTs"))

    iot = {
        "status": "ok" if iot_ok else "unavailable",
        "freshness": iot_freshness,
        "lastDataAt": iot_sensors[0]["lastTs"] if iot_sensors else None,
        "summary": f"{len(iot_sensors)} sensores activos" if iot_ok else "sin sensores",
        "sensors": iot_sensors,
    }

    # ── Weather ───────────────────────────────────────────────────────
    weather_parts = []
    weather_last_ts = None
    # Check WeatherObserved entity (SDM standard)
    if weather_obs:
        wo = weather_obs[0]
        temp = wo.get("temperature")
        if temp is not None:
            weather_parts.append(f"{temp}°C")
        et0 = wo.get("et0")
        if et0 is not None:
            weather_parts.append(f"ET0 {et0}mm")
        weather_last_ts = wo.get("dateObserved")
    # Fallback: CropHealthAssessment VPD
    if assessment.get("vpdKpa") is not None:
        weather_parts.append(f"VPD {assessment['vpdKpa']:.1f}kPa")
        if not weather_last_ts:
            weather_last_ts = assessment.get("assessedAt")
    weather_summary = " · ".join(weather_parts) if weather_parts else "sin datos"
    weather = {
        "status": "ok" if weather_parts else "unavailable",
        "freshness": _freshness(weather_last_ts),
        "lastDataAt": weather_last_ts,
        "summary": weather_summary,
        "details": {
            "vpdKpa": assessment.get("vpdKpa"),
        },
    }

    # ── Satellite ──────────────────────────────────────────────────────
    ndvi_val = None
    ndvi_ts = None
    # Primary: EOProduct with productType=NDVI
    if veg_indices:
        vi = veg_indices[0]
        ndvi_val = vi.get("ndviMean") or vi.get("ndviValue") or vi.get("value")
        ndvi_ts = vi.get("dateObserved") or vi.get("sensingDate")
    # Fallback: legacy VegetationIndex during migration window
    if ndvi_val is None and vi_fallback:
        fb = vi_fallback[0]
        ndvi_val = fb.get("ndviMean") or fb.get("ndviMax")
        ndvi_ts = fb.get("sensingDate")
    ndvi = {
        "status": "ok" if ndvi_val is not None else "unavailable",
        "freshness": _freshness(ndvi_ts) if isinstance(ndvi_ts, str) else "none",
        "lastDataAt": ndvi_ts if isinstance(ndvi_ts, str) else None,
        "lastValue": ndvi_val,
    }

    sar = {
        "status": "unavailable",
        "freshness": "none",
        "lastDataAt": None,
        "reason": "no_entity" if ndvi_val is not None else "no_parcel_data",
    }

    # ── Crop ───────────────────────────────────────────────────────────
    ac = agri_crops[0] if agri_crops else {}
    crop_ok = bool(ac.get("species") or ac.get("eppoCode"))
    phenology_stage = assessment.get("phenologyStage")
    crop = {
        "status": "ok" if crop_ok else "unavailable",
        "freshness": "fresh" if crop_ok else "none",
        "lastDataAt": ac.get("plantingDate"),
        "species": ac.get("species"),
        "eppoCode": ac.get("eppoCode"),
        "variety": ac.get("variety"),
        "plantingDate": ac.get("plantingDate"),
        "harvestDate": ac.get("harvestDate"),
        "phenologyStage": phenology_stage,
        "gddProgressPct": None,
        "source": "agri_crop" if crop_ok else "none",
    }

    # ── BioOrchestrator ────────────────────────────────────────────────
    phenology_source = assessment.get("phenologySource", "default")
    kc_val = assessment.get("kc")
    bio_ok = phenology_source != "default" or kc_val is not None
    bio = {
        "status": "ok" if bio_ok else "unavailable",
        "freshness": _freshness(assessment.get("assessedAt")),
        "lastDataAt": assessment.get("assessedAt"),
        "summary": f"Kc={kc_val}" if kc_val else "sin parámetros",
        "matchLevel": "SPECIES" if phenology_source == "bioorchestrator" else "NONE",
        "details": {
            "kc": kc_val,
            "d1": assessment.get("d1"),
            "d2": assessment.get("d2"),
            "ky": None,
            "mdsRef": None,
            "provenance": None,
        },
    }

    # ── Risks ──────────────────────────────────────────────────────────
    risks_alerts = []
    # Placeholder risk logic — expandable with real disease/thermal models
    risks = {
        "status": "advisory" if risks_alerts else "none",
        "alerts": risks_alerts,
    }

    response = {
        "parcelId": parcelId,
        "checkedAt": now.isoformat(),
        "sources": {
            "soil": soil,
            "iot": iot,
            "weather": weather,
            "satellite": {"ndvi": ndvi, "sar": sar},
            "crop": crop,
            "bioorchestrator": bio,
            "risks": risks,
        },
    }

    _detail_cache[parcelId] = (now.timestamp(), response)
    return response
