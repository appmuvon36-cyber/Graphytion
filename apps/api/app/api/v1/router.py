from fastapi import APIRouter

from app.api.v1.routes import creative, health, identity, platform_admin, system, webhooks

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(identity.router, tags=["identity", "workspace", "projects"])
api_router.include_router(
    creative.router, tags=["creative production", "briefs", "scripts", "storyboards"]
)
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
