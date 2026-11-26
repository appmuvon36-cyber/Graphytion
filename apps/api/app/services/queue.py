from redis.asyncio import Redis
from app.core.config import settings

class QueueTransport:
    """Redis transport adapter only; durable job state belongs in PostgreSQL."""
    def __init__(self) -> None:
        self._client = Redis.from_url(settings.redis_url, encoding="utf-8", decode_responses=True)
    async def publish(self, stream: str, payload: dict[str, str]) -> str:
        if not stream.startswith("graphytion:"):
            raise ValueError("Queue stream must be namespaced")
        return await self._client.xadd(stream, payload, maxlen=10000, approximate=True)
    async def close(self) -> None:
        await self._client.aclose()
