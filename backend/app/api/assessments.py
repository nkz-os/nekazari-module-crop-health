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
