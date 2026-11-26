from __future__ import annotations

import logging
from typing import Literal

from redis.asyncio import Redis

from app.core.config import settings

logger = logging.getLogger(__name__)
QueueName = Literal["media", "render"]


async def notify_worker(queue: QueueName, job_id: str) -> bool:
    """Best-effort wake-up signal. PostgreSQL remains the durable job source of truth."""
    redis_url = settings.redis_url_value
    if not redis_url:
        return False
    client = Redis.from_url(
        redis_url,
        decode_responses=True,
        socket_connect_timeout=1,
        socket_timeout=1,
        retry_on_timeout=False,
        max_connections=2,
    )
    try:
        await client.lpush(f"graphytion:{queue}:jobs", job_id)
        return True
    except Exception:
        logger.warning("redis_job_notification_unavailable", extra={"queue": queue})
        return False
    finally:
        await client.aclose()
