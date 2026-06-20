"""IO for the action-rules worker: read plan from Orion, rules from BioOrch."""
import logging
import httpx
from nkz_platform_sdk.orion import OrionClient
from app.config import get_settings

logger = logging.getLogger(__name__)


async def _read_crop_plan(parcel_id: str, tenant_id: str) -> list[dict]:
    client = OrionClient(tenant_id)
    try:
        return await client.query_entities(
            type="AgriCrop", q=f'hasAgriParcel=="{parcel_id}"', limit=50, options="keyValues"
        ) or []
    except Exception as exc:  # noqa: BLE001 — fail-safe
        logger.warning("_read_crop_plan failed for %s: %s", parcel_id, exc)
        return []
    finally:
        await client.close()


async def _find_active_parcels(tenant_id: str) -> list[str]:
    client = OrionClient(tenant_id)
    try:
        rows = await client.query_entities(
            type="AgriCrop", q='status=="planned"|status=="active"', limit=2000, options="keyValues"
        ) or []
    except Exception as exc:  # noqa: BLE001
        logger.warning("_find_active_parcels failed tenant=%s: %s", tenant_id, exc)
        rows = []
    finally:
        await client.close()
    parcels = set()
    for r in rows:
        ref = r.get("hasAgriParcel")
        if isinstance(ref, str):
            parcels.add(ref)
    return list(parcels)


async def get_action_rules(species, stage, role, tenant_id) -> list[dict]:
    settings = get_settings()
    base = getattr(settings, "bioorchestrator_url", "") or "http://bioorchestrator-api-service:8420"
    params = {k: v for k, v in {"species": species, "stage": stage, "role": role}.items() if v}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(f"{base}/api/graph/action-rules", params=params,
                                    headers={"X-Tenant-ID": tenant_id, "X-User-ID": "crop-health-worker"})
            if resp.status_code == 200:
                return resp.json() or []
    except Exception as exc:  # noqa: BLE001 — fail-safe
        logger.warning("get_action_rules failed: %s", exc)
    return []
