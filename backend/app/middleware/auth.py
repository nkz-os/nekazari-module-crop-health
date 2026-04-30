"""
Auth Middleware — JWT validation via Keycloak JWKS.

Validates RS256 JWTs from Keycloak with:
- Issuer whitelist (exact match)
- Audience validation
- Cookie fallback for httpOnly auth flow
- Public endpoints bypass (health, webhooks)
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
import jwt as pyjwt
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from app.config import get_settings

logger = logging.getLogger(__name__)

# Paths that do NOT require authentication
_PUBLIC_PATHS = {
    "/health",
    "/healthz",
    "/readyz",
}

# Webhook paths — authenticated by Fiware-Service header, not JWT
_WEBHOOK_PREFIXES = [
    "/webhooks/",
]

# JWKS cache
_jwks_client: pyjwt.PyJWKClient | None = None


def _get_jwks_client() -> pyjwt.PyJWKClient:
    """Lazy JWKS client initialisation."""
    global _jwks_client
    if _jwks_client is None:
        settings = get_settings()
        _jwks_client = pyjwt.PyJWKClient(settings.jwks_url, cache_keys=True)
    return _jwks_client


class AuthMiddleware(BaseHTTPMiddleware):
    """Keycloak JWT validation middleware."""

    async def dispatch(self, request: Request, call_next: Any) -> Any:
        path = request.url.path

        # Skip auth for public endpoints
        if path in _PUBLIC_PATHS:
            return await call_next(request)

        # Skip JWT auth for webhook endpoints (FIWARE internal)
        for prefix in _WEBHOOK_PREFIXES:
            if prefix in path:
                return await call_next(request)

        # OPTIONS (CORS preflight) — pass through
        if request.method == "OPTIONS":
            return await call_next(request)

        # Extract token: Authorization header or httpOnly cookie
        token = self._extract_token(request)
        if not token:
            return JSONResponse(
                status_code=401,
                content={"detail": "Missing authentication token"},
            )

        # Validate JWT
        try:
            settings = get_settings()
            jwks_client = _get_jwks_client()
            signing_key = jwks_client.get_signing_key_from_jwt(token)

            payload = pyjwt.decode(
                token,
                signing_key.key,
                algorithms=["RS256"],
                audience=settings.jwt_audience,
                issuer=settings.jwt_issuer_url,
            )

            # Inject tenant_id into request state
            tenant_id = (
                payload.get("tenant_id")
                or payload.get("tenant-id")
                or payload.get("tenant")
                or ""
            )
            request.state.tenant_id = tenant_id
            request.state.user_id = payload.get("sub", "")

        except pyjwt.ExpiredSignatureError:
            return JSONResponse(status_code=401, content={"detail": "Token expired"})
        except pyjwt.InvalidIssuerError:
            return JSONResponse(status_code=401, content={"detail": "Invalid token issuer"})
        except pyjwt.InvalidAudienceError:
            return JSONResponse(status_code=401, content={"detail": "Invalid token audience"})
        except Exception as exc:
            logger.warning("JWT validation failed: %s", exc)
            return JSONResponse(status_code=401, content={"detail": "Invalid token"})

        return await call_next(request)

    @staticmethod
    def _extract_token(request: Request) -> str | None:
        """Extract JWT from Authorization header or httpOnly cookie."""
        # 1. Authorization: Bearer <token>
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            return auth_header[7:]

        # 2. httpOnly cookie
        return request.cookies.get("nkz_token")
