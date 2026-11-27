from __future__ import annotations

import asyncio
import logging
import os
import socket
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import settings
from app.api.v1.routes.creative import CreativeRunRequest, _process_creative_run
from app.core.database import SessionLocal, set_rls_subject

logger = logging.getLogger("graphytion.creative_worker")
WORKER_ID = f"{socket.gethostname()}:{os.getpid()}:{uuid4().hex[:8]}"
LEASE_SECONDS = 180


class CreativeCancellationRequested(Exception):
    pass


async def _heartbeat(run_id: str, actor_id: str, task_id: str) -> None:
    while True:
        await asyncio.sleep(30)
        async with SessionLocal() as heartbeat_db:
            await set_rls_subject(heartbeat_db, actor_id)
            renewed = await heartbeat_db.scalar(text("""
                update public.production_runs
                set lease_expires_at=now()+make_interval(secs => :lease)
                where id=:run and worker_id=:worker and cancel_requested_at is null
                returning id
            """), {"run": run_id, "worker": WORKER_ID, "lease": LEASE_SECONDS})
            if renewed is None:
                state = await heartbeat_db.scalar(text("""
                    select status from public.production_runs where id=:run
                """), {"run": run_id})
                await heartbeat_db.rollback()
                if state == "cancel_requested":
                    raise CreativeCancellationRequested()
                raise RuntimeError("Creative run worker lease was lost")
            await heartbeat_db.execute(text("""
                update public.agent_tasks
                set lease_expires_at=now()+make_interval(secs => :lease)
                where id=:task and status='running' and worker_id=:worker
            """), {"task": task_id, "lease": LEASE_SECONDS, "worker": WORKER_ID})
            await heartbeat_db.commit()


async def _claim_and_execute(run_id: str | None = None) -> bool:
    async with SessionLocal() as db:
        await db.execute(text("select private.graphytion_finalize_creative_runs()"))
        await db.commit()
        claimed = (await db.execute(text("""
            select * from private.graphytion_claim_creative_run(
                :worker_id, cast(:run_id as uuid), :lease_seconds
            )
        """), {
            "worker_id": WORKER_ID,
            "run_id": run_id,
            "lease_seconds": LEASE_SECONDS,
        })).mappings().first()
        if claimed is None:
            await db.rollback()
            return False

        await set_rls_subject(db, str(claimed["requested_by"]))
        task_id = await db.scalar(text("""
            select id from public.agent_tasks
            where production_run_id=:run and status in ('queued','retry_wait','running')
            order by created_at limit 1
        """), {"run": claimed["run_id"]})
        if task_id is None:
            await db.execute(text("""
                update public.production_runs
                set status='failed',error_code='TASK_NOT_FOUND',
                    error_message_safe='Creative task record is missing',
                    completed_at=now(),worker_id=null,lease_expires_at=null
                where id=:run and worker_id=:worker
            """), {"run": claimed["run_id"], "worker": WORKER_ID})
            await db.commit()
            return True

        await db.execute(text("""
            update public.agent_tasks
            set status='running',worker_id=:worker,attempt_count=attempt_count+1,
                started_at=coalesce(started_at,now()),
                lease_expires_at=now()+make_interval(secs => :lease)
            where id=:task
        """), {"task": task_id, "lease": LEASE_SECONDS, "worker": WORKER_ID})
        await db.commit()

        snapshot = dict(claimed["input_snapshot"])
        stage = str(snapshot.get("stage", ""))
        payload = CreativeRunRequest.model_validate(snapshot)
        request = SimpleNamespace(state=SimpleNamespace(request_id=str(uuid4())))
        heartbeat_task = asyncio.create_task(
            _heartbeat(str(claimed["run_id"]), str(claimed["requested_by"]), str(task_id))
        )
        run_context = dict(claimed)
        run_context["id"] = claimed["run_id"]
        processing_task = asyncio.create_task(_process_creative_run(
            db=db,
            request=request,
            actor=claimed["requested_by"],
            workspace_id=claimed["workspace_id"],
            project_id=claimed["project_id"],
            stage=stage,
            payload=payload,
            run=run_context,
            task=task_id,
        ))
        try:
            done, _ = await asyncio.wait(
                {processing_task, heartbeat_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done:
                try:
                    heartbeat_task.result()
                except CreativeCancellationRequested:
                    processing_task.cancel()
                    await asyncio.gather(processing_task, return_exceptions=True)
                    await db.rollback()
                    await db.execute(text("""
                        update public.production_runs
                        set status='cancelled',cancelled_at=now(),completed_at=now(),
                            worker_id=null,lease_expires_at=null
                        where id=:run and worker_id=:worker
                    """), {"run": claimed["run_id"], "worker": WORKER_ID})
                    await db.execute(text("""
                        update public.agent_tasks set status='cancelled',completed_at=now(),
                            lease_expires_at=null
                        where id=:task and worker_id=:worker
                    """), {"task": task_id, "worker": WORKER_ID})
                    await db.execute(text("""
                        insert into public.workflow_events(production_run_id,event_type,event_payload,sequence_number)
                        values (:run,'stage.cancelled','{}'::jsonb,
                          (select coalesce(max(sequence_number),0)+1 from public.workflow_events where production_run_id=:run))
                    """), {"run": claimed["run_id"]})
                    await db.commit()
                    return True
                raise RuntimeError("Creative run heartbeat stopped unexpectedly")
            await processing_task
            return True
        except HTTPException as exc:
            logger.warning(
                "creative_run_failed",
                extra={"run_id": str(claimed["run_id"]), "status_code": exc.status_code},
            )
            if exc.status_code in (502, 504):
                await asyncio.sleep(min(2 ** int(claimed["attempt_count"]), 15))
                # PostgreSQL polling discovers the retry after its retry_wait timestamp.
            return True
        except Exception:
            logger.exception("creative_worker_unhandled_failure", extra={"run_id": str(claimed["run_id"])})
            if not processing_task.done():
                processing_task.cancel()
                await asyncio.gather(processing_task, return_exceptions=True)
            await db.rollback()
            await db.execute(text("""
                update public.production_runs
                set status='failed',error_code='WORKER_UNHANDLED',
                    error_message_safe='Creative worker failed unexpectedly',
                    completed_at=now(),worker_id=null,lease_expires_at=null
                where id=:run and worker_id=:worker
            """), {"run": claimed["run_id"], "worker": WORKER_ID})
            await db.execute(text("""
                update public.agent_tasks set status='failed',
                    error_code='WORKER_UNHANDLED',completed_at=now(),lease_expires_at=null
                where id=:task and worker_id=:worker
            """), {"task": task_id, "worker": WORKER_ID})
            await db.commit()
            return True
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except (asyncio.CancelledError, Exception):
                pass


async def run_worker() -> None:
    redis_client = (
        Redis.from_url(
            settings.redis_url_value,
            decode_responses=True,
            socket_connect_timeout=1.5,
            socket_timeout=3,
        )
        if settings.redis_url_value else None
    )
    logger.info(
        "creative_worker_started",
        extra={"worker_id": WORKER_ID, "queue": "postgresql_with_optional_redis_wakeup"},
    )
    try:
        while True:
            try:
                processed = False
                while await _claim_and_execute(None):
                    processed = True
                if not processed:
                    # Redis is only a wake-up signal. Every wake-up is followed by
                    # an authoritative PostgreSQL claim; missed signals are harmless.
                    if redis_client is not None:
                        try:
                            await redis_client.blpop("graphytion:creative:jobs", timeout=2)
                        except Exception:
                            logger.warning("creative_redis_wakeup_unavailable_polling_postgres", exc_info=True)
                            await asyncio.sleep(2)
                    else:
                        await asyncio.sleep(2)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("creative_worker_database_poll_failed")
                await asyncio.sleep(3)
    finally:
        if redis_client is not None:
            await redis_client.aclose()


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("creative_worker_stopped")


if __name__ == "__main__":
    main()
