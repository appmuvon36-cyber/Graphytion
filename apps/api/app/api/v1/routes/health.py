from fastapi import APIRouter
from app.core.redis import check_redis
router = APIRouter()
@router.get("/health", summary="Liveness probe")
async def health() -> dict[str, str]:
    return {"status":"ok","service":"graphytion-api"}
@router.get("/ready", summary="Readiness probe")
async def readiness() -> dict[str, object]:
    redis_ok = await check_redis()
    return {"status":"ready" if redis_ok else "degraded","dependencies":{"redis":redis_ok}}
