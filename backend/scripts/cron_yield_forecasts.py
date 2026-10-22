"""CronJob driver: loop run-yield-forecasts per tenant until cursor null.

One parcel per page: each bioorch simulation takes 40-80 s and bioorch
allows 3 pending jobs per tenant. Tenants from SCHEDULED_TENANTS.
A failing page is logged and skipped, and a failing tenant never stops the
others: one slow or broken parcel must not cost the whole night.
"""
import asyncio
import os
import sys

import httpx

BATCH = 1
MAX_CONSECUTIVE_FAILURES = 3  # the backend itself is down: stop this tenant


async def _post_page(tenant: str, cursor, base_url: str, secret: str) -> dict:
    async with httpx.AsyncClient(timeout=340.0) as client:
        resp = await client.post(
            f"{base_url}/api/crop-health/internal/run-yield-forecasts",
            headers={"X-Internal-Service-Secret": secret},
            json={"tenant_id": tenant, "cursor": cursor, "batch_size": BATCH},
        )
        resp.raise_for_status()
        return resp.json()


async def run_tenant(tenant: str, base_url: str, secret: str) -> dict:
    cursor, totals = None, {"processed": 0, "written": 0, "errors": []}
    failures = 0
    while True:
        try:
            page = await _post_page(tenant, cursor, base_url, secret)
        except Exception as exc:
            print(f"[yield-forecasts] tenant={tenant} cursor={cursor} page failed: {exc!r}", file=sys.stderr)
            totals["errors"].append({"cursor": cursor, "error": type(exc).__name__})
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
    tenants = [t.strip() for t in os.environ.get("SCHEDULED_TENANTS", "").split(",") if t.strip()]
    for tenant in tenants:
        try:
            totals = await run_tenant(tenant, base_url, secret)
        except Exception as exc:
            print(f"[yield-forecasts] tenant={tenant} failed: {exc!r}", file=sys.stderr)
            continue
        print(f"[yield-forecasts] tenant={tenant} {totals}")


if __name__ == "__main__":
    asyncio.run(main())
