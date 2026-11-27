import asyncio
from contextlib import asynccontextmanager
from time import perf_counter
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.database import engine
from app.core.errors import (
    http_error_handler,
    unhandled_error_handler,
    validation_error_handler,
)
from app.core.logging import configure_logging, logger
from app.workers.creative import run_worker
from app.workers.orchestrator import run_dispatcher

configure_logging(settings.log_level)


@asynccontextmanager
async def lifespan(_: FastAPI):
    logger.info("application_starting", environment=settings.app_env)
    creative_worker_task = asyncio.create_task(run_worker(), name="graphytion-creative-worker")
    orchestrator_task = asyncio.create_task(
        run_dispatcher(), name="graphytion-production-orchestrator"
    )
    logger.info("creative_worker_embedded", worker="postgresql-lease-poller")
    logger.info("production_orchestrator_embedded", worker="postgresql-dag-dispatcher")
    try:
        yield
    finally:
        creative_worker_task.cancel()
        orchestrator_task.cancel()
        await asyncio.gather(creative_worker_task, orchestrator_task, return_exceptions=True)
        await engine.dispose()


app = FastAPI(
    title="Graphytion API",
    version="1.0.0",
    description="Graphytion business and orchestration control plane",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "X-Request-ID"],
)
app.add_exception_handler(StarletteHTTPException, http_error_handler)
app.add_exception_handler(RequestValidationError, validation_error_handler)
app.add_exception_handler(Exception, unhandled_error_handler)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or str(uuid4())
    request.state.request_id = request_id
    started = perf_counter()
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    logger.info(
        "http_request_completed",
        request_id=request_id,
        method=request.method,
        path=request.url.path,
        status_code=response.status_code,
        duration_ms=round((perf_counter() - started) * 1000, 2),
    )
    return response


app.include_router(api_router, prefix="/api/v1")
