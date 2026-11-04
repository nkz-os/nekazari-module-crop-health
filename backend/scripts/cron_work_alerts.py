"""CronJob driver: POST /internal/work-alerts/run once per installed tenant.

Called in-cluster (not via gateway). Tenants come from entity-manager's installation
list (SDK `installed_tenants`); SCHEDULED_TENANTS, when set, overrides it. A failing
tenant never stops the others; the job exits non-zero at the end when any failed.
"""
import asyncio
import os
import sys

import httpx
from nkz_platform_sdk import installed_tenants

MODULE_ID = "crop-health"


async def _post_tenant(tenant: str, base_url: str, secret: str) -> dict:
    async with httpx.AsyncClient(timeout=300.0) as client:
        resp = await client.post(
            f"{base_url}/api/crop-health/internal/work-alerts/run",
            headers={"X-Internal-Service-Secret": secret},
            json={"tenant_id": tenant},
        )
        resp.raise_for_status()
        return resp.json()


async def run_tenants(tenants: list[str], base_url: str, secret: str) -> int:
    """Run every tenant; returns how many failed."""
    failed = 0
    for tenant in tenants:
        try:
            totals = await _post_tenant(tenant, base_url, secret)
        except Exception as exc:  # noqa: BLE001 -- the other tenants still run
            failed += 1
            print(f"[work-alerts] tenant={tenant} failed: {exc!r}", file=sys.stderr)
            continue
        print(f"[work-alerts] tenant={tenant} {totals}")
    return failed


async def _tenants() -> list[str]:
    override = [t.strip() for t in os.environ.get("SCHEDULED_TENANTS", "").split(",") if t.strip()]
    if override:
        return override
    return list((await installed_tenants(MODULE_ID)).enabled)


async def main() -> None:
    base_url = os.environ.get("SELF_URL", "http://crop-health-api-service:8000")
    secret = os.environ["INTERNAL_SERVICE_SECRET"]
    tenants = await _tenants()
    failed = await run_tenants(tenants, base_url, secret)
    if failed:
        print(f"[work-alerts] {failed} of {len(tenants)} tenants failed", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
