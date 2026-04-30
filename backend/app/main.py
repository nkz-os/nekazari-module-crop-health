"""
Crop Health Module — FastAPI Application

Main entry point. Lifespan manages Redis connection.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.api import router as api_router
from app.services.redis_state import RedisState

logger = logging.getLogger(__name__)

# Module-level reference so API handlers can access it
_redis_state: RedisState | None = None


def get_redis_state() -> RedisState:
    """Dependency: get the Redis state client."""
    if _redis_state is None:
        raise RuntimeError("Redis not initialised — app not fully started")
    return _redis_state


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: connect/disconnect Redis."""
    global _redis_state
    settings = get_settings()

    # Configure structured logging
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(name)s] %(levelname)s %(message)s",
    )

    logger.info(
        "%s v%s starting — prefix=%s debug=%s",
        settings.app_name,
        settings.app_version,
        settings.api_prefix,
        settings.debug,
    )

    # Connect Redis
    try:
        _redis_state = await RedisState.create()
        logger.info("Redis sliding window ready (prefix=%s)", settings.redis_key_prefix)
    except Exception as exc:
        logger.error("Redis connection failed: %s — module will operate without temporal state", exc)
        _redis_state = RedisState()  # degraded mode — no client

    yield

    # Cleanup
    if _redis_state:
        await _redis_state.close()
    logger.info("%s shut down", settings.app_name)


def create_app() -> FastAPI:
    """Application factory."""
    settings = get_settings()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Crop Health Engine — Async biophysical inference for Nekazari Platform",
        docs_url=f"{settings.api_prefix}/docs",
        redoc_url=f"{settings.api_prefix}/redoc",
        openapi_url=f"{settings.api_prefix}/openapi.json",
        lifespan=lifespan,
    )

    # CORS
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Health check (root level for K8s probes)
    @app.get("/health")
    async def health_check():
        redis_health = {}
        if _redis_state:
            redis_health = await _redis_state.health_check()
        return {
            "status": "healthy",
            "service": settings.app_name,
            "version": settings.app_version,
            **redis_health,
        }

    # API routes
    app.include_router(api_router, prefix=settings.api_prefix)

    return app


# Create application instance
app = create_app()
