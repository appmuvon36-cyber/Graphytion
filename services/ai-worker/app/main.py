import asyncio
import logging
import os
import signal


async def run() -> None:
    """Keep the optional AI worker process healthy without an external queue broker."""
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop.set)
    logging.info(
        "AI worker is idle: agent-task execution remains owned by the PostgreSQL-backed API worker"
    )
    await stop.wait()


if __name__ == "__main__":
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
    asyncio.run(run())
