"""Assessments API — query CropHealthAssessment entities from Orion-LD."""

from __future__ import annotations

import logging
import os

import httpx
from fastapi import APIRouter, Request

router = APIRouter()

logger = logging.getLogger(__name__)

ORION_URL = os.getenv("ORION_LD_URL", "http://orion-ld-service:1026")
CONTEXT_URL = os.getenv(
    "ORION_LD_CONTEXT",
    "https://uri.etsi.org/ngsi-ld/v1/ngsi-ld-core-context-v1.6.jsonld",
)


@router.get("/assessments/latest")
async def latest_assessments(request: Request):
    """Return the latest CropHealthAssessment per parcel.

    Queries Orion-LD for CropHealthAssessment entities ordered by
    assessedAt descending, grouped by parcel.
    """
    tenant_id = getattr(request.state, "tenant_id", "")
    headers = {
        "Accept": "application/ld+json",
        "Link": f"<{CONTEXT_URL}>; rel=\"http://www.w3.org/ns/json-ld#context\"; type=\"application/ld+json\"",
    }
    if tenant_id:
        headers["NGSILD-Tenant"] = tenant_id

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(
                f"{ORION_URL}/ngsi-ld/v1/entities",
                params={
                    "type": "CropHealthAssessment",
                    "limit": 10,
                    "options": "keyValues",
                },
                headers=headers,
            )
            if resp.status_code != 200:
                logger.warning("Orion-LD returned %d for assessments query", resp.status_code)
                return {"assessments": []}

            entities = resp.json()
            assessments = []
            for e in entities:
                parcel = ""
                if isinstance(e.get("refAgriParcel"), dict):
                    parcel = e["refAgriParcel"].get("object", "").replace("urn:ngsi-ld:AgriParcel:", "")
                assessments.append({
                    "id": e.get("id", ""),
                    "parcelId": parcel,
                    "cwsiValue": e.get("cwsiValue", {}).get("value") if isinstance(e.get("cwsiValue"), dict) else e.get("cwsiValue"),
                    "mdsValue": e.get("mdsValue", {}).get("value") if isinstance(e.get("mdsValue"), dict) else e.get("mdsValue"),
                    "mdsSeverity": e.get("mdsSeverity", {}).get("value") if isinstance(e.get("mdsSeverity"), dict) else e.get("mdsSeverity"),
                    "waterBalanceDeficit": e.get("waterBalanceDeficit", {}).get("value") if isinstance(e.get("waterBalanceDeficit"), dict) else e.get("waterBalanceDeficit"),
                    "overallSeverity": e.get("overallSeverity", {}).get("value") if isinstance(e.get("overallSeverity"), dict) else e.get("overallSeverity", "LOW"),
                    "recommendedAction": e.get("recommendedAction", {}).get("value") if isinstance(e.get("recommendedAction"), dict) else e.get("recommendedAction", "NO_ACTION"),
                    "assessedAt": e.get("assessedAt", {}).get("value") if isinstance(e.get("assessedAt"), dict) else e.get("assessedAt", ""),
                    "phenologySource": e.get("phenologySource", {}).get("value") if isinstance(e.get("phenologySource"), dict) else e.get("phenologySource", "default"),
                })

            return {"assessments": assessments}

    except Exception as e:
        logger.error("Failed to query Orion-LD for assessments: %s", e)
        return {"assessments": []}


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
        weather_db = os.getenv("WEATHER_DB_URL", "")
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
        headers = {"Accept": "application/ld+json"}
        if tenant_id:
            headers["NGSILD-Tenant"] = tenant_id

        async with httpx.AsyncClient(timeout=15.0) as client:
            vi_resp = await client.get(
                f"{ORION_URL}/ngsi-ld/v1/entities",
                params={
                    "type": "VegetationIndex",
                    "q": f'refAgriParcel=="urn:ngsi-ld:AgriParcel:{parcelId}"',
                    "limit": 30,
                    "options": "keyValues",
                },
                headers=headers,
            )
            vi_data = vi_resp.json() if vi_resp.status_code == 200 else []

            # Query CropHealthAssessment from telemetry_events
            import asyncpg
            weather_db = os.getenv("WEATHER_DB_URL", "")
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

    # Query Orion-LD for historical assessments
    tenant_id = getattr(request.state, "tenant_id", "")
    headers = {"Accept": "application/ld+json"}
    if tenant_id:
        headers["NGSILD-Tenant"] = tenant_id

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
        async with httpx.AsyncClient(timeout=15.0) as client:
            params = {
                "type": "CropHealthAssessment",
                "limit": 100,
                "options": "keyValues",
            }
            if parcelId:
                params["q"] = f'refAgriParcel=="urn:ngsi-ld:AgriParcel:{parcelId}"'
            resp = await client.get(
                f"{ORION_URL}/ngsi-ld/v1/entities", params=params, headers=headers,
            )
            if resp.status_code == 200:
                entities = resp.json()
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
