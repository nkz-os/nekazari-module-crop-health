"""Gateway-style headers for direct calls to soil-module (HMAC-enabled backend)."""

from __future__ import annotations

import hashlib
import hmac
import os
import time


def soil_module_headers(
    tenant_id: str,
    user_id: str = "crop-health-worker",
) -> dict[str, str]:
    """Headers for service-to-service soil API calls (empty JWT + HMAC)."""
    headers = {"X-Tenant-ID": tenant_id, "X-User-ID": user_id}
    secret = os.getenv("HMAC_SECRET", "")
    if not secret:
        return headers
    timestamp = str(int(time.time()))
    payload = f"|{tenant_id}|{timestamp}"
    signature = hmac.new(
        secret.encode("utf-8"),
        payload.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    headers["X-Auth-Signature"] = f"{signature}:{timestamp}"
    return headers
