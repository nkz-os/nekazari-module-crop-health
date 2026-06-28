"""Assessments API — query CropHealthAssessment entities from Orion-LD."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Query, Request

from app.api.assessment_mapper import (
    dedupe_latest_per_parcel,
    map_entity_to_assessment,
    prop_value,
)
from app.config import get_settings
from nkz_platform_sdk.orion import OrionClient

router = APIRouter()

logger = logging.getLogger(__name__)


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
        return await client.query_entities(
            type="CropHealthAssessment",
            q=q,
            limit=limit,
            options="keyValues",
        )
    except Exception as e:
        logger.warning("Orion CropHealthAssessment query failed: %s", e)
        return []
    finally:
        await client.close()


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


@router.get("/assessments/latest")
async def latest_assessments(
    request: Request,
    parcelId: str = Query("", alias="parcelId"),
):
    """Return the latest CropHealthAssessment per parcel, or for one parcel if filtered."""
    tenant_id = getattr(request.state, "tenant_id", "")
    entities = await _fetch_assessment_entities(tenant_id, parcel_id=parcelId, limit=100 if parcelId else 100)

    if parcelId:
        if not entities:
            return {"assessments": []}
        latest = max(entities, key=lambda e: prop_value(e, "assessedAt", ""))
        return {"assessments": [map_entity_to_assessment(latest)]}

    latest_entities = dedupe_latest_per_parcel(entities)
    assessments = [map_entity_to_assessment(e) for e in latest_entities]
    assessments.sort(key=lambda a: a.get("assessedAt", ""), reverse=True)
    return {"assessments": assessments}


@router.get("/assessments/all")
async def all_assessments(request: Request):
    """Alias for latest assessments without parcel filter (map-layer compat)."""
    return await latest_assessments(request, parcelId="")


@router.get("/assessments/history")
async def assessment_history(
    request: Request,
    parcelId: str = "",
    days: int = 7,
):
    """Return CWSI/MDS/water balance time series for a parcel.

    Queries timeseries-reader (no direct DB access).
    """
    if not parcelId:
        return {"points": []}

    try:
        settings = get_settings()
        url = (
            f"{settings.weather_api_url}/api/timeseries/type/CropHealthAssessment"
            f"/parcel/{parcelId}/data"
            f"?attrs=cwsiValue,mdsValue,waterBalanceDeficit"
            f"&limit=500"
        )
        import httpx
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            result = resp.json()

        points = [
            {
                "date": p.get("observed_at", ""),
                "cwsi": p.get("cwsiValue"),
                "mds": p.get("mdsValue"),
                "balance": p.get("waterBalanceDeficit"),
            }
            for p in result.get("data", [])
        ]
        points.sort(key=lambda p: p["date"])
        return {"points": points}
    except Exception as e:
        logger.error("History query failed: %s", e)
        return {"points": []}


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
        import httpx as _httpx
        cwsi_by_date = {}
        async with _httpx.AsyncClient(timeout=10.0) as http_client:
            resp = await http_client.get(url)
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

    # Sort: parcels with data first (by severity priority), then without data
    severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3}
    parcels.sort(key=lambda p: (
        0 if p.get("hasData") else 1,
        severity_order.get(p.get("overallSeverity", "LOW"), 3),
    ))

    return {"parcels": parcels}


@router.get("/diseases/active")
async def active_disease_risks(
    request: Request,
    parcelId: str = "",
):
    """Return active disease risks from Orion-LD DiseaseRiskAssessment entities.

    Optionally filter by parcelId (hasAgriParcel relationship).
    """
    tenant_id = getattr(request.state, "tenant_id", "")
    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        entities = await client.query_entities(type="DiseaseRiskAssessment", limit=50, options="keyValues")
    except Exception as e:
        logger.warning("active_disease_risks Orion query failed: %s", e)
        entities = []
    finally:
        await client.close()

    risks = []
    for e in entities:
        parcel = ""
        if isinstance(e.get("hasAgriParcel"), dict):
            parcel = e["hasAgriParcel"].get("object", "").replace("urn:ngsi-ld:AgriParcel:", "")
        elif isinstance(e.get("hasAgriParcel"), str):
            parcel = e["hasAgriParcel"].replace("urn:ngsi-ld:AgriParcel:", "")

        if parcelId and parcel != parcelId:
            continue

        risks.append({
            "disease": e.get("disease", "unknown"),
            "crop": e.get("crop", ""),
            "risk_level": e.get("riskLevel", "LOW"),
            "conditions": e.get("conditions", ""),
            "lwd_method": e.get("lwdMethod", ""),
            "confidence": e.get("confidence", "medium"),
            "source_model": e.get("sourceModel", ""),
            "recommended_action": e.get("recommendedAction", ""),
            "parcelId": parcel,
        })

    return {"risks": risks}
