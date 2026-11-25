"""CronJob driver: loop run-scheduled-assessments per tenant until cursor null.

Called in-cluster (not via gateway). Tenants from SCHEDULED_TENANTS env.

A failing page is logged and skipped, and a failing tenant never stops the
others: one slow or broken parcel must not cost the remaining tenants their run.
The job exits non-zero at the end when anything failed.

Known limitation (documented): tenant enumeration is env-driven for the
cimiento; wiring to a tenant registry is a follow-up.
"""
import asyncio
import os
import sys

import httpx

from scripts.scheduled_tenants import scheduled_tenants

BATCH = 200
MAX_CONSECUTIVE_FAILURES = 3  # the backend itself is down: stop this tenant
# A fresh job pod can try to connect before its network is ready. A connect error
# means the request never reached the backend, so it is safe to retry after a wait.
CONNECT_RETRY_DELAYS_S = (2, 5, 10, 20)


async def _post_once(tenant: str, cursor, base_url: str, secret: str) -> dict:
    async with httpx.AsyncClient(timeout=120.0) as client:
        resp = await client.post(
            f"{base_url}/api/crop-health/internal/run-scheduled-assessments",
            headers={"X-Internal-Service-Secret": secret},
            json={"tenant_id": tenant, "cursor": cursor, "batch_size": BATCH},
        )
        resp.raise_for_status()
        return resp.json()


async def _post_page(tenant: str, cursor, base_url: str, secret: str) -> dict:
    """One page; connect errors are retried with CONNECT_RETRY_DELAYS_S, anything else raises."""
    for delay in CONNECT_RETRY_DELAYS_S:
        try:
            return await _post_once(tenant, cursor, base_url, secret)
        except httpx.ConnectError as exc:
            print(f"[scheduled] tenant={tenant} cursor={cursor} connect failed, retry in {delay}s: {exc!r}",
                  file=sys.stderr)
            await asyncio.sleep(delay)
    return await _post_once(tenant, cursor, base_url, secret)


async def run_tenant(tenant: str, base_url: str, secret: str) -> dict:
    cursor, totals = None, {"processed": 0, "written": 0, "errors": [], "failed_pages": 0}
    failures = 0
    while True:
        try:
            page = await _post_page(tenant, cursor, base_url, secret)
        except Exception as exc:  # noqa: BLE001 -- a bad page must not cost the rest
            print(f"[scheduled] tenant={tenant} cursor={cursor} page failed: {exc!r}", file=sys.stderr)
            totals["errors"].append({"cursor": cursor, "error": type(exc).__name__})
            totals["failed_pages"] += 1
            failures += 1
            if failures >= MAX_CONSECUTIVE_FAILURES:
                return totals
            cursor = str(int(cursor or 0) + BATCH)
            continue
        failures = 0
        totals["processed"] += page["processed"]
        totals["written"] += page["written"]
        totals["errors"].extend(page["errors"])
        cursor = page["next_cursor"]
        if cursor is None:
            return totals


async def main() -> None:
    base_url = os.environ.get("SELF_URL", "http://crop-health-api-service:8000")
    secret = os.environ["INTERNAL_SERVICE_SECRET"]
    tenants = await scheduled_tenants()
    failed_tenants = 0
    for tenant in tenants:
        try:
            totals = await run_tenant(tenant, base_url, secret)
        except Exception as exc:  # noqa: BLE001 -- the other tenants still run
            failed_tenants += 1
            print(f"[scheduled] tenant={tenant} failed: {exc!r}", file=sys.stderr)
            continue
        print(f"[scheduled] tenant={tenant} {totals}")
        if totals.get("failed_pages"):
            failed_tenants += 1
    if failed_tenants:
        print(f"[scheduled] {failed_tenants} of {len(tenants)} tenants failed", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
