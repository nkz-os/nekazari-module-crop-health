"""
FIWARE Publisher — Upsert CropHealthAssessment entities to Orion-LD.

Handles:
- POST (create) or PATCH (update) for idempotent entity upsert
- NGSI-LD @context and Link header management
- Proper content-type handling per NGSI-LD spec
"""

from __future__ import annotations

import logging

import httpx

from app.config import get_settings
from app.schemas import CropHealthAssessment

logger = logging.getLogger(__name__)


async def publish_assessment(assessment: CropHealthAssessment) -> bool:
    """Upsert a CropHealthAssessment entity to Orion-LD.

    Uses POST /ngsi-ld/v1/entityOperations/upsert for atomic create-or-update.

    Args:
        assessment: The assessment to publish.

    Returns:
        True if published successfully, False otherwise.
    """
    settings = get_settings()
    entity = assessment.to_ngsi_ld()

    # Use application/ld+json with inline @context (no Link header per spec)
    entity["@context"] = settings.orion_ld_context
    url = f"{settings.orion_ld_url}/ngsi-ld/v1/entityOperations/upsert"

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                url,
                json=[entity],
                headers={
                    "Content-Type": "application/ld+json",
                    "Accept": "application/ld+json",
                },
            )

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
