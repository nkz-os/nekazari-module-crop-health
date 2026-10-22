"""CronJob driver: loop run-scheduled-assessments per tenant until cursor null.

Called in-cluster (not via gateway). Tenants from SCHEDULED_TENANTS env.

Known limitation (documented): tenant enumeration is env-driven for the
cimiento; wiring to a tenant registry is a follow-up.
"""
import asyncio
import os

import httpx


async def _post_page(tenant: str, cursor, base_url: str, secret: str) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{base_url}/api/crop-health/internal/run-scheduled-assessments",
            headers={"X-Internal-Service-Secret": secret},
            json={"tenant_id": tenant, "cursor": cursor, "batch_size": 200},
        )
        resp.raise_for_status()
        return resp.json()


async def run_tenant(tenant: str, base_url: str, secret: str) -> dict:
    cursor, totals = None, {"processed": 0, "written": 0, "errors": []}
    while True:
        page = await _post_page(tenant, cursor, base_url, secret)
        totals["processed"] += page["processed"]
        totals["written"] += page["written"]
        totals["errors"].extend(page["errors"])
        cursor = page["next_cursor"]
        if cursor is None:
            return totals


async def main() -> None:
    base_url = os.environ.get("SELF_URL", "http://crop-health-api-service:8000")
    secret = os.environ["INTERNAL_SERVICE_SECRET"]
    tenants = [t.strip() for t in os.environ.get("SCHEDULED_TENANTS", "").split(",") if t.strip()]
    for tenant in tenants:
        totals = await run_tenant(tenant, base_url, secret)
        print(f"[scheduled] tenant={tenant} {totals}")


if __name__ == "__main__":
    asyncio.run(main())
