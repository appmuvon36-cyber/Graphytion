from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, File, Form, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims, DbSession
from app.core.config import settings
from app.core.database import set_rls_subject
from app.services.workspace_authorization import WorkspacePermissionResolver
from app.services.supabase_storage import SupabaseStorage
from app.services.queue_notifications import notify_worker
from app.services.quota import reserve_fixed_operation, reconcile_fixed_operation, release_fixed_operation

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


def _require_worker(request: Request) -> None:
    configured = settings.internal_worker_token.get_secret_value() if settings.internal_worker_token else ""
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not configured or not supplied or not hmac.compare_digest(configured, supplied):
        raise HTTPException(401, "Internal worker authentication required")


def _validate_config(payload: MediaGenerationCreate) -> dict[str, Any]:
    config = dict(payload.generation_config)
    if payload.media_type == "image":
        if payload.model_key != "gemini-3.1-flash-image":
            raise HTTPException(422, "Unsupported Gemini image model")
        ratio = config.get("aspect_ratio", "1:1")
        if ratio not in {"1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16"}:
            raise HTTPException(422, "Unsupported image aspect ratio")
        config["aspect_ratio"] = ratio
        config["output_format"] = "png"
    else:
        if payload.model_key not in {"gemini-omni-1.2-flash", "gemini-omni-1.1-flash"}:
            raise HTTPException(422, "Unsupported Gemini video model")
        ratio = config.get("aspect_ratio", "16:9")
        duration = config.get("duration_seconds", 8)
        resolution = config.get("resolution", "720p")
        if ratio not in {"16:9", "9:16"} or duration not in range(3, 16):
            raise HTTPException(422, "Unsupported video aspect ratio or duration")
        if resolution not in {"360p", "720p", "1080p", "4k"}:
            raise HTTPException(422, "Unsupported video resolution")
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
    if row is None:
        old = (await db.execute(text("""
            select id,status,media_type,provider_key,model_key,prompt,generation_config
            from public.media_generation_jobs
            where workspace_id=:workspace and idempotency_key=:key
        """), {"workspace": workspace, "key": idempotency_key})).mappings().first()
        if old is None or old["media_type"] != payload.media_type or old["provider_key"] != payload.provider_key or old["model_key"] != payload.model_key or old["prompt"] != payload.prompt or old["generation_config"] != config:
            raise HTTPException(409, "Idempotency key was used for a different media request")
        return {"data": {"generation_id": str(old["id"]), "status": old["status"], "replayed": True}}
    operation = "image_generation" if payload.media_type == "image" else "video_generation"
    try:
        reservation = await reserve_fixed_operation(
            db, workspace_id=workspace, project_id=project_id,
            resource_type="image_generation" if payload.media_type == "image" else "video_generation",
            resource_id=row["id"], operation_key=operation, units=1,
            idempotency_key=f"media-generation:{row['id']}:initial",
        )
        await db.execute(text("""
            update public.media_generation_jobs set quota_reservation_id=:reservation where id=:id
        """), {"reservation": reservation, "id": row["id"]})
        await db.execute(text("""
            insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id,metadata)
            values(:actor,:workspace,'media_generation.requested','media_generation',:id,:request,cast(:metadata as jsonb))
        """), {"actor": actor, "workspace": workspace, "id": row["id"],
               "request": request.state.request_id,
               "metadata": json.dumps({"media_type": payload.media_type, "provider": payload.provider_key, "model": payload.model_key})})
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
    rows = (await db.execute(text("""
        select id,project_id,media_type,provider_key,model_key,status,error_code,attempt_count,
               asset_id,output_mime_type,output_size_bytes,output_sha256,
               provider_cost_status,provider_cost_microusd,operational_cost_microusd,
               quota_debit_microusd,margin_microusd,economics_status,created_at,started_at,completed_at
        from public.media_generation_jobs where project_id=:project
        order by created_at desc limit 200
    """), {"project": project_id})).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.get("/media-generations/{generation_id}")
async def get_media_generation(generation_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = _actor(claims)
    await set_rls_subject(db, str(actor))
    row = (await db.execute(text("""
        select * from public.media_generation_jobs where id=:id
    """), {"id": generation_id})).mappings().first()
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
        "error_code": row["error_code"], "attempt_count": row["attempt_count"],
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
        select id,project_id,workspace_id,media_type,status
        from public.media_generation_jobs where id=:id for update
    """), {"id": generation_id})).mappings().first()
    if row is None:
        raise HTTPException(404, "Media generation not found")
    await _scope(db, row["project_id"], actor, "project.update")
    if row["status"] != "failed":
        raise HTTPException(409, "Only failed media generation jobs can be retried")
    operation = "image_generation" if row["media_type"] == "image" else "video_generation"
    resource_type = operation
    reservation = await reserve_fixed_operation(
        db, workspace_id=row["workspace_id"], project_id=row["project_id"],
        resource_type=resource_type, resource_id=generation_id,
        operation_key=operation, units=1,
        idempotency_key=f"media-generation:{generation_id}:retry:{idempotency_key}",
    )
    await db.execute(text("""
        update public.media_generation_jobs set status='queued',error_code=null,
          attempt_count=0,max_attempts=3,worker_id=null,lease_expires_at=null,
          quota_reservation_id=:reservation,completed_at=null,updated_at=now()
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
    rows = (await db.execute(text("""
        select * from private.graphytion_recover_media_generation_jobs()
    """))).mappings().all()
    await db.commit()
    return {"data": {"recovered": len(rows), "jobs": [
        {"generation_id": str(row["job_id"]), "status": row["job_status"]} for row in rows
    ]}}


@router.post("/internal/media-generation-jobs/claim")
async def claim_media_generation_job(request: Request, worker_id: str = Query(min_length=1, max_length=128),
                                     db: AsyncSession = DbSession):
    _require_worker(request)
    row = (await db.execute(text("""
        select * from private.graphytion_claim_media_generation_job(:worker)
    """), {"worker": worker_id})).mappings().first()
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
    await set_rls_subject(db, str(status["requested_by"]))
    await db.commit()
    return {"data": {"generation_id": str(generation_id), "cancel_requested": status["status"] == "cancel_requested",
                     "status": status["status"]}}


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
        select id,requested_by,workspace_id,media_type,attempt_count,max_attempts,status
        from public.media_generation_jobs where id=:id and worker_id=:worker for update
    """), {"id": generation_id, "worker": worker_id})).mappings().first()
    if row is None:
        raise HTTPException(409, "Media generation lease is no longer owned")
    if row["status"] == "cancel_requested":
        await db.execute(text("""
            update public.media_generation_jobs set status='cancelled',completed_at=now(),
              worker_id=null,lease_expires_at=null,updated_at=now() where id=:id
        """), {"id": generation_id})
        await release_fixed_operation(
            db, resource_type="image_generation" if row["media_type"] == "image" else "video_generation",
            resource_id=generation_id, reason="cancelled_during_provider_execution")
        status = "cancelled"
    else:
        status = "queued" if payload.retryable and row["attempt_count"] < row["max_attempts"] else "failed"
        await db.execute(text("""
            update public.media_generation_jobs set status=:status,error_code=:error,
              worker_id=null,lease_expires_at=null,
              completed_at=case when :status='failed' then now() else null end,updated_at=now()
            where id=:id
        """), {"id": generation_id, "status": status, "error": payload.error_code})
        if status == "failed":
            await release_fixed_operation(
                db, resource_type="image_generation" if row["media_type"] == "image" else "video_generation",
                resource_id=generation_id, reason=payload.error_code)
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
    row = (await db.execute(text("""
        select * from public.media_generation_jobs where id=:id and worker_id=:worker
          and status='processing' for update
    """), {"id": generation_id, "worker": worker_id})).mappings().first()
    await set_rls_subject(db, str(owner))
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
              content_type,size_bytes,sha256
            ) values(:id,:workspace,:project,:actor,:bucket,:path,:name,:mime,:size,:sha)
        """), {"id": asset_id, "workspace": row["workspace_id"], "project": row["project_id"],
               "actor": owner, "bucket": BUCKET, "path": path,
               "name": f"generated-{generation_id}.{suffix}", "mime": mime,
               "size": len(content), "sha": digest})
        provider_cost = None
        if usage:
            input_tokens = usage.get("input_tokens", usage.get("prompt_tokens", usage.get("total_input_tokens")) )
            output_tokens = usage.get("output_tokens", usage.get("completion_tokens", usage.get("total_output_tokens")) )
            if isinstance(input_tokens, int) and isinstance(output_tokens, int):
                price = (await db.execute(text("""
                    select id,input_microusd_per_million,output_microusd_per_million
                    from public.ai_model_prices where provider_key=:provider and model_key=:model
                      and is_active=true and effective_at<=now()
                    order by effective_at desc,created_at desc limit 1
                """), {"provider": row["provider_key"], "model": row["model_key"]})).mappings().first()
                if price:
                    provider_cost = round(input_tokens * int(price["input_microusd_per_million"]) / 1000000) + round(output_tokens * int(price["output_microusd_per_million"]) / 1000000)
        await db.execute(text("""
            update public.media_generation_jobs set status='completed',asset_id=:asset,
              output_mime_type=:mime,output_size_bytes=:size,output_sha256=:sha,
              provider_provenance=cast(:provenance as jsonb),
              provider_usage=cast(:usage as jsonb),
              provider_cost_microusd=:provider_cost,
              provider_cost_status=case when :provider_cost is null then 'unpriced' else 'priced' end,
              completed_at=now(),worker_id=null,lease_expires_at=null,updated_at=now()
            where id=:id and status='processing' and worker_id=:worker
        """), {"asset": asset_id, "mime": mime, "size": len(content), "sha": digest,
               "provenance": json.dumps(provenance), "usage": json.dumps(usage) if usage else None,
               "provider_cost": provider_cost, "id": generation_id, "worker": worker_id})
        await reconcile_fixed_operation(
            db, resource_type="image_generation" if row["media_type"] == "image" else "video_generation",
            resource_id=generation_id,
        )
        reservation = (await db.execute(text("""
            select consumed_microusd from public.quota_reservations
            where id=:id and status='consumed'
        """), {"id": row["quota_reservation_id"]})).mappings().first() if row["quota_reservation_id"] else None
        quota_debit = int(reservation["consumed_microusd"]) if reservation else None
        cost_price = (await db.execute(text("""
            select microusd_per_unit,unit_name
            from public.media_operational_cost_prices
            where media_type=:type and provider_key=:provider and model_key=:model
              and is_active=true and effective_at<=now()
            order by effective_at desc,created_at desc limit 1
        """), {"type": row["media_type"], "provider": row["provider_key"],
               "model": row["model_key"]})).mappings().first()
        operational_cost = None
        if cost_price:
            units = int((row["generation_config"] or {}).get("duration_seconds", 1)) if row["media_type"] == "video" else 1
            operational_cost = int(cost_price["microusd_per_unit"]) * units
        margin = quota_debit - provider_cost - operational_cost if quota_debit is not None and provider_cost is not None and operational_cost is not None else None
        economics_status = "complete" if margin is not None else ("partial" if any(value is not None for value in (quota_debit, provider_cost, operational_cost)) else "unpriced")
        await db.execute(text("""
            update public.media_generation_jobs set operational_cost_microusd=:operational,
              quota_debit_microusd=:debit,margin_microusd=:margin,economics_status=:economics
            where id=:id
        """), {"operational": operational_cost, "debit": quota_debit, "margin": margin,
               "economics": economics_status, "id": generation_id})
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
