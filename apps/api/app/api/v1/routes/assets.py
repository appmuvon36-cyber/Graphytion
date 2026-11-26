from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims, DbSession
from app.services.supabase_storage import SupabaseStorage
from app.services.workspace_authorization import WorkspacePermissionResolver

router = APIRouter()
permissions = WorkspacePermissionResolver()
ASSET_BUCKET = "project-assets"
MAX_ASSET_BYTES = 50 * 1024 * 1024
MIME_EXTENSIONS = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp",
    "video/mp4": "mp4", "audio/mpeg": "mp3", "audio/wav": "wav",
    "application/pdf": "pdf",
}


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


def _valid_media(content_type: str, data: bytes) -> bool:
    if content_type == "image/png":
        return data.startswith(b"\x89PNG\r\n\x1a\n")
    if content_type == "image/jpeg":
        return data.startswith(b"\xff\xd8\xff")
    if content_type == "image/webp":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP"
    if content_type == "video/mp4":
        return len(data) >= 12 and data[4:8] == b"ftyp"
    if content_type == "audio/wav":
        return len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE"
    if content_type == "audio/mpeg":
        return data.startswith(b"ID3") or (len(data) > 1 and data[0] == 0xFF and data[1] & 0xE0 == 0xE0)
    if content_type == "application/pdf":
        return data.startswith(b"%PDF-")
    return False


@router.post("/projects/{project_id}/assets", status_code=201)
async def upload_project_asset(
    project_id: UUID,
    request: Request,
    claims: AuthenticatedClaims,
    file: UploadFile,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace_id = await _project_workspace(db, project_id, actor, "project.update")
    content_type = file.content_type or ""
    extension = MIME_EXTENSIONS.get(content_type)
    if not extension:
        raise HTTPException(status_code=415, detail="Unsupported project asset media type")
    content = await file.read(MAX_ASSET_BYTES + 1)
    if not content or len(content) > MAX_ASSET_BYTES:
        raise HTTPException(status_code=413, detail="Project assets must be between 1 byte and 50 MB")
    if not _valid_media(content_type, content):
        raise HTTPException(status_code=415, detail="Uploaded file signature does not match its media type")
    asset_id = uuid4()
    object_path = f"{workspace_id}/{project_id}/{asset_id}.{extension}"
    filename = Path(file.filename or f"asset.{extension}").name[:255]
    digest = hashlib.sha256(content).hexdigest()
    storage = SupabaseStorage()
    try:
        await storage.upload(
            bucket=ASSET_BUCKET, object_path=object_path, content=content, content_type=content_type
        )
        row = (await db.execute(text("""
            insert into public.project_assets(
                id,workspace_id,project_id,uploaded_by,bucket,object_path,
                file_name,content_type,size_bytes,sha256
            ) values (
                :id,:workspace,:project,:actor,:bucket,:path,:name,:type,:size,:hash
            ) returning *
        """), {
            "id": asset_id, "workspace": workspace_id, "project": project_id,
            "actor": actor, "bucket": ASSET_BUCKET, "path": object_path,
            "name": filename, "type": content_type, "size": len(content), "hash": digest,
        })).mappings().one()
        await db.execute(text("""
            insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id)
            values (:actor,:workspace,'project.asset.uploaded','project_asset',:asset,:request_id)
        """), {"actor": actor, "workspace": workspace_id, "asset": asset_id,
               "request_id": request.state.request_id})
        await db.commit()
        return {"data": {
            "id": str(row["id"]), "project_id": str(row["project_id"]),
            "workspace_id": str(row["workspace_id"]), "uploaded_by": str(row["uploaded_by"]),
            "file_name": row["file_name"], "content_type": row["content_type"],
            "size_bytes": row["size_bytes"], "sha256": row["sha256"],
            "status": row["status"], "created_at": row["created_at"],
        }}
    except Exception as exc:
        await db.rollback()
        try:
            await storage.remove(bucket=ASSET_BUCKET, object_path=object_path)
        except Exception:
            pass
        if isinstance(exc, HTTPException):
            raise
        raise HTTPException(status_code=502, detail="Project asset persistence failed") from exc


@router.get("/projects/{project_id}/assets")
async def list_project_assets(
    project_id: UUID,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _project_workspace(db, project_id, actor, "project.read")
    rows = (await db.execute(text("""
        select id,project_id,workspace_id,uploaded_by,file_name,content_type,
               size_bytes,sha256,status,created_at
        from public.project_assets
        where project_id=:project and status='active'
        order by created_at desc
    """), {"project": project_id})).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.get("/assets/{asset_id}/download")
async def download_project_asset(
    asset_id: UUID,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    row = (await db.execute(text("""
        select id,project_id,bucket,object_path,status
        from public.project_assets where id=:asset
    """), {"asset": asset_id})).mappings().first()
    if row is None or row["status"] != "active":
        raise HTTPException(status_code=404, detail="Project asset not found")
    await _project_workspace(db, row["project_id"], actor, "project.read")
    try:
        url = await SupabaseStorage().create_signed_url(
            bucket=row["bucket"], object_path=row["object_path"], expires_in=300
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Project asset download URL unavailable") from exc
    return {"data": {"signed_url": url, "expires_in": 300}}


@router.delete("/assets/{asset_id}", status_code=204)
async def delete_project_asset(
    asset_id: UUID,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    row = (await db.execute(text("""
        select id,project_id,workspace_id,bucket,object_path,status
        from public.project_assets where id=:asset
    """), {"asset": asset_id})).mappings().first()
    if row is None or row["status"] == "deleted":
        raise HTTPException(status_code=404, detail="Project asset not found")
    if row["status"] not in ("active", "deleting", "delete_failed"):
        raise HTTPException(status_code=409, detail="Project asset is already in a lifecycle transition")
    await _project_workspace(db, row["project_id"], actor, "project.update")
    await db.execute(text("""
        update public.project_assets set status='deleting' where id=:asset
    """), {"asset": asset_id})
    await db.commit()
    try:
        await SupabaseStorage().remove(bucket=row["bucket"], object_path=row["object_path"])
    except Exception as exc:
        await db.execute(text("""
            update public.project_assets set status='delete_failed' where id=:asset
        """), {"asset": asset_id})
        await db.commit()
        raise HTTPException(status_code=502, detail="Project asset storage deletion failed; retry is available") from exc
    await db.execute(text("""
        update public.project_assets set status='deleted',deleted_at=now()
        where id=:asset
    """), {"asset": asset_id})
    await db.execute(text("""
        insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id)
        values (:actor,:workspace,'project.asset.deleted','project_asset',:asset,:request_id)
    """), {"actor": actor, "workspace": row["workspace_id"], "asset": asset_id,
           "request_id": request.state.request_id})
    await db.commit()
    return None
