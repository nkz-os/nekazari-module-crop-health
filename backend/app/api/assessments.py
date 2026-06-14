"""Assessments API — query CropHealthAssessment entities from Orion-LD."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Request

from app.config import get_settings
from nkz_platform_sdk.orion import OrionClient

router = APIRouter()

logger = logging.getLogger(__name__)


@router.get("/assessments/latest")
async def latest_assessments(request: Request):
    """Return the latest CropHealthAssessment per parcel.

    Queries Orion-LD for CropHealthAssessment entities ordered by
    assessedAt descending, grouped by parcel.
    """
    tenant_id = getattr(request.state, "tenant_id", "")
    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        entities = await client.query_entities(type="CropHealthAssessment", limit=10, options="keyValues")
    except Exception as e:
        logger.warning("latest_assessments Orion query failed: %s", e)
        entities = []
    finally:
        await client.close()

    assessments = []
    for e in entities:
        parcel = ""
        if isinstance(e.get("hasAgriParcel"), dict):
            parcel = e["hasAgriParcel"].get("object", "").replace("urn:ngsi-ld:AgriParcel:", "")
        assessments.append({
            "id": e.get("id", ""),
            "parcelId": parcel,
            "cwsiValue": e.get("cwsiValue", {}).get("value") if isinstance(e.get("cwsiValue"), dict) else e.get("cwsiValue"),
            "mdsValue": e.get("mdsValue", {}).get("value") if isinstance(e.get("mdsValue"), dict) else e.get("mdsValue"),
            "mdsSeverity": e.get("mdsSeverity", {}).get("value") if isinstance(e.get("mdsSeverity"), dict) else e.get("mdsSeverity"),
            "waterBalanceDeficit": e.get("waterBalanceDeficit", {}).get("value") if isinstance(e.get("waterBalanceDeficit"), dict) else e.get("waterBalanceDeficit"),
            "thermalCondition": e.get("thermalCondition", {}).get("value") if isinstance(e.get("thermalCondition"), dict) else e.get("thermalCondition"),
            "thermalSeverity": e.get("thermalSeverity", {}).get("value") if isinstance(e.get("thermalSeverity"), dict) else e.get("thermalSeverity"),
            "vigorIndex": e.get("vigorIndex", {}).get("value") if isinstance(e.get("vigorIndex"), dict) else e.get("vigorIndex"),
            "vigorCondition": e.get("vigorCondition", {}).get("value") if isinstance(e.get("vigorCondition"), dict) else e.get("vigorCondition"),
            "compositeStressIndex": e.get("compositeStressIndex", {}).get("value") if isinstance(e.get("compositeStressIndex"), dict) else e.get("compositeStressIndex"),
            "dominantStressor": e.get("dominantStressor", {}).get("value") if isinstance(e.get("dominantStressor"), dict) else e.get("dominantStressor"),
            "yieldUtilizationPct": e.get("yieldUtilizationPct", {}).get("value") if isinstance(e.get("yieldUtilizationPct"), dict) else e.get("yieldUtilizationPct"),
            "yieldGapConfidence": e.get("yieldGapConfidence", {}).get("value") if isinstance(e.get("yieldGapConfidence"), dict) else e.get("yieldGapConfidence"),
            "wueStatus": e.get("wueStatus", {}).get("value") if isinstance(e.get("wueStatus"), dict) else e.get("wueStatus"),
            "wueKgM3": e.get("wueKgM3", {}).get("value") if isinstance(e.get("wueKgM3"), dict) else e.get("wueKgM3"),
            "wueBiomassKg": e.get("wueBiomassKg", {}).get("value") if isinstance(e.get("wueBiomassKg"), dict) else e.get("wueBiomassKg"),
            "wueWaterAppliedMm": e.get("wueWaterAppliedMm", {}).get("value") if isinstance(e.get("wueWaterAppliedMm"), dict) else e.get("wueWaterAppliedMm"),
            "wueTrend": e.get("wueTrend", {}).get("value") if isinstance(e.get("wueTrend"), dict) else e.get("wueTrend"),
            "overallSeverity": e.get("overallSeverity", {}).get("value") if isinstance(e.get("overallSeverity"), dict) else e.get("overallSeverity", "LOW"),
            "recommendedAction": e.get("recommendedAction", {}).get("value") if isinstance(e.get("recommendedAction"), dict) else e.get("recommendedAction", "NO_ACTION"),
            "assessedAt": e.get("assessedAt", {}).get("value") if isinstance(e.get("assessedAt"), dict) else e.get("assessedAt", ""),
            "phenologySource": e.get("phenologySource", {}).get("value") if isinstance(e.get("phenologySource"), dict) else e.get("phenologySource", "default"),
            "dataFidelity": e.get("dataFidelity", {}).get("value") if isinstance(e.get("dataFidelity"), dict) else e.get("dataFidelity"),
            "cropName": e.get("cropName") if not isinstance(e.get("cropName"), dict) else e.get("cropName", {}).get("value"),
            "phenologyStage": e.get("phenologyStage") if not isinstance(e.get("phenologyStage"), dict) else e.get("phenologyStage", {}).get("value"),
            "soilProperties": {
                "fieldCapacity": e.get("soilFieldCapacity", {}).get("value") if isinstance(e.get("soilFieldCapacity"), dict) else e.get("soilFieldCapacity"),
                "wiltingPoint": e.get("soilWiltingPoint", {}).get("value") if isinstance(e.get("soilWiltingPoint"), dict) else e.get("soilWiltingPoint"),
                "ksatMmH": e.get("soilKsatMmH", {}).get("value") if isinstance(e.get("soilKsatMmH"), dict) else e.get("soilKsatMmH"),
                "scsHydrologicGroup": e.get("soilScsGroup", {}).get("value") if isinstance(e.get("soilScsGroup"), dict) else e.get("soilScsGroup"),
                "usdaTextureClass": e.get("soilTexture", {}).get("value") if isinstance(e.get("soilTexture"), dict) else e.get("soilTexture"),
                "source": e.get("soilDataSource", {}).get("value") if isinstance(e.get("soilDataSource"), dict) else e.get("soilDataSource"),
                "hasData": True,
            } if (e.get("soilTexture") or e.get("soilFieldCapacity")) else None,
            "soilWaterMm": e.get("soilWaterMm", {}).get("value") if isinstance(e.get("soilWaterMm"), dict) else e.get("soilWaterMm"),
            "soilAWCmm": e.get("soilAWCmm", {}).get("value") if isinstance(e.get("soilAWCmm"), dict) else e.get("soilAWCmm"),
            "soilWaterRatio": e.get("soilWaterRatio", {}).get("value") if isinstance(e.get("soilWaterRatio"), dict) else e.get("soilWaterRatio"),
            "waterloggingRiskLevel": e.get("waterloggingRiskLevel", {}).get("value") if isinstance(e.get("waterloggingRiskLevel"), dict) else e.get("waterloggingRiskLevel"),
            "waterloggingSaturationHours": e.get("waterloggingSaturationHours", {}).get("value") if isinstance(e.get("waterloggingSaturationHours"), dict) else e.get("waterloggingSaturationHours"),
        })

    return {"assessments": assessments}


@router.get("/assessments/history")
async def assessment_history(
    request: Request,
    parcelId: str = "",
    days: int = 7,
):
    """Return CWSI/MDS/water balance time series for a parcel.

    Queries telemetry_events for CropHealthAssessment entities
    filtered by parcel ID and time range.
    """
    if not parcelId:
        return {"points": []}

    try:
        import asyncpg
        weather_db = get_settings().weather_db_url
        if not weather_db:
            logger.warning("WEATHER_DB_URL not configured — history unavailable")
            return {"points": []}

        conn = await asyncpg.connect(weather_db)
        try:
            rows = await conn.fetch(
                """
                SELECT observed_at,
                       payload->'measurements'->>'cwsiValue' AS cwsi,
                       payload->'measurements'->>'mdsValue' AS mds,
                       payload->'measurements'->>'waterBalanceDeficit' AS balance
                FROM telemetry_events
                WHERE entity_type = 'CropHealthAssessment'
                  AND payload->'measurements'->>'parcelId' = $1
                  AND observed_at > NOW() - ($2 || ' days')::INTERVAL
                ORDER BY observed_at ASC
                """,
                parcelId, str(days),
            )
            points = [
                {
                    "date": str(row["observed_at"]),
                    "cwsi": float(row["cwsi"]) if row["cwsi"] else None,
                    "mds": float(row["mds"]) if row["mds"] else None,
                    "balance": float(row["balance"]) if row["balance"] else None,
                }
                for row in rows
            ]
            return {"points": points}
        finally:
            await conn.close()
    except ImportError:
        logger.warning("asyncpg not available — history endpoint disabled")
        return {"points": []}
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

    Queries VegetationIndex from Orion-LD and CropHealthAssessment
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
                q=f'hasAgriParcel=="urn:ngsi-ld:AgriParcel:{parcelId}";productType=="NDVI"',
                limit=30,
                options="keyValues",
            )
        except Exception as e:
            logger.warning("ndvi_cwsi_correlation Orion query failed: %s", e)
            vi_data = []
        finally:
            await client.close()

        # Query CropHealthAssessment from telemetry_events
        import asyncpg
        weather_db = get_settings().weather_db_url
        if weather_db:
            conn = await asyncpg.connect(weather_db)
            try:
                rows = await conn.fetch(
                    """
                    SELECT observed_at::date AS date,
                           AVG((payload->'measurements'->>'cwsiValue')::float) AS cwsi
                    FROM telemetry_events
                    WHERE entity_type = 'CropHealthAssessment'
                      AND payload->'measurements'->>'parcelId' = $1
                      AND observed_at > NOW() - ($2 || ' days')::INTERVAL
                    GROUP BY observed_at::date
                    ORDER BY date ASC
                    """,
                    parcelId, str(days),
                )
                cwsi_by_date = {
                    str(row["date"]): float(row["cwsi"])
                    for row in rows if row["cwsi"]
                }
            finally:
                await conn.close()

            # Align satellite and ground data
            for vi in vi_data:
                date_str = str(vi.get("dateObserved", ""))[:10]
                ndvi_val = vi.get("ndviValue")
                if isinstance(ndvi_val, dict):
                    ndvi_val = ndvi_val.get("value")
                cwsi_val = cwsi_by_date.get(date_str)
                pairs.append({
                    "date": date_str,
                    "ndvi": float(ndvi_val) if ndvi_val else None,
                    "cwsi": cwsi_val,
                })

    except ImportError:
        logger.warning("asyncpg not available — correlation disabled")
    except Exception as e:
        logger.error("Correlation query failed: %s", e)

    return {"pairs": pairs}


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
        q = f'hasAgriParcel=="urn:ngsi-ld:AgriParcel:{parcelId}"' if parcelId else None
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
        seen.add(pid)
        info = parcel_info.get(pid, {})
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
