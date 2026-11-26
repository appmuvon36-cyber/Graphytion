from fastapi import APIRouter
from app.api.v1.routes import health, identity, system

api_router = APIRouter()
api_router.include_router(health.router, tags=["health"])
api_router.include_router(identity.router, tags=["identity", "workspace", "projects"])
api_router.include_router(system.router, prefix="/system", tags=["system"])
