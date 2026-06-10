"""API package — route registration."""

from fastapi import APIRouter

from app.api.assessments import router as assessments_router
from app.api.setup import router as setup_router
from app.api.sources import router as sources_router
from app.api.webhooks import router as webhooks_router

router = APIRouter()
router.include_router(assessments_router)
router.include_router(setup_router)
router.include_router(sources_router)
router.include_router(webhooks_router)
