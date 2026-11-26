from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any
from uuid import UUID, NAMESPACE_URL, uuid5

from fastapi import APIRouter, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims, DbSession
from app.core.config import settings
from app.core.database import set_rls_subject
from app.services.supabase_storage import SupabaseStorage
from app.services.workspace_authorization import WorkspacePermissionResolver
from app.services.composition_validation import validate_snapshot
from app.services.composition_assets import collect_asset_ids, resolve_project_assets

router = APIRouter()
permissions = WorkspacePermissionResolver()
RENDER_BUCKET = "render-artifacts"
MAX_RENDER_BYTES = 512 * 1024 * 1024
ALLOWED_COMPONENTS = {"core.title-card.v1","visual.image.v1","visual.video.v1","visual.shape.v1","text.basic.v1","data.chart.v1","audio.clip.v1","text.subtitle.v1"}


class RenderCreate(BaseModel):
    snapshot: dict[str, Any]
    render_profile_id: UUID | None = None
    composition_version: str = Field(default="2.0.0", min_length=1, max_length=32)


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
    await set_rls_subject(db,str(actor))
    return workspace_id


def _validate_snapshot(snapshot: dict[str, Any]) -> str:
    return validate_snapshot(snapshot)

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
    snapshot.pop("contentHash", None)
    timeline_hash = _validate_snapshot(snapshot)
    snapshot["contentHash"] = timeline_hash
    component_keys = list({clip["componentKey"] for clip in snapshot["clips"]})
    component_rows = (await db.execute(text("select component_key,component_version from public.motion_component_controls where enabled=true and component_key=any(cast(:keys as text[]))"), {"keys":component_keys})).mappings().all()
    enabled = {r["component_key"]:r["component_version"] for r in component_rows}
    for clip in snapshot["clips"]:
        if enabled.get(clip["componentKey"]) != clip["componentVersion"]:
            raise HTTPException(422, detail=f"Motion component {clip['componentKey']} is disabled or unsupported")
    asset_ids = collect_asset_ids(snapshot)
    await resolve_project_assets(db, project_id=project_id, workspace_id=workspace_id, asset_ids=asset_ids, expires_in=300, snapshot=snapshot)
    if payload.render_profile_id:
        profile = (await db.execute(text("select * from public.render_profiles where id=:id and is_archived=false and (scope='global' or (scope='workspace' and workspace_id=:workspace) or (scope='project' and project_id=:project))"), {"id":payload.render_profile_id,"workspace":workspace_id,"project":project_id})).mappings().first()
    else:
        profile = (await db.execute(text("select * from public.render_profiles where scope='global' and is_archived=false and width=:width and height=:height and fps=:fps order by is_default desc,priority desc,name limit 1"), {"width":snapshot["width"],"height":snapshot["height"],"fps":snapshot["fps"]})).mappings().first()
    if profile is None:
        raise HTTPException(422, detail="No active render profile matches this composition")
    if (profile["width"],profile["height"],profile["fps"]) != (snapshot["width"],snapshot["height"],snapshot["fps"]):
        raise HTTPException(422, detail="Render profile resolution and FPS must match the immutable composition snapshot")
    render_config = {"codec":profile["video_codec"],"format":profile["container"],"video_crf":profile["video_crf"],"video_bitrate":profile["video_bitrate"],"audio_codec":profile["audio_codec"],"audio_bitrate":profile["audio_bitrate"],"concurrency":profile["render_concurrency"],"priority":profile["priority"],"thumbnail_enabled":profile["thumbnail_enabled"],"preview_enabled":profile["preview_enabled"],"profile_key":profile["profile_key"],"profile_version":profile["version"]}
    timeline_id = await db.scalar(text("select id from public.video_timelines where project_id=:project and compiled_hash=:hash order by version desc limit 1"), {"project":project_id,"hash":timeline_hash})
    row = (await db.execute(text("insert into public.render_jobs(workspace_id,project_id,requested_by,composition_id,composition_version,timeline_snapshot,timeline_hash,render_config,idempotency_key,render_profile_id,snapshot_version,asset_manifest,timeline_id) values(:workspace,:project,:actor,'GraphytionTimeline',:version,cast(:snapshot as jsonb),:hash,cast(:config as jsonb),:key,:profile,:snapshot_version,cast(:assets as jsonb),:timeline_id) on conflict(workspace_id,idempotency_key) do nothing returning id,status"), {"workspace":workspace_id,"project":project_id,"actor":actor,"version":payload.composition_version,"snapshot":json.dumps(snapshot,ensure_ascii=False),"hash":timeline_hash,"config":json.dumps(render_config),"key":idempotency_key,"profile":profile["id"],"snapshot_version":snapshot["version"],"assets":json.dumps([str(x) for x in asset_ids]),"timeline_id":timeline_id})).mappings().first()
    if row is None:
        existing = (await db.execute(text("select id,status,timeline_hash from public.render_jobs where workspace_id=:workspace and idempotency_key=:key"), {"workspace":workspace_id,"key":idempotency_key})).mappings().first()
        if existing is None or existing["timeline_hash"] != timeline_hash:
            raise HTTPException(409, detail="Idempotency-Key was used for a different render snapshot")
        await db.rollback()
        return {"data":{"render_job_id":str(existing["id"]),"status":existing["status"],"replayed":True}}
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id)
        values (:actor,:workspace,'render.queued','render_job',:job,:request_id)
    """), {"actor": actor, "workspace": workspace_id, "job": row["id"], "request_id": request.state.request_id})
    await db.commit()
    # Workers poll PostgreSQL directly; the persisted render_jobs row is the queue.
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


@router.get("/renders/{render_job_id}/artifacts")
async def list_render_sidecar_artifacts(
    render_job_id: UUID,
    claims: AuthenticatedClaims,
    expires_in: int = Query(default=300, ge=30, le=21600),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    job = (await db.execute(text("select project_id from public.render_jobs where id=:id"),
                            {"id": render_job_id})).mappings().first()
    if job is None:
        raise HTTPException(status_code=404, detail="Render job not found")
    await _project_workspace(db, job["project_id"], actor, "project.read")
    rows = (await db.execute(text("""
        select id,artifact_type,storage_bucket,storage_path,mime_type,size_bytes,sha256,
               snapshot_version,created_at
        from public.render_artifacts where render_job_id=:job
        order by artifact_type
    """), {"job": render_job_id})).mappings().all()
    artifacts = []
    storage = SupabaseStorage()
    for row in rows:
        artifacts.append({
            **dict(row),
            "signed_url": await storage.create_signed_url(
                bucket=row["storage_bucket"], object_path=row["storage_path"], expires_in=expires_in
            ),
        })
    return {"data": artifacts}


@router.post("/internal/render-jobs/recover")
async def recover_render_jobs(
    request: Request,
    db: AsyncSession = DbSession,
):
    _require_worker(request)
    finalized = await db.scalar(text("select private.graphytion_finalize_render_jobs()"))
    await db.commit()
    return {"data": {"finalized_jobs": int(finalized or 0)}}


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
    resolved_assets = await resolve_project_assets(db, project_id=row["project_id"], workspace_id=row["workspace_id"], asset_ids=collect_asset_ids(dict(row["timeline_snapshot"])), expires_in=21600, snapshot=dict(row["timeline_snapshot"]))
    await db.execute(text("insert into public.render_attempts(render_job_id,attempt_number,worker_id,status) values(:job,:attempt,:worker,'claimed') on conflict(render_job_id,attempt_number) do update set worker_id=excluded.worker_id,status='claimed',started_at=now(),ended_at=null"), {"job":row["id"],"attempt":row["attempt_count"],"worker":worker_id})
    await db.commit()
    return {"data": {
        "id": str(row["id"]), "workspace_id": str(row["workspace_id"]),
        "project_id": str(row["project_id"]), "requested_by": str(row["requested_by"]),
        "composition_id": row["composition_id"], "composition_version": row["composition_version"],
        "timeline_snapshot": row["timeline_snapshot"], "timeline_hash": row["timeline_hash"],
        "render_config": row["render_config"], "resolved_assets":resolved_assets, "attempt_count": row["attempt_count"],
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
    state = await db.scalar(text("""
        select status from public.render_jobs where id=:job and worker_id=:worker
    """), {"job": render_job_id, "worker": worker_id})
    if state == "cancel_requested":
        await db.rollback()
        return {"data": {"render_job_id": str(render_job_id), "cancel_requested": True}}
    if state != "rendering":
        raise HTTPException(status_code=409, detail="Render job is not in a renderable state")
    await db.execute(text("""
        update public.render_jobs
        set progress_percent=:progress,lease_expires_at=now()+interval '5 minutes'
        where id=:job and worker_id=:worker and status='rendering'
    """), {"progress": payload.progress_percent, "job": render_job_id, "worker": worker_id})
    await db.execute(text("update public.render_attempts set status='rendering',diagnostics=jsonb_build_object('progress_percent',:progress) where render_job_id=:job and attempt_number=(select attempt_count from public.render_jobs where id=:job)"), {"progress":payload.progress_percent,"job":render_job_id})
    await db.commit()
    return {"data": {"render_job_id": str(render_job_id), "progress_percent": payload.progress_percent, "cancel_requested": False}}


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
        select id,workspace_id,project_id,requested_by,worker_id,status,render_config
        from public.render_jobs where id=:job and worker_id=:worker and status='rendering'
    """), {"job": render_job_id, "worker": worker_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=409, detail="Render job lease is no longer owned")
    content = await file.read(MAX_RENDER_BYTES + 1)
    container = row["render_config"].get("format","mp4")
    is_mp4 = len(content)>=12 and content[4:8]==b"ftyp"
    is_webm = len(content)>=4 and content[:4]==bytes.fromhex("1a45dfa3")
    if len(content)<12 or len(content)>MAX_RENDER_BYTES or not ((container=="mp4" and is_mp4) or (container=="webm" and is_webm)):
        raise HTTPException(status_code=415, detail="Render output does not match its persisted container profile")
    mime_type = "video/webm" if container=="webm" else "video/mp4"
    extension = "webm" if container=="webm" else "mp4"
    digest = hashlib.sha256(content).hexdigest()
    object_path = f"{row['workspace_id']}/{row['project_id']}/{render_job_id}/output.{extension}"
    try:
        await SupabaseStorage().upload(
            bucket=RENDER_BUCKET, object_path=object_path, content=content, content_type=mime_type, upsert=True, timeout_seconds=600
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Render artifact storage upload failed") from exc
    await db.execute(text("""
        update public.render_jobs set status='completed',progress_percent=100,
            output_bucket=:bucket,output_path=:path,output_size_bytes=:size,output_sha256=:hash,
            completed_at=now(),lease_expires_at=null,worker_id=null
        where id=:job
    """), {"bucket": RENDER_BUCKET, "path": object_path, "size": len(content), "hash": digest, "job": render_job_id})
    await db.execute(text("update public.render_attempts set status='completed',ended_at=now(),diagnostics=cast(:diagnostics as jsonb) where render_job_id=:job and attempt_number=(select attempt_count from public.render_jobs where id=:job)"), {"job":render_job_id,"diagnostics":json.dumps({"bytes":len(content),"sha256":digest,"mime_type":mime_type})})
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id)
        values (:actor,:workspace,'render.completed','render_job',:job,:request_id)
    """), {"actor": row["requested_by"], "workspace": row["workspace_id"],
           "job": render_job_id, "request_id": request.state.request_id})
    await db.commit()
    return {"data": {"render_job_id": str(render_job_id), "status": "completed",
                     "output_size_bytes": len(content), "sha256": digest}}


@router.post("/internal/render-jobs/{render_job_id}/artifacts", status_code=201)
async def create_render_sidecar_artifact(
    render_job_id: UUID,
    request: Request,
    file: UploadFile,
    artifact_type: str = Query(pattern=r"^(thumbnail|preview)$"),
    worker_id: str = Query(min_length=1, max_length=128),
    db: AsyncSession = DbSession,
):
    """Persist a thumbnail or preview separately; never changes final render completion state."""
    _require_worker(request)
    owner_id = await db.scalar(text("select private.graphytion_render_job_owner(:job,:worker)"),
                               {"job": render_job_id, "worker": worker_id})
    if owner_id is None:
        raise HTTPException(status_code=409, detail="Render job lease is no longer owned")
    await set_rls_subject(db, str(owner_id))
    row = (await db.execute(text("""
        select id,workspace_id,project_id,worker_id,status,snapshot_version
        from public.render_jobs where id=:job and worker_id=:worker and status='rendering'
    """), {"job": render_job_id, "worker": worker_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=409, detail="Render job lease is no longer owned")
    content = await file.read(100 * 1024 * 1024 + 1)
    mime = file.content_type or ""
    if artifact_type == "thumbnail":
        valid = ((mime == "image/jpeg" and content.startswith(bytes.fromhex("ffd8ff"))) or
                 (mime == "image/png" and content.startswith(bytes.fromhex("89504e470d0a1a0a"))))
        maximum = 20 * 1024 * 1024
    else:
        valid = ((mime == "video/mp4" and len(content) >= 12 and content[4:8] == b"ftyp") or
                 (mime == "video/webm" and content.startswith(bytes.fromhex("1a45dfa3"))))
        maximum = 100 * 1024 * 1024
    if not valid or not 1 <= len(content) <= maximum:
        raise HTTPException(status_code=415, detail="Sidecar artifact bytes do not match its declared media type")
    digest = hashlib.sha256(content).hexdigest()
    extension = {"image/jpeg":"jpg","image/png":"png","video/mp4":"mp4","video/webm":"webm"}[mime]
    object_path = f"{row['workspace_id']}/{row['project_id']}/{render_job_id}/{artifact_type}.{extension}"
    try:
        await SupabaseStorage().upload(bucket=RENDER_BUCKET, object_path=object_path,
                                       content=content, content_type=mime, upsert=True, timeout_seconds=180)
        await db.execute(text("""
            insert into public.render_artifacts
            (workspace_id,project_id,render_job_id,artifact_type,storage_bucket,storage_path,
             mime_type,size_bytes,sha256,snapshot_version)
            values(:workspace,:project,:job,:type,:bucket,:path,:mime,:size,:hash,:snapshot)
            on conflict(render_job_id,artifact_type) do update set
              storage_bucket=excluded.storage_bucket,storage_path=excluded.storage_path,
              mime_type=excluded.mime_type,size_bytes=excluded.size_bytes,sha256=excluded.sha256,
              snapshot_version=excluded.snapshot_version,created_at=now()
        """), {"workspace":row["workspace_id"],"project":row["project_id"],"job":render_job_id,
               "type":artifact_type,"bucket":RENDER_BUCKET,"path":object_path,"mime":mime,
               "size":len(content),"hash":digest,"snapshot":row["snapshot_version"]})
        await db.commit()
    except Exception as exc:
        await db.rollback()
        try:
            await SupabaseStorage().remove(bucket=RENDER_BUCKET, object_path=object_path)
        except Exception:
            pass
        raise HTTPException(status_code=502, detail="Sidecar artifact persistence failed") from exc
    return {"data":{"render_job_id":str(render_job_id),"artifact_type":artifact_type,
                    "storage_path":object_path,"mime_type":mime,"size_bytes":len(content),"sha256":digest}}


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
        select requested_by,attempt_count,max_attempts,status from public.render_jobs
        where id=:job and worker_id=:worker
    """), {"job": render_job_id, "worker": worker_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=409, detail="Render job lease is no longer owned")
    if row["status"] == "cancel_requested":
        await db.execute(text("""
            update public.render_jobs set status='cancelled',completed_at=now(),
                worker_id=null,lease_expires_at=null
            where id=:job and worker_id=:worker
        """), {"job": render_job_id, "worker": worker_id})
        await db.execute(text("update public.render_attempts set status='cancelled',ended_at=now() where render_job_id=:job and attempt_number=(select attempt_count from public.render_jobs where id=:job)"), {"job":render_job_id})
        await db.commit()
        return {"data": {"render_job_id": str(render_job_id), "status": "cancelled"}}
    retry = payload.retryable and row["attempt_count"] < row["max_attempts"]
    await db.execute(text("""
        update public.render_jobs set status=:status,error_code=:code,error_message_safe=:message,
            worker_id=null,lease_expires_at=null,completed_at=case when :retry then null else now() end
        where id=:job
    """), {"status": "queued" if retry else "failed", "code": payload.error_code,
           "message": payload.error_message, "retry": retry, "job": render_job_id})
    await db.execute(text("update public.render_attempts set status='failed',ended_at=now(),error_code=:code,diagnostics=cast(:diagnostics as jsonb) where render_job_id=:job and attempt_number=(select attempt_count from public.render_jobs where id=:job)"), {"code":payload.error_code,"diagnostics":json.dumps({"message":payload.error_message,"retryable":payload.retryable}),"job":render_job_id})
    await db.commit()
    # PostgreSQL polling discovers retryable jobs after the failure transaction commits.
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
    track_id = str(uuid5(NAMESPACE_URL, f"graphytion:{storyboard_id}:main"))
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
            "trackId": track_id,
            "startFrame": cursor,
            "durationFrames": duration_frames, "trimStartFrames": 0, "playbackRate": 1,
            "componentKey": "core.title-card.v1", "componentVersion": "1.1.0",
            "props": {"title": str(scene["title"]), "subtitle": str(visual.get("description") or "")[:500], "background": background},
        })
        cursor += duration_frames
    snapshot = {
        "version": 2, "compositionVersion": "2.0.0", "fps": fps,
        "width": int(source["width"]), "height": int(source["height"]),
        "durationFrames": cursor, "tracks": [{"id":track_id,"kind":"typography","name":"Storyboard scenes","zIndex":10,"visible":True,"locked":False,"muted":False,"volume":1}], "clips": clips, "assetRefs": [], "background": "#101828",
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
    if row["status"] == "queued":
        next_status = "cancelled"
        await db.execute(text("""
            update public.render_jobs set status='cancelled',completed_at=now(),
                worker_id=null,lease_expires_at=null
            where id=:job and status='queued'
        """), {"job": render_job_id})
    elif row["status"] == "rendering":
        next_status = "cancel_requested"
        await db.execute(text("""
            update public.render_jobs set status='cancel_requested'
            where id=:job and status='rendering'
        """), {"job": render_job_id})
    else:
        raise HTTPException(status_code=409, detail=f"Render job cannot be cancelled from status {row['status']}")
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id)
        values (:actor,:workspace,'render.cancel_requested','render_job',:job,:request_id)
    """), {"actor": actor, "workspace": row["workspace_id"], "job": render_job_id,
           "request_id": request.state.request_id})
    await db.commit()
    return {"data": {"render_job_id": str(render_job_id), "status": next_status}}


@router.get("/projects/{project_id}/storyboards/{storyboard_id}/preview")
async def preview_approved_storyboard(
    project_id: UUID,
    storyboard_id: UUID,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace_id = await _project_workspace(db, project_id, actor, "project.read")
    source = (await db.execute(text("""
        select sb.id,p.width,p.height,p.fps
        from public.storyboards sb
        join public.video_projects p on p.id=sb.project_id
        join public.video_scripts vs on vs.id=sb.script_id
        where sb.id=:storyboard and sb.project_id=:project
          and sb.workspace_id=:workspace and sb.status='approved' and vs.status='approved'
    """), {"storyboard": storyboard_id, "project": project_id, "workspace": workspace_id})).mappings().first()
    if source is None:
        raise HTTPException(status_code=409, detail="Only an approved storyboard based on an approved script can be previewed")
    scenes = (await db.execute(text("""
        select id,title,duration_ms,visual_direction
        from public.storyboard_scenes
        where storyboard_id=:storyboard and project_id=:project
        order by scene_index
    """), {"storyboard": storyboard_id, "project": project_id})).mappings().all()
    if not scenes:
        raise HTTPException(status_code=409, detail="Storyboard has no scenes to preview")
    fps = int(source["fps"] or 30)
    track_id = str(uuid5(NAMESPACE_URL, f"graphytion:{storyboard_id}:main"))
    clips = []
    cursor = 0
    for scene in scenes:
        duration_frames = max(1, round(int(scene["duration_ms"]) * fps / 1000))
        visual = dict(scene["visual_direction"] or {})
        background = visual.get("background", "#102F60")
        if not isinstance(background, str) or not background.startswith("#") or len(background) not in (4, 7):
            background = "#102F60"
        clips.append({
            "id": str(scene["id"]), "trackId": track_id, "startFrame": cursor,
            "durationFrames": duration_frames, "trimStartFrames": 0, "playbackRate": 1, "componentKey": "core.title-card.v1", "componentVersion": "1.1.0",
            "props": {"title": str(scene["title"]), "subtitle": str(visual.get("description") or "")[:500], "background": background},
        })
        cursor += duration_frames
    snapshot = {
        "version": 2, "compositionVersion": "2.0.0", "fps": fps, "width": int(source["width"]), "height": int(source["height"]),
        "durationFrames": cursor, "tracks": [{"id":track_id,"kind":"typography","name":"Storyboard scenes","zIndex":10,"visible":True,"locked":False,"muted":False,"volume":1}], "clips": clips, "assetRefs": [], "background": "#101828",
    }
    timeline_hash = _validate_snapshot(snapshot)
    snapshot["contentHash"] = timeline_hash
    resolved_assets = await resolve_project_assets(db, project_id=project_id, workspace_id=workspace_id, asset_ids=collect_asset_ids(snapshot), snapshot=snapshot)
    return {"data": {"storyboard_id": str(storyboard_id), "snapshot": snapshot, "resolved_assets":resolved_assets, "timeline_hash": timeline_hash}}
