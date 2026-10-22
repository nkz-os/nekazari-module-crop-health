"""Gateway identity for user-facing routes.

The api-gateway validates the user's JWT and signs the identity it forwards
(X-Auth-Signature, HMAC over token + tenant). ``require_auth`` from the SDK
verifies that signature, so a pod inside the cluster cannot claim another
tenant by setting X-Tenant-ID itself. Internal and webhook routes carry their
own credentials and do not use this dependency.
"""

from __future__ import annotations

import logging

from fastapi import Request
from nkz_platform_sdk import auth as sdk_auth
from nkz_platform_sdk.auth import AuthContext, require_auth

logger = logging.getLogger(__name__)


async def gateway_identity(request: Request, ctx: AuthContext = require_auth()) -> AuthContext:
    """Verified identity, also exposed as request.state.tenant_id / user_id."""
    request.state.tenant_id = ctx.tenant_id
    request.state.user_id = ctx.user_id
    return ctx


def ensure_signature_enforced() -> None:
    """Refuse to start when gateway signatures would not be checked.

    Without REQUIRE_HMAC_SIGNATURE=true and HMAC_SECRET, require_auth accepts
    unsigned identity headers: that is fail-open, so the service must not run.
    """
    if not (sdk_auth.REQUIRE_HMAC and sdk_auth.HMAC_SECRET):
        logger.critical(
            "gateway signature check disabled: REQUIRE_HMAC_SIGNATURE=%s HMAC_SECRET set=%s",
            sdk_auth.REQUIRE_HMAC,
            bool(sdk_auth.HMAC_SECRET),
        )
        raise RuntimeError("REQUIRE_HMAC_SIGNATURE=true and HMAC_SECRET are required")
