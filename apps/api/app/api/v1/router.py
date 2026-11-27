from fastapi import APIRouter

from app.api.v1.routes import (
    assets,
    creative,
    health,
    identity,
    platform_admin,
    render,
    system,
    templates,
    timeline,
    subtitles,
    voiceover,
    webhooks,
)

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(identity.router, tags=["identity", "workspace", "projects"])
api_router.include_router(creative.router, tags=["creative production", "briefs", "scripts", "storyboards"])
api_router.include_router(templates.router, tags=["composition templates", "brand kits"])
api_router.include_router(platform_admin.router, prefix="/admin", tags=["platform administration"])
api_router.include_router(render.router, tags=["render jobs", "render workers"])
api_router.include_router(assets.router, tags=["project assets"])
api_router.include_router(timeline.router, tags=["multi-track timeline"])
api_router.include_router(voiceover.router, tags=["TTS and voiceover"])
api_router.include_router(subtitles.router, tags=["subtitle tracks"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
