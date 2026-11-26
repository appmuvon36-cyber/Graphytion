from redis.asyncio import Redis

from app.core.config import settings

redis_client = Redis.from_url(
    settings.redis_url_value,
    encoding="utf-8",
    decode_responses=True,
    socket_connect_timeout=3,
    socket_timeout=3,
    health_check_interval=30,
)


async def check_redis() -> bool:
    try:
        return bool(await redis_client.ping())
    except Exception:
        return False
