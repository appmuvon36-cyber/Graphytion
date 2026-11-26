from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims, DbSession
from app.core.config import settings
from app.core.database import set_rls_subject
from app.core.redis import redis_client
from app.services.supabase_storage import SupabaseStorage
from app.services.workspace_authorization import WorkspacePermissionResolver

router = APIRouter()
permissions = WorkspacePermissionResolver()
RENDER_STREAM = "graphytion:render:jobs"
RENDER_BUCKET = "render-artifacts"
MAX_RENDER_BYTES = 1024 * 1024 * 1024
ALLOWED_COMPONENTS = {"core.title-card.v1"}


class RenderCreate(BaseModel):
    snapshot: dict[str, Any]
    codec: str = Field(default="h264", pattern=r"^h264$")
    composition_version: str = Field(default="1.0.0", min_length=1, max_length=32)


class RenderProgress(BaseModel):
    progress_percent: float = Field(ge=0, lt=100)


class RenderFailure(BaseModel):
    error_code: str = Field(min_length=1, max_length=100)
    error_message: str = Field(min_length=1, max_length=500)
    retryable: bool = False


def _actor(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid authenticated subject") from exc


async def _project_workspace(db: AsyncSession, project_id: UUID, actor: UUID, permission: str) -> UUID:
    workspace_id = await db.scalar(text("""
        select workspace_id from public.video_projects
        where id=:project and status <> 'deleted'
    """), {"project": project_id})
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await permissions.require_permission(
        session=db, user_id=str(actor), workspace_id=str(workspace_id), permission=permission
    )
    return workspace_id


def _validate_snapshot(snapshot: dict[str, Any]) -> str:
    required = {"version", "fps", "width", "height", "durationFrames", "clips"}
    if not required.issubset(snapshot):
        raise HTTPException(status_code=422, detail="Timeline snapshot is missing required fields")
    fps, width, height, duration = (
        snapshot.get("fps"), snapshot.get("width"), snapshot.get("height"), snapshot.get("durationFrames")
    )
    if not isinstance(fps, int) or not 1 <= fps <= 120:
        raise HTTPException(status_code=422, detail="Unsupported timeline FPS")
    if not isinstance(width, int) or not 320 <= width <= 7680:
        raise HTTPException(status_code=422, detail="Invalid timeline width")
    if not isinstance(height, int) or not 240 <= height <= 4320:
        raise HTTPException(status_code=422, detail="Invalid timeline height")
    if not isinstance(duration, int) or not 1 <= duration <= fps * 60 * 30:
        raise HTTPException(status_code=422, detail="Timeline duration exceeds 30 minutes")
    clips = snapshot.get("clips")
    if not isinstance(clips, list) or len(clips) > 500:
        raise HTTPException(status_code=422, detail="Timeline clips must be a list of at most 500 items")
    clip_ids: set[str] = set()
    for clip in clips:
        if not isinstance(clip, dict):
            raise HTTPException(status_code=422, detail="Invalid timeline clip")
        clip_id = clip.get("id")
        start = clip.get("startFrame")
        length = clip.get("durationFrames")
        if not isinstance(clip_id, str) or not clip_id or clip_id in clip_ids:
            raise HTTPException(status_code=422, detail="Timeline clip IDs must be unique")
        clip_ids.add(clip_id)
        if not isinstance(start, int) or start < 0 or not isinstance(length, int) or length < 1 or start + length > duration:
            raise HTTPException(status_code=422, detail="Timeline clip frame range is invalid")
        component = clip.get("componentKey")
        if component is not None and component not in ALLOWED_COMPONENTS:
            raise HTTPException(status_code=422, detail="Timeline contains a non-allowlisted component")
        if not isinstance(clip.get("props", {}), dict):
            raise HTTPException(status_code=422, detail="Timeline component props must be an object")
    canonical = json.dumps(snapshot, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _require_worker(request: Request) -> None:
    configured = settings.internal_worker_token.get_secret_value() if settings.internal_worker_token else ""
    supplied = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not configured or not supplied or not hmac.compare_digest(configured, supplied):
        raise HTTPException(status_code=401, detail="Internal worker authentication required")


async def _worker_job(db: AsyncSession, job_id: UUID, worker_id: str) -> dict[str, Any]:
    row = (await db.execute(text("""
        select * from public.render_jobs where id=:job and worker_id=:worker
    """), {"job": job_id, "worker": worker_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Render job not found or lease not owned")
    await set_rls_subject(db, str(row["requested_by"]))
    return dict(row)


@router.post("/projects/{project_id}/renders", status_code=202)
async def create_render(
    project_id: UUID,
    payload: RenderCreate,
    request: Request,
    claims: AuthenticatedClaims,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace_id = await _project_workspace(db, project_id, actor, "project.update")
    if not idempotency_key or not 16 <= len(idempotency_key) <= 128:
        raise HTTPException(status_code=400, detail="Idempotency-Key header must contain 16-128 characters")
    snapshot = dict(payload.snapshot)
    timeline_hash = _validate_snapshot(snapshot)
    snapshot["contentHash"] = timeline_hash
    row = (await db.execute(text("""
        insert into public.render_jobs(
            workspace_id,project_id,requested_by,composition_id,composition_version,
            timeline_snapshot,timeline_hash,render_config,idempotency_key
        ) values (
            :workspace,:project,:actor,'GraphytionTimeline',:version,
            cast(:snapshot as jsonb),:hash,cast(:config as jsonb),:key
        )
        on conflict (workspace_id,idempotency_key) do nothing returning id,status
    """), {
        "workspace": workspace_id, "project": project_id, "actor": actor,
        "version": payload.composition_version,
        "snapshot": json.dumps(snapshot, ensure_ascii=False), "hash": timeline_hash,
        "config": json.dumps({"codec": payload.codec, "format": "mp4"}),
        "key": idempotency_key,
    })).mappings().first()
    if row is None:
        existing = (await db.execute(text("""
            select id,status,timeline_hash from public.render_jobs
            where workspace_id=:workspace and idempotency_key=:key
        """), {"workspace": workspace_id, "key": idempotency_key})).mappings().first()
        if existing is None or existing["timeline_hash"] != timeline_hash:
            raise HTTPException(status_code=409, detail="Idempotency-Key was used for a different render snapshot")
        await db.rollback()
        return {"data": {"render_job_id": str(existing["id"]), "status": existing["status"], "replayed": True}}
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id)
        values (:actor,:workspace,'render.queued','render_job',:job,:request_id)
    """), {"actor": actor, "workspace": workspace_id, "job": row["id"], "request_id": request.state.request_id})
    await db.commit()
    try:
        await redis_client.xadd(RENDER_STREAM, {"render_job_id": str(row["id"])}, maxlen=10000, approximate=True)
    except Exception:
        # The worker's database recovery scan claims persisted queued jobs.
        pass
    return {"data": {"render_job_id": str(row["id"]), "status": "queued", "timeline_hash": timeline_hash}}


@router.get("/projects/{project_id}/renders")
async def list_renders(
    project_id: UUID,
    claims: AuthenticatedClaims,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _project_workspace(db, project_id, actor, "project.read")
    rows = (await db.execute(text("""
        select id,project_id,workspace_id,requested_by,status,composition_id,composition_version,timeline_hash,
               progress_percent,output_bucket,output_path,output_size_bytes,output_sha256,
               error_code,error_message_safe,started_at,completed_at,created_at
        from public.render_jobs where project_id=:project
        order by created_at desc limit :limit offset :offset
    """), {"project": project_id, "limit": per_page, "offset": (page - 1) * per_page})).mappings().all()
    total = await db.scalar(text("select count(*) from public.render_jobs where project_id=:project"), {"project": project_id})
    return {"data": [dict(row) for row in rows], "page": {"number": page, "size": per_page, "total": total}}


@router.get("/renders/{render_job_id}")
async def get_render(
    render_job_id: UUID,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    row = (await db.execute(text("""
        select * from public.render_jobs where id=:job
    """), {"job": render_job_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Render job not found")
    await _project_workspace(db, row["project_id"], actor, "project.read")
    return {"data": dict(row)}


@router.post("/internal/render-jobs/claim")
async def claim_render_job(
    request: Request,
    worker_id: str = Query(min_length=1, max_length=128),
    render_job_id: UUID | None = Query(default=None),
    db: AsyncSession = DbSession,
):
    _require_worker(request)
    row = (await db.execute(text("""
        select * from private.graphytion_claim_render_job(
            :worker,cast(:job as uuid),300
        )
    """), {"worker": worker_id, "job": render_job_id})).mappings().first()
    if row is None:
        await db.rollback()
        return {"data": None}
    await set_rls_subject(db, str(row["requested_by"]))
    await db.commit()
    return {"data": {
        "id": str(row["id"]), "workspace_id": str(row["workspace_id"]),
        "project_id": str(row["project_id"]), "requested_by": str(row["requested_by"]),
        "composition_id": row["composition_id"], "composition_version": row["composition_version"],
        "timeline_snapshot": row["timeline_snapshot"], "timeline_hash": row["timeline_hash"],
        "render_config": row["render_config"], "attempt_count": row["attempt_count"],
    }}


@router.patch("/internal/render-jobs/{render_job_id}/progress")
async def update_render_progress(
    render_job_id: UUID,
    payload: RenderProgress,
    request: Request,
    worker_id: str = Query(min_length=1, max_length=128),
    db: AsyncSession = DbSession,
):
    _require_worker(request)
    owner_id = await db.scalar(text("""
        select private.graphytion_render_job_owner(:job,:worker)
    """), {"job": render_job_id, "worker": worker_id})
    if owner_id is None:
        raise HTTPException(status_code=409, detail="Render job lease is no longer owned")
    await set_rls_subject(db, str(owner_id))
    await db.execute(text("""
        update public.render_jobs
        set progress_percent=:progress,lease_expires_at=now()+interval '5 minutes'
        where id=:job and worker_id=:worker and status='rendering'
    """), {"progress": payload.progress_percent, "job": render_job_id, "worker": worker_id})
    await db.commit()
    return {"data": {"render_job_id": str(render_job_id), "progress_percent": payload.progress_percent}}


@router.post("/internal/render-jobs/{render_job_id}/artifact", status_code=201)
async def complete_render_artifact(
    render_job_id: UUID,
    request: Request,
    file: UploadFile,
    worker_id: str = Query(min_length=1, max_length=128),
    db: AsyncSession = DbSession,
):
    _require_worker(request)
    owner_id = await db.scalar(text("""
        select private.graphytion_render_job_owner(:job,:worker)
    """), {"job": render_job_id, "worker": worker_id})
    if owner_id is None:
        raise HTTPException(status_code=409, detail="Render job lease is no longer owned")
    await set_rls_subject(db, str(owner_id))
    row = (await db.execute(text("""
        select id,workspace_id,project_id,requested_by,worker_id,status
        from public.render_jobs where id=:job and worker_id=:worker and status='rendering'
    """), {"job": render_job_id, "worker": worker_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=409, detail="Render job lease is no longer owned")
    content = await file.read(MAX_RENDER_BYTES + 1)
    if len(content) < 12 or len(content) > MAX_RENDER_BYTES or content[4:8] != b"ftyp":
        raise HTTPException(status_code=415, detail="Render output must be a valid MP4 file under 1 GB")
    digest = hashlib.sha256(content).hexdigest()
    object_path = f"{row['workspace_id']}/{row['project_id']}/{render_job_id}/output.mp4"
    try:
        await SupabaseStorage().upload(
            bucket=RENDER_BUCKET, object_path=object_path, content=content, content_type="video/mp4", upsert=True
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Render artifact storage upload failed") from exc
    await db.execute(text("""
        update public.render_jobs set status='completed',progress_percent=100,
            output_bucket=:bucket,output_path=:path,output_size_bytes=:size,output_sha256=:hash,
            completed_at=now(),lease_expires_at=null,worker_id=null
        where id=:job
    """), {"bucket": RENDER_BUCKET, "path": object_path, "size": len(content), "hash": digest, "job": render_job_id})
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id)
        values (:actor,:workspace,'render.completed','render_job',:job,:request_id)
    """), {"actor": row["requested_by"], "workspace": row["workspace_id"],
           "job": render_job_id, "request_id": request.state.request_id})
    await db.commit()
    return {"data": {"render_job_id": str(render_job_id), "status": "completed",
                     "output_size_bytes": len(content), "sha256": digest}}


@router.post("/internal/render-jobs/{render_job_id}/failed")
async def fail_render_job(
    render_job_id: UUID,
    payload: RenderFailure,
    request: Request,
    worker_id: str = Query(min_length=1, max_length=128),
    db: AsyncSession = DbSession,
):
    _require_worker(request)
    owner_id = await db.scalar(text("""
        select private.graphytion_render_job_owner(:job,:worker)
    """), {"job": render_job_id, "worker": worker_id})
    if owner_id is None:
        raise HTTPException(status_code=409, detail="Render job lease is no longer owned")
    await set_rls_subject(db, str(owner_id))
    row = (await db.execute(text("""
        select requested_by,attempt_count,max_attempts from public.render_jobs
        where id=:job and worker_id=:worker
    """), {"job": render_job_id, "worker": worker_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=409, detail="Render job lease is no longer owned")
    retry = payload.retryable and row["attempt_count"] < row["max_attempts"]
    await db.execute(text("""
        update public.render_jobs set status=:status,error_code=:code,error_message_safe=:message,
            worker_id=null,lease_expires_at=null,completed_at=case when :retry then null else now() end
        where id=:job
    """), {"status": "queued" if retry else "failed", "code": payload.error_code,
           "message": payload.error_message, "retry": retry, "job": render_job_id})
    await db.commit()
    if retry:
        try:
            await redis_client.xadd(RENDER_STREAM, {"render_job_id": str(render_job_id)}, maxlen=10000, approximate=True)
        except Exception:
            pass
    return {"data": {"render_job_id": str(render_job_id), "status": "queued" if retry else "failed"}}


@router.post("/projects/{project_id}/storyboards/{storyboard_id}/render", status_code=202)
async def render_approved_storyboard(
    project_id: UUID,
    storyboard_id: UUID,
    request: Request,
    claims: AuthenticatedClaims,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace_id = await _project_workspace(db, project_id, actor, "project.update")
    source = (await db.execute(text("""
        select sb.id,sb.global_visual_direction,p.width,p.height,p.fps
        from public.storyboards sb
        join public.video_projects p on p.id=sb.project_id
        join public.video_scripts vs on vs.id=sb.script_id
        where sb.id=:storyboard and sb.project_id=:project
          and sb.workspace_id=:workspace and sb.status='approved' and vs.status='approved'
    """), {"storyboard": storyboard_id, "project": project_id, "workspace": workspace_id})).mappings().first()
    if source is None:
        raise HTTPException(status_code=409, detail="Only an approved storyboard based on an approved script can be rendered")
    scenes = (await db.execute(text("""
        select id,scene_index,title,duration_ms,visual_direction
        from public.storyboard_scenes
        where storyboard_id=:storyboard and project_id=:project
        order by scene_index
    """), {"storyboard": storyboard_id, "project": project_id})).mappings().all()
    if not scenes:
        raise HTTPException(status_code=409, detail="Storyboard has no scenes to render")
    fps = int(source["fps"] or 30)
    clips = []
    cursor = 0
    for scene in scenes:
        duration_frames = max(1, round(int(scene["duration_ms"]) * fps / 1000))
        visual = dict(scene["visual_direction"] or {})
        background = visual.get("background", "#102F60")
        if not isinstance(background, str) or not background.startswith("#") or len(background) not in (4, 7):
            background = "#102F60"
        clips.append({
            "id": str(scene["id"]),
            "trackId": "main",
            "startFrame": cursor,
            "durationFrames": duration_frames,
            "componentKey": "core.title-card.v1",
            "props": {"title": str(scene["title"]), "background": background},
        })
        cursor += duration_frames
    snapshot = {
        "version": 1, "fps": fps,
        "width": int(source["width"]), "height": int(source["height"]),
        "durationFrames": cursor, "clips": clips,
    }
    return await create_render(
        project_id=project_id,
        payload=RenderCreate(snapshot=snapshot),
        request=request,
        claims=claims,
        idempotency_key=idempotency_key,
        db=db,
    )


@router.get("/renders/{render_job_id}/download")
async def download_render(
    render_job_id: UUID,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    row = (await db.execute(text("""
        select id,project_id,output_bucket,output_path,status
        from public.render_jobs where id=:job
    """), {"job": render_job_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Render job not found")
    await _project_workspace(db, row["project_id"], actor, "project.read")
    if row["status"] != "completed" or not row["output_bucket"] or not row["output_path"]:
        raise HTTPException(status_code=409, detail="Render output is not available")
    try:
        signed_url = await SupabaseStorage().create_signed_url(
            bucket=row["output_bucket"], object_path=row["output_path"], expires_in=300
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Render download URL could not be created") from exc
    return {"data": {"signed_url": signed_url, "expires_in": 300}}


@router.post("/renders/{render_job_id}/cancel")
async def cancel_queued_render(
    render_job_id: UUID,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    row = (await db.execute(text("""
        select id,project_id,workspace_id,status from public.render_jobs where id=:job
    """), {"job": render_job_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Render job not found")
    await _project_workspace(db, row["project_id"], actor, "project.update")
    if row["status"] != "queued":
        raise HTTPException(status_code=409, detail="Only queued render jobs can be cancelled; active Remotion renders are not interruptible")
    await db.execute(text("""
        update public.render_jobs set status='cancelled',completed_at=now(),
            worker_id=null,lease_expires_at=null
        where id=:job and status='queued'
    """), {"job": render_job_id})
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id)
        values (:actor,:workspace,'render.cancelled','render_job',:job,:request_id)
    """), {"actor": actor, "workspace": row["workspace_id"], "job": render_job_id,
           "request_id": request.state.request_id})
    await db.commit()
    return {"data": {"render_job_id": str(render_job_id), "status": "cancelled"}}
