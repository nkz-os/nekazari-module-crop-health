"""CronJob driver: run action rules per tenant (cluster-internal).

Called in-cluster (not via the public gateway). Tenants from
ACTION_RULE_TENANTS env. Unlike run-scheduled-assessments, this is a single
POST per tenant — the internal endpoint processes all parcels for the
tenant in one call (no cursor/pagination).

Known limitation (documented): tenant enumeration is env-driven for the
cimiento; wiring to a tenant registry is a follow-up.
"""
import asyncio
import os

import httpx


async def _post_tenant(tenant: str, base_url: str, secret: str) -> dict:
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            f"{base_url}/api/crop-health/internal/run-action-rules",
            headers={"X-Internal-Service-Secret": secret},
            json={"tenant_id": tenant},
        )
        resp.raise_for_status()
        return resp.json()


async def main() -> None:
    base_url = os.environ.get("SELF_URL", "http://crop-health-api-service:8000")
    secret = os.environ["INTERNAL_SERVICE_SECRET"]
    tenants = [t.strip() for t in os.environ.get("ACTION_RULE_TENANTS", "").split(",") if t.strip()]
    for tenant in tenants:
        result = await _post_tenant(tenant, base_url, secret)
        print(f"[action-rules] tenant={tenant} {result}")


if __name__ == "__main__":
    asyncio.run(main())
