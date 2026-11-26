from __future__ import annotations

from app.core.redis import redis_client

CREATIVE_STREAM = "graphytion:creative:runs"
CREATIVE_GROUP = "graphytion:creative-workers"


async def enqueue_creative_run(run_id: str) -> str:
    """Publish a wake-up signal; the PostgreSQL run row remains authoritative."""
    return str(await redis_client.xadd(
        CREATIVE_STREAM,
        {"run_id": run_id},
        maxlen=10000,
        approximate=True,
    ))
