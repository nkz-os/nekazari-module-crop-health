"""CronJob driver: loop run-yield-forecasts per tenant until cursor null.

One parcel per page: each bioorch simulation takes 40-80 s and bioorch
allows 3 pending jobs per tenant. Tenants from SCHEDULED_TENANTS.
A failing page is logged and skipped, and a failing tenant never stops the
others: one slow or broken parcel must not cost the whole night.
Connection errors (request never reached the backend) are retried with a
short backoff; a request that was sent is never retried.
The backend is awaited before the first page.
The job exits non-zero when the backend never became ready or a page was lost.
"""
import asyncio
import os
import sys

import httpx

BATCH = 1
MAX_CONSECUTIVE_FAILURES = 3  # the backend itself is down: stop this tenant
CONNECT_RETRY_DELAYS: tuple[float, ...] = (2.0, 4.0, 8.0)  # waits between the 4 attempts of a page
READY_ATTEMPTS = 10
READY_DELAY = 3.0
# A simulation can take minutes to answer; establishing the connection must not.
REQUEST_TIMEOUT = httpx.Timeout(340.0, connect=10.0)

_sleep = asyncio.sleep  # replaced in tests


async def _health_status(url: str) -> int:
    async with httpx.AsyncClient(timeout=5.0) as client:
        return (await client.get(url)).status_code


async def _wait_ready(base_url: str) -> bool:
    for attempt in range(READY_ATTEMPTS):
        try:
            if await _health_status(f"{base_url}/health") == 200:
                return True
        except httpx.HTTPError:
            pass
        if attempt < READY_ATTEMPTS - 1:
            await _sleep(READY_DELAY)
    return False


async def _post_page(tenant: str, cursor, base_url: str, secret: str) -> dict:
    delays = iter(CONNECT_RETRY_DELAYS)
    while True:
        try:
            return await _post_once(tenant, cursor, base_url, secret)
        except (httpx.ConnectError, httpx.ConnectTimeout):
            delay = next(delays, None)
            if delay is None:
                raise
            await _sleep(delay)


async def _post_once(tenant: str, cursor, base_url: str, secret: str) -> dict:
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.post(
            f"{base_url}/api/crop-health/internal/run-yield-forecasts",
            headers={"X-Internal-Service-Secret": secret},
            json={"tenant_id": tenant, "cursor": cursor, "batch_size": BATCH},
        )
        resp.raise_for_status()
        return resp.json()


async def run_tenant(tenant: str, base_url: str, secret: str) -> dict:
    cursor, totals = None, {"processed": 0, "written": 0, "errors": [], "failed_pages": 0}
    failures = 0
    while True:
        try:
            page = await _post_page(tenant, cursor, base_url, secret)
        except Exception as exc:
            print(f"[yield-forecasts] tenant={tenant} cursor={cursor} page failed: {exc!r}", file=sys.stderr)
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
    tenants = [t.strip() for t in os.environ.get("SCHEDULED_TENANTS", "").split(",") if t.strip()]
    if not await _wait_ready(base_url):
        print("[yield-forecasts] backend not ready, no page posted", file=sys.stderr)
        sys.exit(1)
    failed_tenants = 0
    for tenant in tenants:
        try:
            totals = await run_tenant(tenant, base_url, secret)
        except Exception as exc:
            failed_tenants += 1
            print(f"[yield-forecasts] tenant={tenant} failed: {exc!r}", file=sys.stderr)
            continue
        print(f"[yield-forecasts] tenant={tenant} {totals}")
        if totals.get("failed_pages"):
            failed_tenants += 1
    if failed_tenants:
        print(f"[yield-forecasts] {failed_tenants} of {len(tenants)} tenants failed", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
