from __future__ import annotations

import asyncio
import logging
import os
import socket
from types import SimpleNamespace
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import text

from app.api.v1.routes.creative import CreativeRunRequest, _process_creative_run
from app.core.database import SessionLocal, set_rls_subject
from app.core.redis import redis_client
from app.services.creative_queue import CREATIVE_GROUP, CREATIVE_STREAM, enqueue_creative_run

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
                where id=:task and status='running'
            """), {"task": task_id, "lease": LEASE_SECONDS})
            await heartbeat_db.commit()


async def _claim_and_execute(run_id: str | None = None) -> bool:
    async with SessionLocal() as db:
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
                where id=:run
            """), {"run": claimed["run_id"]})
            await db.commit()
            return True

        await db.execute(text("""
            update public.agent_tasks
            set status='running',attempt_count=attempt_count+1,
                started_at=coalesce(started_at,now()),
                lease_expires_at=now()+make_interval(secs => :lease)
            where id=:task
        """), {"task": task_id, "lease": LEASE_SECONDS})
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
        try:
            await _process_creative_run(
                db=db,
                request=request,
                actor=claimed["requested_by"],
                workspace_id=claimed["workspace_id"],
                project_id=claimed["project_id"],
                stage=stage,
                payload=payload,
                run=run_context,
                task=task_id,
            )
            return True
        except HTTPException as exc:
            logger.warning(
                "creative_run_failed",
                extra={"run_id": str(claimed["run_id"]), "status_code": exc.status_code},
            )
            if exc.status_code in (502, 504):
                await asyncio.sleep(min(2 ** int(claimed["attempt_count"]), 15))
                try:
                    await enqueue_creative_run(str(claimed["run_id"]))
                except Exception:
                    logger.exception("creative_retry_signal_failed", extra={"run_id": str(claimed["run_id"])})
            return True
        except Exception:
            logger.exception("creative_worker_unhandled_failure", extra={"run_id": str(claimed["run_id"])})
            await db.rollback()
            await db.execute(text("""
                update public.production_runs
                set status='failed',error_code='WORKER_UNHANDLED',
                    error_message_safe='Creative worker failed unexpectedly',
                    completed_at=now(),worker_id=null,lease_expires_at=null
                where id=:run
            """), {"run": claimed["run_id"]})
            await db.execute(text("""
                update public.agent_tasks set status='failed',
                    error_code='WORKER_UNHANDLED',completed_at=now(),lease_expires_at=null
                where id=:task
            """), {"task": task_id})
            await db.commit()
            return True
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass


async def _ensure_group() -> None:
    try:
        await redis_client.xgroup_create(CREATIVE_STREAM, CREATIVE_GROUP, id="0", mkstream=True)
    except Exception as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def run_worker() -> None:
    await _ensure_group()
    consumer = WORKER_ID
    logger.info("creative_worker_started", extra={"worker_id": WORKER_ID})
    while True:
        # Reclaim messages left pending by a worker that exited unexpectedly.
        try:
            claimed_messages = await redis_client.xautoclaim(
                CREATIVE_STREAM, CREATIVE_GROUP, consumer, min_idle_time=60000,
                start_id="0-0", count=5,
            )
            messages = claimed_messages[1] if len(claimed_messages) > 1 else []
            for message_id, fields in messages:
                try:
                    await _claim_and_execute(fields.get("run_id"))
                finally:
                    await redis_client.xack(CREATIVE_STREAM, CREATIVE_GROUP, message_id)
        except Exception:
            logger.exception("creative_worker_reclaim_failed")

        try:
            batches = await redis_client.xreadgroup(
                CREATIVE_GROUP, consumer, {CREATIVE_STREAM: ">"}, count=5, block=5000
            )
            for _, messages in batches:
                for message_id, fields in messages:
                    try:
                        await _claim_and_execute(fields.get("run_id"))
                    finally:
                        await redis_client.xack(CREATIVE_STREAM, CREATIVE_GROUP, message_id)
        except Exception:
            logger.exception("creative_worker_stream_read_failed")
            await asyncio.sleep(2)

        # PostgreSQL recovery scan covers the commit-to-Redis crash window and
        # expired leases; Redis is never the durable queue of record.
        try:
            while await _claim_and_execute(None):
                pass
        except Exception:
            logger.exception("creative_worker_database_recovery_scan_failed")
            await asyncio.sleep(2)


def main() -> None:
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
    try:
        asyncio.run(run_worker())
    except KeyboardInterrupt:
        logger.info("creative_worker_stopped")


if __name__ == "__main__":
    main()
