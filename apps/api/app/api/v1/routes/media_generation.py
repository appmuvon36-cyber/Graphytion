from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims, DbSession
from app.core.config import settings
from app.core.database import set_rls_subject
from app.services.workspace_authorization import WorkspacePermissionResolver
from app.services.supabase_storage import SupabaseStorage
from app.services.queue_notifications import notify_worker
from app.services.quota import release_fixed_operation

router = APIRouter()
permissions = WorkspacePermissionResolver()
BUCKET = "project-assets"
MAX_IMAGE_BYTES = 50 * 1024 * 1024
MAX_VIDEO_BYTES = 512 * 1024 * 1024


class MediaGenerationCreate(BaseModel):
    media_type: Literal["image", "video"]
    provider_key: Literal["gemini"] = "gemini"
    model_key: str = Field(min_length=1, max_length=128)
    prompt: str = Field(min_length=1, max_length=32000)
    generation_config: dict[str, Any] = Field(default_factory=dict)


class MediaGenerationFailure(BaseModel):
    error_code: str = Field(min_length=1, max_length=120)
    retryable: bool = False


def _actor(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(401, "Invalid authenticated subject") from exc


async def _scope(db: AsyncSession, project_id: UUID, actor: UUID, permission: str) -> UUID:
    workspace = await db.scalar(text("""
        select workspace_id from public.video_projects
        where id=:project and status<>'deleted'
    """), {"project": project_id})
    if workspace is None:
        raise HTTPException(404, "Project not found")
    await permissions.require_permission(
        session=db, user_id=str(actor), workspace_id=str(workspace), permission=permission,
    )
    await set_rls_subject(db, str(actor))
    return workspace


def _migration_missing(exc: ProgrammingError) -> bool:
    message = str(exc).lower()
    return "media_generation_jobs" in message or "graphytion_claim_media_generation_job" in message or "graphytion_recover_media_generation_jobs" in message or "graphytion_pending_media_reconciliation_jobs" in message


def _migration_required() -> HTTPException:
    return HTTPException(503, "Graphytion media generation runtime migration must be applied before this workflow is available")


def _require_worker(request: Request) -> None:
    configured = settings.internal_worker_token.get_secret_value() if settings.internal_worker_token else ""
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not configured or not supplied or not hmac.compare_digest(configured, supplied):
        raise HTTPException(401, "Internal worker authentication required")


def _validate_config(payload: MediaGenerationCreate) -> dict[str, Any]:
    config = dict(payload.generation_config)
    if payload.media_type == "image":
        if payload.provider_key != "gemini":
            raise HTTPException(422, "Image generation requires the Gemini API-key provider")
        if payload.model_key != "gemini-3.1-flash-image":
            raise HTTPException(422, "Unsupported Gemini image model")
        ratio = config.get("aspect_ratio", "1:1")
        if ratio not in {"1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16"}:
            raise HTTPException(422, "Unsupported image aspect ratio")
        image_size = config.get("image_size", "1K")
        if image_size not in {"512", "1K", "2K", "4K"}:
            raise HTTPException(422, "Unsupported image size")
        config["aspect_ratio"] = ratio
        config["image_size"] = image_size
        config["output_format"] = "png"
    else:
        if payload.provider_key != "gemini":
            raise HTTPException(422, "Video generation requires the Gemini Developer API provider")
        if payload.model_key != "gemini-omni-1.2-flash":
            raise HTTPException(422, "Unsupported Gemini Developer API video model")
        ratio = config.get("aspect_ratio", "16:9")
        duration = config.get("duration_seconds", 8)
        if ratio not in {"16:9", "9:16"} or duration not in range(3, 16):
            raise HTTPException(422, "Gemini Omni 1.2 Flash supports 3-15 second videos")
        resolution = config.get("resolution", "720p")
        if resolution not in {"360p", "720p", "1080p", "4k"}:
            raise HTTPException(422, "Unsupported Gemini Omni 1.2 Flash resolution")
        config.update({"aspect_ratio": ratio, "duration_seconds": duration, "resolution": resolution})
    return config


@router.post("/projects/{project_id}/media-generations", status_code=202)
async def create_media_generation(
    project_id: UUID, payload: MediaGenerationCreate, request: Request,
    claims: AuthenticatedClaims,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace = await _scope(db, project_id, actor, "project.update")
    if not idempotency_key or not 16 <= len(idempotency_key) <= 128:
        raise HTTPException(400, "Idempotency-Key must contain 16-128 characters")
    config = _validate_config(payload)
    try:
        row = (await db.execute(text("""
        insert into public.media_generation_jobs(
          workspace_id,project_id,requested_by,media_type,provider_key,model_key,
          prompt,generation_config,idempotency_key
        ) values (:workspace,:project,:actor,:type,:provider,:model,:prompt,
          cast(:config as jsonb),:key)
        on conflict(workspace_id,idempotency_key) do nothing
        returning id,status,media_type,provider_key,model_key,created_at
        """), {"workspace": workspace, "project": project_id, "actor": actor,
               "type": payload.media_type, "provider": payload.provider_key,
               "model": payload.model_key, "prompt": payload.prompt,
               "config": json.dumps(config), "key": idempotency_key})).mappings().first()
    except ProgrammingError as exc:
        await db.rollback()
        if _migration_missing(exc):
            raise _migration_required() from exc
        raise
    if row is None:
        old = (await db.execute(text("""
            select id,status,media_type,provider_key,model_key,prompt,generation_config
            from public.media_generation_jobs
            where workspace_id=:workspace and idempotency_key=:key
        """), {"workspace": workspace, "key": idempotency_key})).mappings().first()
        if old is None or old["media_type"] != payload.media_type or old["provider_key"] != payload.provider_key or old["model_key"] != payload.model_key or old["prompt"] != payload.prompt or old["generation_config"] != config:
            raise HTTPException(409, "Idempotency key was used for a different media request")
        return {"data": {"generation_id": str(old["id"]), "status": old["status"], "replayed": True}}
    try:
        # Personal Graphytion usage is free: do not reserve or debit user quota.
        # Provider and internal operating costs are tracked separately on the job.
        await db.execute(text("""
            update public.media_generation_jobs
            set quota_debit_microusd=0,quota_reconciliation_status='pending',
                economics_status='unpriced',updated_at=now()
            where id=:id
        """), {"id": row["id"]})
        await db.execute(text("""
            insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id,metadata)
            values(:actor,:workspace,'media_generation.requested','media_generation',:id,:request,cast(:metadata as jsonb))
        """), {"actor": actor, "workspace": workspace, "id": row["id"],
               "request": request.state.request_id,
               "metadata": json.dumps({"media_type": payload.media_type, "provider": payload.provider_key,
                                       "model": payload.model_key, "billing_mode": "free_personal"})})
        await db.commit()
    except Exception:
        await db.rollback()
        raise
    await notify_worker("media", str(row["id"]))
    return {"data": {"generation_id": str(row["id"]), "status": row["status"]}}


@router.get("/projects/{project_id}/media-generations")
async def list_media_generations(project_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = _actor(claims)
    await _scope(db, project_id, actor, "project.read")
    try:
        rows = (await db.execute(text("""
        select id,project_id,media_type,provider_key,model_key,status,error_code,attempt_count,
               retry_count,max_retries,next_retry_at,last_error,last_error_class,provider_operation_status,
               quota_reconciliation_status,provider_job_id as provider_operation_id,asset_id,output_mime_type,output_size_bytes,output_sha256,
               provider_cost_status,provider_cost_microusd,operational_cost_microusd,
               quota_debit_microusd,margin_microusd,economics_status,created_at,started_at,completed_at
        from public.media_generation_jobs where project_id=:project
        order by created_at desc limit 200
        """), {"project": project_id})).mappings().all()
    except ProgrammingError as exc:
        await db.rollback()
        if _migration_missing(exc):
            raise _migration_required() from exc
        raise
    return {"data": [dict(row) for row in rows]}


@router.get("/media-generations/{generation_id}")
async def get_media_generation(generation_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = _actor(claims)
    await set_rls_subject(db, str(actor))
    try:
        row = (await db.execute(text("""
            select * from public.media_generation_jobs where id=:id
        """), {"id": generation_id})).mappings().first()
    except ProgrammingError as exc:
        await db.rollback()
        if _migration_missing(exc):
            raise _migration_required() from exc
        raise
    if row is None:
        raise HTTPException(404, "Media generation not found")
    await _scope(db, row["project_id"], actor, "project.read")
    artifact = None
    if row["asset_id"]:
        asset = (await db.execute(text("""
            select id,bucket,object_path,file_name,content_type,size_bytes,sha256
            from public.project_assets where id=:id and workspace_id=:workspace
              and project_id=:project and status='active'
        """), {"id": row["asset_id"], "workspace": row["workspace_id"], "project": row["project_id"]})).mappings().first()
        if asset:
            artifact = {**dict(asset), "signed_url": await SupabaseStorage().create_signed_url(
                bucket=asset["bucket"], object_path=asset["object_path"], expires_in=300)}
    return {"data": {
        "id": str(row["id"]), "project_id": str(row["project_id"]),
        "media_type": row["media_type"], "provider_key": row["provider_key"],
        "model_key": row["model_key"], "status": row["status"],
        "provider_operation_id": row["provider_job_id"], "provider_operation_status": row["provider_operation_status"],
        "error_code": row["error_code"], "attempt_count": row["attempt_count"],
        "retry_count": row["retry_count"], "max_retries": row["max_retries"], "next_retry_at": row["next_retry_at"],
        "last_error": row["last_error"], "last_error_class": row["last_error_class"],
        "quota_reconciliation_status": row["quota_reconciliation_status"],
        "generation_config": row["generation_config"],
        "provider_provenance": row["provider_provenance"],
        "provider_usage": row["provider_usage"],
        "provider_cost_status": row["provider_cost_status"],
        "provider_cost_microusd": row["provider_cost_microusd"],
        "operational_cost_microusd": row["operational_cost_microusd"],
        "quota_debit_microusd": row["quota_debit_microusd"],
        "margin_microusd": row["margin_microusd"],
        "economics_status": row["economics_status"],
        "created_at": row["created_at"], "completed_at": row["completed_at"],
        "artifact": artifact,
    }}


@router.post("/media-generations/{generation_id}/retry", status_code=202)
async def retry_media_generation(
    generation_id: UUID, request: Request, claims: AuthenticatedClaims,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await set_rls_subject(db, str(actor))
    if not idempotency_key or not 16 <= len(idempotency_key) <= 128:
        raise HTTPException(400, "Idempotency-Key must contain 16-128 characters")
    row = (await db.execute(text("""
        select id,project_id,workspace_id,media_type,status,provider_job_id,provider_operation_status,quota_reservation_id
        from public.media_generation_jobs where id=:id for update
    """), {"id": generation_id})).mappings().first()
    if row is None:
        raise HTTPException(404, "Media generation not found")
    await _scope(db, row["project_id"], actor, "project.update")
    if row["status"] != "failed":
        raise HTTPException(409, "Only failed media generation jobs can be retried")
    if row["provider_job_id"]:
        raise HTTPException(409, "The previous provider operation remains linked; resolve its provider cost and reconciliation before starting a new generation")
    # Free personal mode never creates a new quota reservation. Preserve a
    # pre-existing reservation reference only for legacy jobs pending cost resolution.
    reservation = row["quota_reservation_id"]
    await db.execute(text("""
        update public.media_generation_jobs set status='queued',error_code=null,last_error=null,last_error_class=null,
          attempt_count=0,retry_count=0,next_retry_at=now(),worker_id=null,lease_expires_at=null,
          quota_reservation_id=:reservation,quota_debit_microusd=case when :reservation is null then 0 else quota_debit_microusd end,
          provider_operation_status='not_started',completed_at=null,updated_at=now()
        where id=:id and status='failed'
    """), {"id": generation_id, "reservation": reservation})
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id)
        values(:actor,:workspace,'media_generation.retried','media_generation',:id,:request)
    """), {"actor": actor, "workspace": row["workspace_id"], "id": generation_id,
           "request": request.state.request_id})
    await db.commit()
    await notify_worker("media", str(generation_id))
    return {"data": {"generation_id": str(generation_id), "status": "queued"}}


@router.post("/media-generations/{generation_id}/cancel")
async def cancel_media_generation(generation_id: UUID, request: Request, claims: AuthenticatedClaims,
                                  db: AsyncSession = DbSession):
    actor = _actor(claims)
    await set_rls_subject(db, str(actor))
    row = (await db.execute(text("""
        select id,project_id,workspace_id,status,media_type from public.media_generation_jobs
        where id=:id for update
    """), {"id": generation_id})).mappings().first()
    if row is None:
        raise HTTPException(404, "Media generation not found")
    await _scope(db, row["project_id"], actor, "project.update")
    if row["status"] == "queued":
        await db.execute(text("""
            update public.media_generation_jobs set status='cancelled',completed_at=now(),
              updated_at=now() where id=:id and status='queued'
        """), {"id": generation_id})
        await release_fixed_operation(
            db, resource_type="image_generation" if row["media_type"] == "image" else "video_generation",
            resource_id=generation_id, reason="user_cancelled_before_provider_submission")
        status = "cancelled"
    elif row["status"] == "processing":
        await db.execute(text("""
            update public.media_generation_jobs set status='cancel_requested',updated_at=now()
            where id=:id and status='processing'
        """), {"id": generation_id})
        status = "cancel_requested"
    elif row["status"] in {"cancel_requested", "cancelled"}:
        status = row["status"]
    else:
        raise HTTPException(409, "Only queued or processing media jobs can be cancelled")
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id)
        values(:actor,:workspace,'media_generation.cancel_requested','media_generation',:id,:request)
    """), {"actor": actor, "workspace": row["workspace_id"], "id": generation_id,
           "request": request.state.request_id})
    await db.commit()
    await notify_worker("media", str(generation_id))
    return {"data": {"generation_id": str(generation_id), "status": status}}


@router.post("/internal/media-generation-jobs/recover")
async def recover_media_generation_jobs(request: Request, db: AsyncSession = DbSession):
    _require_worker(request)
    try:
        rows = (await db.execute(text("""
            select * from private.graphytion_recover_media_generation_jobs()
        """))).mappings().all()
        pending = (await db.execute(text("""
            select * from private.graphytion_pending_media_reconciliation_jobs(:limit)
        """), {"limit": 50})).mappings().all()
        reconciled = 0
        for job in pending:
            await set_rls_subject(db, str(job["requested_by"]))
            usage = job["provider_usage"] or {}
            provider_price = None
            provider_cost = int(job["provider_cost_microusd"]) if job["provider_cost_microusd"] is not None else None
            estimated_provider_cost = int(job["estimated_provider_cost_microusd"]) if job["estimated_provider_cost_microusd"] is not None else None
            if provider_cost is None:
                reported = usage.get("provider_cost_microusd", usage.get("cost_microusd"))
                if isinstance(reported, int) and reported >= 0:
                    provider_cost = reported
                else:
                    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", usage.get("total_input_tokens")))
                    output_tokens = usage.get("output_tokens", usage.get("completion_tokens", usage.get("total_output_tokens")))
                    if isinstance(input_tokens, int) and isinstance(output_tokens, int):
                        provider_price = (await db.execute(text("""
                            select id,input_microusd_per_million,output_microusd_per_million
                            from public.ai_model_prices
                            where provider_key=:provider and model_key=:model
                              and is_active=true and effective_at<=now()
                            order by effective_at desc,created_at desc limit 1
                        """), {"provider": job["provider_key"], "model": job["model_key"]})).mappings().first()
                        if provider_price:
                            estimated_provider_cost = round(input_tokens * int(provider_price["input_microusd_per_million"]) / 1000000) + round(output_tokens * int(provider_price["output_microusd_per_million"]) / 1000000)
            cost_price = (await db.execute(text("""
                select id,microusd_per_unit,unit_name,effective_at
                from public.quota_operation_prices
                where price_kind='operational'
                  and operation_key=:operation and media_type=:media
                  and provider_key=:provider and model_key=:model
                  and is_active=true and effective_at<=now()
                order by effective_at desc,created_at desc limit 1
            """), {
                "operation": "image_generation" if job["media_type"] == "image" else "video_generation",
                "media": job["media_type"], "provider": job["provider_key"], "model": job["model_key"],
            })).mappings().first()
            operational_cost = int(job["operational_cost_microusd"]) if job["operational_cost_microusd"] is not None else None
            if operational_cost is None and cost_price:
                units = int((job["generation_config"] or {}).get("duration_seconds", 1)) if job["media_type"] == "video" else 1
                operational_cost = int(cost_price["microusd_per_unit"]) * units
            snapshot = dict(job["price_snapshot"] or {})
            if provider_price:
                snapshot["provider"] = {
                    "id": str(provider_price["id"]),
                    "input_microusd_per_million": int(provider_price["input_microusd_per_million"]),
                    "output_microusd_per_million": int(provider_price["output_microusd_per_million"]),
                }
            if cost_price:
                snapshot["operational"] = {
                    "id": str(cost_price["id"]), "microusd_per_unit": int(cost_price["microusd_per_unit"]),
                    "unit_name": cost_price["unit_name"], "effective_at": cost_price["effective_at"].isoformat(),
                }
            await db.execute(text("""
                update public.media_generation_jobs set
                  provider_cost_microusd=coalesce(:provider_cost,provider_cost_microusd),
                  estimated_provider_cost_microusd=coalesce(:estimated,estimated_provider_cost_microusd),
                  provider_cost_status=case when coalesce(:provider_cost,provider_cost_microusd) is null then 'unpriced' else 'priced' end,
                  provider_price_id=coalesce(:provider_price_id,provider_price_id),
                  operational_cost_microusd=coalesce(:operational,operational_cost_microusd),
                  operational_price_id=coalesce(:operational_price_id,operational_price_id),
                  quota_debit_microusd=0,margin_microusd=null,
                  economics_status=case
                    when coalesce(:provider_cost,provider_cost_microusd) is not null
                      and coalesce(:operational,operational_cost_microusd) is not null then 'complete'
                    when coalesce(:estimated,estimated_provider_cost_microusd) is not null
                      or coalesce(:provider_cost,provider_cost_microusd) is not null
                      or coalesce(:operational,operational_cost_microusd) is not null then 'partial'
                    else 'unpriced' end,
                  quota_reconciliation_status=case
                    when coalesce(:provider_cost,provider_cost_microusd) is not null
                      and coalesce(:operational,operational_cost_microusd) is not null then 'complete'
                    else 'pending' end,
                  quota_reconciled_at=case
                    when coalesce(:provider_cost,provider_cost_microusd) is not null
                      and coalesce(:operational,operational_cost_microusd) is not null then now()
                    else null end,
                  price_snapshot=cast(:snapshot as jsonb),updated_at=now()
                where id=:id
            """), {
                "provider_cost": provider_cost, "estimated": estimated_provider_cost,
                "provider_price_id": provider_price["id"] if provider_price else None,
                "operational": operational_cost, "operational_price_id": cost_price["id"] if cost_price else None,
                "snapshot": json.dumps(snapshot), "id": job["id"],
            })
            # A legacy quota hold is released only when actual provider cost is known.
            if provider_cost is not None and job["quota_reservation_id"] is not None:
                await release_fixed_operation(
                    db, resource_type="image_generation" if job["media_type"] == "image" else "video_generation",
                    resource_id=job["id"], reason="free_personal_mode_provider_cost_resolved",
                )
            if provider_cost is None or operational_cost is None:
                continue
            quota_debit = 0
            margin = None
            snapshot = dict(job["price_snapshot"] or {})
            if provider_price:
                snapshot["provider"] = {
                    "id": str(provider_price["id"]),
                    "input_microusd_per_million": int(provider_price["input_microusd_per_million"]),
                    "output_microusd_per_million": int(provider_price["output_microusd_per_million"]),
                }
            if cost_price:
                snapshot["operational"] = {
                    "id": str(cost_price["id"]), "microusd_per_unit": int(cost_price["microusd_per_unit"]),
                    "unit_name": cost_price["unit_name"], "effective_at": cost_price["effective_at"].isoformat(),
                }
            await db.execute(text("""
                update public.media_generation_jobs set
                  provider_cost_microusd=:provider_cost,
                  estimated_provider_cost_microusd=coalesce(:estimated_provider_cost,estimated_provider_cost_microusd),
                  provider_cost_status=case when :provider_cost is null then 'unpriced' else 'priced' end,
                  provider_price_id=coalesce(:provider_price_id,provider_price_id),
                  operational_cost_microusd=:operational_cost,
                  operational_price_id=coalesce(:operational_price_id,operational_price_id),
                  quota_debit_microusd=0,margin_microusd=null,
                  economics_status=case when :provider_cost is not null then 'complete' else 'partial' end,
                  quota_reconciliation_status=case when :provider_cost is not null then 'complete' else 'pending' end,
                  quota_reconciled_at=case when :provider_cost is not null then now() else null end,
                  price_snapshot=cast(:snapshot as jsonb),updated_at=now()
                where id=:id
            """), {
                "provider_cost": provider_cost, "estimated_provider_cost": estimated_provider_cost,
                "provider_price_id": provider_price["id"] if provider_price else None,
                "operational_cost": operational_cost, "operational_price_id": cost_price["id"] if cost_price else None,
                "quota_debit": quota_debit, "margin": margin, "snapshot": json.dumps(snapshot), "id": job["id"],
            })
            reconciled += 1
        await db.commit()
    except ProgrammingError as exc:
        await db.rollback()
        if _migration_missing(exc):
            return {"data": {"recovered": 0, "reconciled": 0, "migration_required": True}}
        raise
    return {"data": {"recovered": len(rows), "reconciled": reconciled, "jobs": [
        {"generation_id": str(row["job_id"]), "status": row["job_status"]} for row in rows
    ]}}


@router.post("/internal/media-generation-jobs/claim")
async def claim_media_generation_job(request: Request, worker_id: str = Query(min_length=1, max_length=128),
                                     db: AsyncSession = DbSession):
    _require_worker(request)
    try:
        row = (await db.execute(text("""
            select * from private.graphytion_claim_media_generation_job(:worker)
        """), {"worker": worker_id})).mappings().first()
    except ProgrammingError as exc:
        await db.rollback()
        if _migration_missing(exc):
            return {"data": None, "migration_required": True}
        raise
    if row is None:
        await db.rollback()
        return {"data": None}
    await set_rls_subject(db, str(row["requested_by"]))
    await db.commit()
    return {"data": {
        "id": str(row["id"]), "project_id": str(row["project_id"]),
        "workspace_id": str(row["workspace_id"]), "requested_by": str(row["requested_by"]),
        "media_type": row["media_type"], "provider_key": row["provider_key"],
        "model_key": row["model_key"], "prompt": row["prompt"],
        "generation_config": row["generation_config"], "attempt_count": row["attempt_count"],
        "provider_job_id": row["provider_job_id"],
    }}


@router.post("/internal/media-generation-jobs/{generation_id}/heartbeat")
async def heartbeat_media_generation_job(generation_id: UUID, request: Request,
                                          worker_id: str = Query(min_length=1, max_length=128),
                                          db: AsyncSession = DbSession):
    _require_worker(request)
    status = (await db.execute(text("""
        select * from private.graphytion_media_generation_status(:id,:worker)
    """), {"id": generation_id, "worker": worker_id})).mappings().first()
    if status is None:
        raise HTTPException(409, "Media generation lease is no longer owned")
    if status["status"] == "processing":
        await db.execute(text("select private.graphytion_heartbeat_media_generation_job(:id,:worker)"),
                         {"id": generation_id, "worker": worker_id})
        await db.execute(text("""
            update public.media_generation_jobs
            set provider_operation_last_polled_at=case when provider_job_id is not null then now() else provider_operation_last_polled_at end,
                provider_operation_poll_count=provider_operation_poll_count + case when provider_job_id is not null then 1 else 0 end,
                updated_at=now()
            where id=:id and worker_id=:worker
        """), {"id": generation_id, "worker": worker_id})
    await set_rls_subject(db, str(status["requested_by"]))
    await db.commit()
    return {"data": {"generation_id": str(generation_id), "cancel_requested": status["status"] == "cancel_requested",
                     "status": status["status"]}}


@router.post("/internal/media-generation-jobs/{generation_id}/provider-operation")
async def save_media_provider_operation(
    generation_id: UUID, request: Request, payload: dict[str, str],
    worker_id: str = Query(min_length=1, max_length=128), db: AsyncSession = DbSession,
):
    _require_worker(request)
    operation_id = (payload.get("provider_operation_id") or "").strip()
    if not operation_id or len(operation_id) > 256:
        raise HTTPException(422, "Invalid Gemini interaction ID")
    owner = await db.scalar(
        text("select private.graphytion_media_generation_owner(:id,:worker)"),
        {"id": generation_id, "worker": worker_id},
    )
    if owner is None:
        raise HTTPException(409, "Media generation lease is no longer owned")
    await set_rls_subject(db, str(owner))
    result = await db.execute(text("""
        update public.media_generation_jobs
        set provider_job_id=:operation,provider_operation_status='submitted',updated_at=now()
        where id=:id and worker_id=:worker and status in ('processing','cancel_requested')
          and provider_key='gemini'
        returning id
    """), {"operation": operation_id, "id": generation_id, "worker": worker_id})
    if result.scalar_one_or_none() is None:
        raise HTTPException(409, "Media generation is no longer eligible for provider tracking")
    await db.commit()
    return {"data": {"generation_id": str(generation_id), "provider_operation_id": operation_id}}


@router.post("/internal/media-generation-jobs/{generation_id}/failed")
async def fail_media_generation_job(generation_id: UUID, payload: MediaGenerationFailure,
                                    request: Request, worker_id: str = Query(min_length=1, max_length=128),
                                    db: AsyncSession = DbSession):
    _require_worker(request)
    owner = await db.scalar(text("select private.graphytion_media_generation_owner(:id,:worker)"), {"id": generation_id, "worker": worker_id})
    if owner is None:
        raise HTTPException(409, "Media generation lease is no longer owned")
    await set_rls_subject(db, str(owner))
    row = (await db.execute(text("""
        select id,requested_by,workspace_id,media_type,attempt_count,max_attempts,retry_count,max_retries,status,provider_job_id,provider_operation_status
        from public.media_generation_jobs where id=:id and worker_id=:worker for update
    """), {"id": generation_id, "worker": worker_id})).mappings().first()
    if row is None:
        raise HTTPException(409, "Media generation lease is no longer owned")
    if row["status"] == "cancel_requested":
        await db.execute(text("""
            update public.media_generation_jobs set status='cancelled',completed_at=now(),
              worker_id=null,lease_expires_at=null,updated_at=now() where id=:id
        """), {"id": generation_id})
        await db.execute(text("""
            update public.media_generation_jobs
            set error_code='CANCELLED_PROVIDER_OUTCOME_UNKNOWN',updated_at=now()
            where id=:id
        """), {"id": generation_id})
        status = "cancelled"
    else:
        terminal_provider_failure = payload.error_code in {"GEMINI_INTERACTION_FAILED", "GEMINI_INTERACTION_CANCELLED", "GEMINI_VIDEO_FAILED", "GEMINI_VIDEO_CANCELLED"}
        status = "failed" if terminal_provider_failure else ("queued" if payload.retryable and row["attempt_count"] < row["max_attempts"] and row["retry_count"] < row["max_retries"] else "failed")
        await db.execute(text("""
            update public.media_generation_jobs set status=:status,error_code=:error,last_error=:error,
              last_error_class=case when :error like '%NOT_CONFIGURED%' or :error like '%UNSUPPORTED%' then 'configuration' when :status='queued' then 'transient' else 'permanent' end,
              retry_count=retry_count + case when :status='queued' then 1 else 0 end,
              next_retry_at=case when :status='queued' then now()+make_interval(secs => least(300,(5*power(2,least(attempt_count,6)))::integer)) else null end,
              provider_operation_status=case when provider_job_id is not null and :error in ('GEMINI_INTERACTION_FAILED','GEMINI_INTERACTION_CANCELLED','GEMINI_VIDEO_FAILED','GEMINI_VIDEO_CANCELLED') then 'failed' when provider_job_id is not null then 'unknown' when :status='failed' then 'failed' else 'not_started' end,
              worker_id=null,lease_expires_at=null,
              completed_at=case when :status='failed' then now() else null end,updated_at=now()
            where id=:id
        """), {"id": generation_id, "status": status, "error": payload.error_code})
        # Keep reservations open after provider attempts: a timeout or terminal error
        # does not prove that the provider incurred zero billable cost. Reconciliation
        # or an explicit pre-provider cancellation is the only release path.
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id,metadata)
        values(:actor,:workspace,'media_generation.failed','media_generation',:id,:request,cast(:metadata as jsonb))
    """), {"actor": row["requested_by"], "workspace": row["workspace_id"], "id": generation_id,
           "request": request.state.request_id, "metadata": json.dumps({"error_code": payload.error_code, "status": status})})
    await db.commit()
    return {"data": {"generation_id": str(generation_id), "status": status}}


@router.post("/internal/media-generation-jobs/{generation_id}/cancelled")
async def complete_media_generation_cancel(generation_id: UUID, request: Request,
                                            worker_id: str = Query(min_length=1, max_length=128),
                                            db: AsyncSession = DbSession):
    _require_worker(request)
    owner = await db.scalar(text("select private.graphytion_media_generation_owner(:id,:worker)"), {"id": generation_id, "worker": worker_id})
    if owner is None:
        raise HTTPException(409, "Media cancellation is no longer pending")
    await set_rls_subject(db, str(owner))
    row = (await db.execute(text("""
        select requested_by,workspace_id,media_type,status from public.media_generation_jobs
        where id=:id and worker_id=:worker for update
    """), {"id": generation_id, "worker": worker_id})).mappings().first()
    if row is None or row["status"] != "cancel_requested":
        raise HTTPException(409, "Media cancellation is no longer pending")
    await db.execute(text("""
        update public.media_generation_jobs set status='cancelled',completed_at=now(),
          worker_id=null,lease_expires_at=null,updated_at=now() where id=:id
    """), {"id": generation_id})
    # Keep the reservation open: the provider may continue processing after the
    # client connection is cancelled, so its billable outcome is not yet known.
    await db.execute(text("""
        update public.media_generation_jobs
        set error_code='CANCELLED_PROVIDER_OUTCOME_UNKNOWN',updated_at=now()
        where id=:id
    """), {"id": generation_id})
    await db.commit()
    return {"data": {"generation_id": str(generation_id), "status": "cancelled"}}


@router.post("/internal/media-generation-jobs/{generation_id}/artifact", status_code=201)
async def complete_media_generation_artifact(
    generation_id: UUID, request: Request, file: UploadFile,
    provider_provenance: str = Form(...), provider_usage: str | None = Form(default=None),
    worker_id: str = Query(min_length=1, max_length=128), db: AsyncSession = DbSession,
):
    _require_worker(request)
    owner = await db.scalar(text("select private.graphytion_media_generation_owner(:id,:worker)"), {"id": generation_id, "worker": worker_id})
    if owner is None:
        raise HTTPException(409, "Media generation lease is no longer owned")
    await set_rls_subject(db, str(owner))
    row = (await db.execute(text("""
        select * from public.media_generation_jobs where id=:id and worker_id=:worker
          and status='processing' for update
    """), {"id": generation_id, "worker": worker_id})).mappings().first()
    if row is None:
        raise HTTPException(409, "Media generation lease is no longer owned")
    maximum = MAX_IMAGE_BYTES if row["media_type"] == "image" else MAX_VIDEO_BYTES
    content = await file.read(maximum + 1)
    if not content or len(content) > maximum:
        raise HTTPException(413, "Generated media artifact exceeds its allowed size")
    mime = file.content_type or ""
    if row["media_type"] == "image":
        valid = ((mime == "image/png" and content.startswith(b"\x89PNG\r\n\x1a\n"))
                 or (mime == "image/jpeg" and content.startswith(b"\xff\xd8\xff"))
                 or (mime == "image/webp" and len(content) > 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"))
        suffix = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}.get(mime)
    else:
        valid = mime == "video/mp4" and len(content) > 12 and content[4:8] == b"ftyp"
        suffix = "mp4" if valid else None
    if not valid or not suffix:
        raise HTTPException(415, "Provider output MIME or file signature is invalid")
    try:
        provenance = json.loads(provider_provenance)
        usage = json.loads(provider_usage) if provider_usage else None
    except (TypeError, ValueError) as exc:
        raise HTTPException(422, "Provider provenance or usage JSON is invalid") from exc
    if not isinstance(provenance, dict) or (usage is not None and not isinstance(usage, dict)):
        raise HTTPException(422, "Provider provenance and usage must be JSON objects")
    asset_id = uuid4()
    digest = hashlib.sha256(content).hexdigest()
    path = f"{row['workspace_id']}/{row['project_id']}/{asset_id}.{suffix}"
    await SupabaseStorage().upload(
        bucket=BUCKET, object_path=path, content=content, content_type=mime,
        upsert=False, timeout_seconds=600,
    )
    try:
        await db.execute(text("""
            insert into public.project_assets(
              id,workspace_id,project_id,uploaded_by,bucket,object_path,file_name,
              content_type,size_bytes,sha256,source_type,source_provider,source_model,source_job_id,
              provenance,generation_metadata,usage_rights_status,generated_at
            ) values(:id,:workspace,:project,:actor,:bucket,:path,:name,:mime,:size,:sha,
              'generated',:provider,:model,:job,cast(:provenance as jsonb),cast(:generation_metadata as jsonb),'unverified',now())
        """), {"id": asset_id, "workspace": row["workspace_id"], "project": row["project_id"],
               "actor": owner, "bucket": BUCKET, "path": path,
               "name": f"generated-{generation_id}.{suffix}", "mime": mime,
               "size": len(content), "sha": digest, "provider": row["provider_key"], "model": row["model_key"],
               "job": generation_id, "provenance": json.dumps(provenance),
               "generation_metadata": json.dumps({"prompt_sha256": hashlib.sha256(row["prompt"].encode("utf-8")).hexdigest(), "generation_config": row["generation_config"]})})
        provider_cost = None
        estimated_provider_cost = None
        provider_price = None
        if usage:
            reported_cost = usage.get("provider_cost_microusd", usage.get("cost_microusd"))
            if isinstance(reported_cost, int) and reported_cost >= 0:
                provider_cost = reported_cost
            input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", usage.get("total_input_tokens")))
            output_tokens = usage.get("output_tokens", usage.get("completion_tokens", usage.get("total_output_tokens")))
            if isinstance(input_tokens, int) and isinstance(output_tokens, int):
                provider_price = (await db.execute(text("""
                    select id,input_microusd_per_million,output_microusd_per_million
                    from public.ai_model_prices where provider_key=:provider and model_key=:model
                      and is_active=true and effective_at<=now()
                    order by effective_at desc,created_at desc limit 1
                """), {"provider": row["provider_key"], "model": row["model_key"]})).mappings().first()
                if provider_price:
                    estimated_provider_cost = round(input_tokens * int(provider_price["input_microusd_per_million"]) / 1000000) + round(output_tokens * int(provider_price["output_microusd_per_million"]) / 1000000)
        await db.execute(text("""
            update public.media_generation_jobs set status='completed',asset_id=:asset,
              output_mime_type=:mime,output_size_bytes=:size,output_sha256=:sha,
              provider_provenance=cast(:provenance as jsonb),
              provider_usage=cast(:usage as jsonb),
              provider_cost_microusd=:provider_cost,
              estimated_provider_cost_microusd=:estimated_provider_cost,
              provider_cost_status=case when :provider_cost is null then 'unpriced' else 'priced' end,
              provider_operation_status='completed',provider_operation_last_polled_at=now(),
              completed_at=now(),worker_id=null,lease_expires_at=null,updated_at=now()
            where id=:id and status='processing' and worker_id=:worker
        """), {"asset": asset_id, "mime": mime, "size": len(content), "sha": digest,
               "provenance": json.dumps(provenance), "usage": json.dumps(usage) if usage else None,
               "provider_cost": provider_cost, "estimated_provider_cost": estimated_provider_cost,
               "id": generation_id, "worker": worker_id})
        if provider_cost is not None and row["quota_reservation_id"] is not None:
            await release_fixed_operation(
                db, resource_type="image_generation" if row["media_type"] == "image" else "video_generation",
                resource_id=generation_id, reason="free_personal_mode_provider_cost_resolved",
            )
        quota_debit = 0
        cost_price = (await db.execute(text("""
            select id,microusd_per_unit,unit_name,effective_at
            from public.quota_operation_prices
            where price_kind='operational' and operation_key=:operation
              and media_type=:type and provider_key=:provider and model_key=:model
              and is_active=true and effective_at<=now()
            order by effective_at desc,created_at desc limit 1
        """), {"operation": "image_generation" if row["media_type"] == "image" else "video_generation",
               "type": row["media_type"], "provider": row["provider_key"],
               "model": row["model_key"]})).mappings().first()
        operational_cost = None
        if cost_price:
            units = int((row["generation_config"] or {}).get("duration_seconds", 1)) if row["media_type"] == "video" else 1
            operational_cost = int(cost_price["microusd_per_unit"]) * units
        margin = None
        economics_status = "complete" if provider_cost is not None and operational_cost is not None else ("partial" if estimated_provider_cost is not None or provider_cost is not None or operational_cost is not None else "unpriced")
        await db.execute(text("""
            update public.media_generation_jobs set operational_cost_microusd=:operational,
              quota_debit_microusd=:debit,margin_microusd=:margin,economics_status=:economics,
              provider_price_id=:provider_price_id,operational_price_id=:operational_price_id,
              price_snapshot=cast(:price_snapshot as jsonb),
              quota_reconciliation_status=case when :reconciled then 'complete' else 'pending' end,
              quota_reconciled_at=case when :reconciled then now() else null end,
              currency='USD'
            where id=:id
        """), {"operational": operational_cost, "debit": quota_debit, "margin": margin,
               "economics": economics_status, "id": generation_id,
               "provider_price_id": provider_price["id"] if provider_price else None,
               "operational_price_id": cost_price["id"] if cost_price else None,
               "price_snapshot": json.dumps({
                   "provider": ({"id": str(provider_price["id"]), "input_microusd_per_million": int(provider_price["input_microusd_per_million"]), "output_microusd_per_million": int(provider_price["output_microusd_per_million"]) } if provider_price else None),
                   "operational": ({"id": str(cost_price["id"]), "microusd_per_unit": int(cost_price["microusd_per_unit"]), "unit_name": cost_price["unit_name"], "effective_at": cost_price["effective_at"].isoformat()} if cost_price else None)
               }),
               "reconciled": provider_cost is not None and operational_cost is not None})
        await db.execute(text("""
            insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id,metadata)
            values(:actor,:workspace,'media_generation.completed','media_generation',:id,:request,cast(:metadata as jsonb))
        """), {"actor": owner, "workspace": row["workspace_id"], "id": generation_id,
               "request": request.state.request_id, "metadata": json.dumps({"asset_id": str(asset_id), "size_bytes": len(content), "mime_type": mime})})
        await db.commit()
    except Exception:
        await db.rollback()
        try:
            await SupabaseStorage().remove(bucket=BUCKET, object_path=path)
        except Exception:
            pass
        raise
    return {"data": {"generation_id": str(generation_id), "asset_id": str(asset_id),
                     "status": "completed", "size_bytes": len(content), "mime_type": mime}}
