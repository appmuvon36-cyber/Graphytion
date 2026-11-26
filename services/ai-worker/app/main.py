import asyncio
import logging
import os
import signal
from redis.asyncio import Redis
async def run() -> None:
    redis = Redis.from_url(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM): loop.add_signal_handler(sig, stop.set)
    try:
        await redis.ping()
        logging.info("AI worker connected to Redis transport; no agent task consumer is enabled in Phase 01.")
        await stop.wait()
    finally: await redis.aclose()
if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(run())
