"""API package — route registration."""

from fastapi import APIRouter, Depends

from app.api.assessments import router as assessments_router
from app.api.phenology import router as phenology_router
from app.api.setup import router as setup_router
from app.api.sources import router as sources_router
from app.api.webhooks import router as webhooks_router
from app.auth import gateway_identity

router = APIRouter()
# User-facing routers: identity verified against the gateway signature.
_user = [Depends(gateway_identity)]
router.include_router(assessments_router, dependencies=_user)
router.include_router(phenology_router, dependencies=_user)
router.include_router(setup_router)
router.include_router(sources_router, dependencies=_user)
router.include_router(webhooks_router)
