"""
FIWARE Publisher — Upsert CropHealthAssessment entities to Orion-LD.
"""

from __future__ import annotations

import logging
import os
import re

import httpx

from app.config import get_settings
from app.schemas import CropHealthAssessment

logger = logging.getLogger(__name__)


def _make_headers(tenant_id: str) -> dict:
    """Build Orion-LD headers with normalized tenant ID."""
    normalized = tenant_id.lower().strip().replace("-", "_").replace(" ", "_")
    normalized = re.sub(r"[^a-z0-9_]", "", normalized)
    normalized = normalized.strip("_") or tenant_id

    headers = {
        "NGSILD-Tenant": normalized,
        "Fiware-Service": normalized,
        "Fiware-ServicePath": "/",
        "Accept": "application/ld+json",
    }
    ctx_url = os.getenv("CONTEXT_URL", "")
    if ctx_url:
        headers["Link"] = (
            f'<{ctx_url}>; rel="http://www.w3.org/ns/json-ld#context";'
            f' type="application/ld+json"'
        )
    return headers


async def publish_assessment(assessment: CropHealthAssessment, tenant_id: str = "") -> bool:
    """Upsert a CropHealthAssessment entity to Orion-LD."""
    settings = get_settings()
    entity = assessment.to_ngsi_ld()

    entity["@context"] = settings.orion_ld_context
    url = f"{settings.orion_ld_url}/ngsi-ld/v1/entityOperations/upsert"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            headers = _make_headers(tenant_id) if tenant_id else {}
            headers["Content-Type"] = "application/ld+json"
            resp = await client.post(url, json=[entity], headers=headers)

            if resp.status_code in (200, 201, 204):
                logger.info(
                    "Published CropHealthAssessment %s — %d",
                    entity["id"],
                    resp.status_code,
                )
                return True

            logger.warning(
                "Orion-LD upsert returned %d for %s: %s",
                resp.status_code,
                entity["id"],
                resp.text[:200],
            )
            return False

    except httpx.TimeoutException:
        logger.error("Orion-LD timeout publishing %s", entity["id"])
        return False
    except httpx.ConnectError:
        logger.error("Orion-LD unreachable at %s", settings.orion_ld_url)
        return False
    except Exception as exc:
        logger.error("Unexpected error publishing to Orion-LD: %s", exc)
        return False
