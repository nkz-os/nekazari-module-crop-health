"""The tenants of SCHEDULED_TENANTS that the platform says are active."""
import asyncio
import os
import sys

from nkz_platform_sdk import installed_tenants
from nkz_platform_sdk.installations import InstalledTenantsUnavailable

MODULE_ID = "crop-health"
# A fresh job pod can ask before its network is ready.
CONNECT_RETRY_DELAYS_S = (2, 5, 10, 20)


async def scheduled_tenants() -> list[str]:
    """The configured list, in order, without suspended tenants.

    A suspended tenant is absent from every state the platform reports. If the
    platform cannot answer, the whole list runs: losing the day for everyone is
    worse than one more run for a tenant that is on its way out.
    """
    configured = [t.strip() for t in os.environ.get("SCHEDULED_TENANTS", "").split(",") if t.strip()]
    if not configured:
        return []
    states = None
    for delay in (*CONNECT_RETRY_DELAYS_S, None):
        try:
            states = await installed_tenants(MODULE_ID)
            break
        except InstalledTenantsUnavailable as exc:
            if delay is None:
                print(f"[scheduled-tenants] platform unavailable, nothing skipped: {exc}",
                      file=sys.stderr)
                return configured
            await asyncio.sleep(delay)
    active = {*states.enabled, *states.disabled, *states.not_installed}
    if not active:
        print("[scheduled-tenants] platform reported no tenant at all, nothing skipped",
              file=sys.stderr)
        return configured
    for tenant in configured:
        if tenant not in active:
            print(f"[scheduled-tenants] tenant={tenant} skipped: not active")
    return [t for t in configured if t in active]
