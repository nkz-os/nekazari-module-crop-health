"""
FIWARE Publisher — Upsert CropHealthAssessment entities to Orion-LD via the SDK.
"""

from __future__ import annotations

import logging

import httpx

from nkz_platform_sdk.orion import OrionClient

from app.config import get_settings
from app.schemas import CropHealthAssessment

logger = logging.getLogger(__name__)


async def publish_assessment(assessment: CropHealthAssessment, tenant_id: str = "") -> bool:
    """Upsert a CropHealthAssessment entity to Orion-LD (tenant sent AS-IS)."""
    if not tenant_id:
        logger.warning("publish_assessment called without tenant_id; skipping")
        return False

    settings = get_settings()
    entity = assessment.to_ngsi_ld()
    client = OrionClient(
        tenant_id,
        base_url=settings.orion_ld_url,
        context_url=settings.orion_ld_context,
    )
    try:
        result = await client.upsert_entities_batch([entity])
        if result["errors"]:
            logger.warning(
                "Orion-LD upsert errors for %s: %s", entity["id"], result["errors"][:3]
            )
            return False
        logger.info("Published CropHealthAssessment %s", entity["id"])
        return True
    except httpx.HTTPStatusError as exc:
        logger.error("Orion-LD upsert failed for %s: %s", entity["id"], exc)
        return False
    except (httpx.TimeoutException, httpx.ConnectError) as exc:
        logger.error("Orion-LD unreachable publishing %s: %s", entity["id"], exc)
        return False
    except Exception as exc:
        logger.error("Unexpected error publishing %s to Orion-LD: %s", entity["id"], exc)
        return False
    finally:
        await client.close()
