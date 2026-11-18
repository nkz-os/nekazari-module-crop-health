"""Read-only access to a parcel and its crop cycles through the platform SDK."""

from __future__ import annotations

import logging

from nkz_platform_sdk.crop_cycles import resolve_crop_cycles
from nkz_platform_sdk.crop_timeline import CropDataUnavailable, load_crop_data, local_today
from nkz_platform_sdk.orion import OrionClient

from app.config import get_settings

logger = logging.getLogger(__name__)


async def load_parcel_cycles(tenant_id: str, parcel_urn: str) -> tuple[dict, list[dict]] | None:
    """(parcel, crop cycles) for the tenant's parcel, or None when the broker data is unavailable."""
    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        parcel, crops, ops = await load_crop_data(client, parcel_urn)
        cycles = resolve_crop_cycles(parcel_urn, crops, ops, local_today(parcel)).to_dict()["cycles"]
        return parcel, cycles
    except CropDataUnavailable as exc:
        logger.warning("harvest source unavailable tenant=%s parcel=%s: %s", tenant_id, parcel_urn, exc)
        return None
    except Exception:  # noqa: BLE001 -- a read endpoint still lists its rows when the cycles cannot be resolved
        logger.exception("harvest source failed tenant=%s parcel=%s", tenant_id, parcel_urn)
        return None
    finally:
        await client.close()
