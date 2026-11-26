import asyncio

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import text

from app.core.database import engine
from app.core.redis import check_redis
from app.services.supabase_auth import supabase_auth
from app.services.supabase_storage import SupabaseStorage

router = APIRouter()


@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "graphytion-api"}


async def check_database() -> bool:
    try:
        async with engine.connect() as connection:
            await connection.execute(text("select 1"))
        return True
    except Exception:
        return False


@router.get("/ready", summary="Dependency readiness probe")
async def readiness() -> dict[str, object]:
    database_ok, redis_ok, auth_ok, storage_ok = await asyncio.gather(
        check_database(),
        check_redis(),
        supabase_auth.health_check(),
        SupabaseStorage().health_check(),
    )
    dependencies = {
        "database": database_ok,
        "redis": redis_ok,
        "supabase_auth": auth_ok,
        "supabase_storage": storage_ok,
    }
    ready = all(dependencies.values())
    if not ready:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "dependencies": dependencies},
        )
    return {"status": "ready", "dependencies": dependencies}
