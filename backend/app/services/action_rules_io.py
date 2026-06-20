"""IO for the action-rules worker: read plan from Orion, rules from BioOrch."""
import logging
import uuid
from datetime import timedelta
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


def _render(template: str, ctx: dict) -> str:
    out = template
    for top, sub in ctx.items():
        if isinstance(sub, dict):
            for k, v in sub.items():
                out = out.replace("{%s.%s}" % (top, k), str(v))
    return out


def build_operation_entity(parcel_id, seg, rule, ctx, tenant_id, today) -> dict:
    action = rule.get("action", {})
    window = int(action.get("window_days", 7))
    e = {
        "id": f"urn:ngsi-ld:AgriParcelOperation:{tenant_id}:{uuid.uuid4().hex[:12]}",
        "type": "AgriParcelOperation",
        "operationType": {"type": "Property", "value": action.get("operation_type")},
        "description": {"type": "Property", "value": _render(action.get("description_template", ""), ctx)},
        "status": {"type": "Property", "value": "issued"},
        "hasAgriParcel": {"type": "Relationship", "object": parcel_id},
        "plannedStartDate": {"type": "Property", "value": today.isoformat()},
        "plannedEndDate": {"type": "Property", "value": (today + timedelta(days=window)).isoformat()},
        "sourceRule": {"type": "Property", "value": rule.get("id")},
        "sourceRuleCategory": {"type": "Property", "value": rule.get("category")},
        "urgency": {"type": "Property", "value": action.get("urgency", "medium")},
        "dateCreated": {"type": "Property", "value": today.isoformat() + "T00:00:00Z"},
    }
    if seg.get("id"):
        e["hasAgriCrop"] = {"type": "Relationship", "object": seg["id"]}
    return e


async def _operation_exists(parcel_id, rule_id, today, tenant_id) -> bool:
    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        rows = await client.query_entities(
            type="AgriParcelOperation",
            q=f'hasAgriParcel=="{parcel_id}";sourceRule=="{rule_id}";dateCreated>="{today.isoformat()}T00:00:00Z"',
            limit=1, options="keyValues",
        )
        return bool(rows)
    except Exception as exc:  # noqa: BLE001 — fail-safe = skip create to avoid dup storms
        logger.warning("_operation_exists failed %s/%s: %s", parcel_id, rule_id, exc)
        return True
    finally:
        await client.close()


async def _create_operation(parcel_id, seg, rule, ctx, tenant_id, today) -> str | None:
    entity = build_operation_entity(parcel_id, seg, rule, ctx, tenant_id, today)
    settings = get_settings()
    client = OrionClient(tenant_id, base_url=settings.orion_ld_url, context_url=settings.orion_ld_context)
    try:
        result = await client.upsert_entities_batch([entity])
        errors = result.get("errors") or []
        if errors:
            logger.warning("_create_operation upsert errors %s rule=%s: %s", parcel_id, rule.get("id"), errors[:3])
            return None
        return entity["id"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("_create_operation failed %s rule=%s: %s", parcel_id, rule.get("id"), exc)
        return None
    finally:
        await client.close()
