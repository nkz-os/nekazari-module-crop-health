"""API package — route registration."""

from fastapi import APIRouter

from app.api.webhooks import router as webhooks_router

router = APIRouter()
router.include_router(webhooks_router)
