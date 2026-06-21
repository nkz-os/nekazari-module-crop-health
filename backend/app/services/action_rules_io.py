"""IO for the action-rules worker: read plan from Orion, rules from BioOrch."""
import logging
import uuid
from datetime import datetime, timedelta, timezone
import httpx
from nkz_platform_sdk.orion import OrionClient
from app.config import get_settings
from app.api.phenology import _read_latest_assessment, _build_status_from_dict
from app.services import context_client
from app.services.context_client import get_phenology_stages, get_soil_properties
from app.services.pipeline import _fetch_parcel_ndvi
from app.engines.action_rules import evaluate_conditions, build_context

logger = logging.getLogger(__name__)


async def _read_crop_plan(parcel_id: str, tenant_id: str) -> list[dict]:
    client = OrionClient(tenant_id)
    try:
        return await client.query_entities(
            type="AgriCrop", q=f'(hasAgriParcel=="{parcel_id}"|refAgriParcel=="{parcel_id}")', limit=50, options="keyValues"
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
            q=f'(hasAgriParcel=="{parcel_id}"|refAgriParcel=="{parcel_id}");sourceRule=="{rule_id}";dateCreated>="{today.isoformat()}T00:00:00Z"',
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


async def get_weather_snapshot(parcel_id: str, tenant_id: str = ""):
    """Worker-facing weather lookup: (parcel_id, tenant_id) -> WeatherSnapshot | None.

    ``context_client.get_weather_snapshot`` takes (latitude, longitude, tenant_id)
    — it has no notion of a parcel. Adapt here by resolving the parcel centroid
    first; fail-safe to None (build_context tolerates a None weather input) if
    coords can't be resolved, matching the sensorless-capable design.
    """
    parcel_short = parcel_id.split(":")[-1] if parcel_id.startswith("urn:") else parcel_id
    coords = await context_client._resolve_parcel_coords(parcel_short, tenant_id)
    if not coords:
        return None
    latitude, longitude = coords
    return await context_client.get_weather_snapshot(
        latitude=latitude, longitude=longitude, tenant_id=tenant_id,
    )


def today_utc():
    return datetime.now(timezone.utc).date()


async def evaluate_parcel(parcel_id: str, tenant_id: str) -> int:
    """Per-parcel action-rules loop: plan -> phenology -> rules -> create ops.

    Best-effort context: phenology is the key input (drives the rule-fetch
    hint); weather/soil/ndvi/stress degrade gracefully to None on any failure
    so a missing data source never blocks rule evaluation.
    """
    plan = await _read_crop_plan(parcel_id, tenant_id)
    segments = [s for s in plan if s.get("status") in ("planned", "active")]
    seg = next((s for s in segments if s.get("status") == "active"), segments[0] if segments else None)
    if not seg:
        return 0

    latest = await _read_latest_assessment(parcel_id, tenant_id)
    if latest:
        stages = await get_phenology_stages(seg.get("species", "generic"))
        phenology = _build_status_from_dict(latest, stages)
        stress = {"composite_index": latest.get("compositeStressIndex"),
                  "dominant_stressor": latest.get("dominantStressor"),
                  "condition": latest.get("stressCondition")}
    else:
        phenology, stress = {}, None

    weather = await get_weather_snapshot(parcel_id, tenant_id)
    soil = await get_soil_properties(parcel_id, tenant_id)
    ndvi = await _fetch_parcel_ndvi(parcel_id, tenant_id)

    today = today_utc()
    ctx = build_context(seg, phenology, weather, soil, ndvi, stress, today)
    # Rule-fetch hint: phenology dict here is _build_status_from_dict's output,
    # which uses camelCase `currentStage` — NOT build_context's snake_case
    # `current_stage` (that key only exists inside ctx["phenology"]). The hint
    # is permissive (BioOrch ignores stage server-side); precise matching
    # happens via build_context + evaluate_conditions below.
    stage_hint = phenology.get("currentStage") if isinstance(phenology, dict) else None
    rules = await get_action_rules(seg.get("species"), stage_hint, seg.get("role"), tenant_id)

    created = 0
    for rule in sorted(rules, key=lambda r: r.get("priority", 0), reverse=True):
        if not evaluate_conditions(rule.get("conditions", {}), ctx):
            continue
        if await _operation_exists(parcel_id, rule["id"], today, tenant_id):
            continue
        if await _create_operation(parcel_id, seg, rule, ctx, tenant_id, today):
            created += 1
    return created


async def run_action_rules_for_tenant(tenant_id: str) -> dict:
    """Find active parcels and evaluate each; per-parcel error isolation."""
    parcels = await _find_active_parcels(tenant_id)
    created, errors = 0, []
    for p in parcels:
        try:
            created += await evaluate_parcel(p, tenant_id)
        except Exception as exc:  # noqa: BLE001 — isolate per parcel, never abort the batch
            logger.exception("run_action_rules_for_tenant: parcel %s tenant=%s failed", p, tenant_id)
            errors.append({"parcel": p, "error": str(exc)[:160]})
    return {"parcels": len(parcels), "operations_created": created, "errors": errors}
