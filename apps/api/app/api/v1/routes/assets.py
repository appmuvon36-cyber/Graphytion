from __future__ import annotations

import hashlib
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any, Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims, DbSession
from app.services.supabase_storage import SupabaseStorage
from app.core.database import set_rls_subject
from app.services.workspace_authorization import WorkspacePermissionResolver

router = APIRouter()
permissions = WorkspacePermissionResolver()
ASSET_BUCKET = "project-assets"
MAX_ASSET_BYTES = 50 * 1024 * 1024
MIME_EXTENSIONS = {
    "image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/svg+xml": "svg", "font/woff2": "woff2", "font/woff": "woff", "font/ttf": "ttf", "font/otf": "otf",
    "video/mp4": "mp4", "audio/mpeg": "mp3", "audio/wav": "wav",
    "application/pdf": "pdf",
}


def _actor(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid authenticated subject") from exc


async def _project_workspace(db: AsyncSession, project_id: UUID, actor: UUID, permission: str) -> UUID:
    await set_rls_subject(db, str(actor))
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


def _sanitize_svg(data: bytes) -> bytes:
    if len(data) > MAX_ASSET_BYTES:
        raise HTTPException(status_code=413, detail="SVG exceeds the asset size limit")
    if b"<!DOCTYPE" in data.upper() or b"<!ENTITY" in data.upper():
        raise HTTPException(status_code=415, detail="SVG DTD and entity declarations are not allowed")
    try:
        root = ET.fromstring(data.decode("utf-8"))
    except (UnicodeDecodeError, ET.ParseError) as exc:
        raise HTTPException(status_code=415, detail="SVG document is invalid") from exc
    allowed = {"svg","g","path","rect","circle","ellipse","line","polyline","polygon","text","tspan","defs","linearGradient","radialGradient","stop","clipPath","mask"}
    attrs = {"xmlns","viewBox","width","height","x","y","x1","x2","y1","y2","cx","cy","r","rx","ry","d","points","fill","fill-rule","fill-opacity","stroke","stroke-width","stroke-linecap","stroke-linejoin","stroke-dasharray","stroke-dashoffset","stroke-opacity","opacity","transform","id","class","font-size","font-family","font-weight","text-anchor","dominant-baseline","offset","stop-color","stop-opacity","gradientUnits","gradientTransform","clip-path","mask","preserveAspectRatio"}
    def clean(node: ET.Element) -> None:
        tag=node.tag.split("}")[-1]
        if tag not in allowed:
            node.clear()
            node.tag="g"
        for key in list(node.attrib):
            local=key.split("}")[-1]
            value=node.attrib[key].strip()
            if local not in attrs or local.lower().startswith("on") or re.search(r"(javascript:|data:|https?://|url\((?!#)",value,re.I):
                del node.attrib[key]
        for child in list(node):
            clean(child)
    if root.tag.split("}")[-1] != "svg":
        raise HTTPException(status_code=415, detail="SVG root element is required")
    clean(root)
    return ET.tostring(root,encoding="utf-8",xml_declaration=True)


def _valid_media(content_type: str, data: bytes) -> bool:
    if content_type == "image/svg+xml":
        try: _sanitize_svg(data)
        except HTTPException: return False
        return True
    if content_type == "font/woff2": return data.startswith(b"wOF2")
    if content_type == "font/woff": return data.startswith(b"wOFF")
    if content_type == "font/ttf": return data.startswith(b"\x00\x01\x00\x00")
    if content_type == "font/otf": return data.startswith(b"OTTO")
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
    supersedes_asset_id: UUID | None = Query(default=None),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace_id = await _project_workspace(db, project_id, actor, "project.update")
    asset_family_id = uuid4()
    version_number = 1
    if supersedes_asset_id:
        previous = (await db.execute(text("""
            select asset_family_id from public.project_assets
            where id=:asset and workspace_id=:workspace and status='active' for update
        """), {"asset": supersedes_asset_id, "workspace": workspace_id})).mappings().first()
        if previous is None:
            raise HTTPException(status_code=404, detail="Asset version source not found in this workspace")
        asset_family_id = previous["asset_family_id"]
        version_number = int(await db.scalar(text("""
            select coalesce(max(version_number),0)+1 from public.project_assets
            where asset_family_id=:family
        """), {"family": asset_family_id}))
    content_type = file.content_type or ""
    extension = MIME_EXTENSIONS.get(content_type)
    if not extension:
        raise HTTPException(status_code=415, detail="Unsupported project asset media type")
    content = await file.read(MAX_ASSET_BYTES + 1)
    if not content or len(content) > MAX_ASSET_BYTES:
        raise HTTPException(status_code=413, detail="Project assets must be between 1 byte and 50 MB")
    if not _valid_media(content_type, content):
        raise HTTPException(status_code=415, detail="Uploaded file signature does not match its media type")
    if content_type == "image/svg+xml":
        content = _sanitize_svg(content)
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
                file_name,content_type,size_bytes,sha256,asset_family_id,version_number,
                supersedes_asset_id,source_type
            ) values (
                :id,:workspace,:project,:actor,:bucket,:path,:name,:type,:size,:hash,
                :family,:version,:supersedes,'upload'
            ) returning *
        """), {
            "id": asset_id, "workspace": workspace_id, "project": project_id,
            "actor": actor, "bucket": ASSET_BUCKET, "path": object_path,
            "name": filename, "type": content_type, "size": len(content), "hash": digest,
            "family": asset_family_id, "version": version_number,
            "supersedes": supersedes_asset_id,
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
            "status": row["status"], "asset_family_id": str(row["asset_family_id"]),
            "version_number": row["version_number"],
            "supersedes_asset_id": str(row["supersedes_asset_id"]) if row["supersedes_asset_id"] else None,
            "created_at": row["created_at"],
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
    scope: Literal["project", "workspace"] = Query(default="project"),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    workspace_id = await _project_workspace(db, project_id, actor, "project.read")
    rows = (await db.execute(text("""
        select id,project_id,workspace_id,uploaded_by,file_name,content_type,
               size_bytes,sha256,status,asset_family_id,version_number,supersedes_asset_id,
               source_type,source_provider,source_job_id,provenance,usage_rights_status,
               license_type,commercial_use_allowed,attribution,created_at
        from public.project_assets
        where workspace_id=:workspace and status='active'
          and (:scope='workspace' or project_id=:project)
        order by created_at desc
        limit 500
    """), {"workspace": workspace_id, "project": project_id, "scope": scope})).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.get("/assets/{asset_id}/download")
async def download_project_asset(
    asset_id: UUID,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await set_rls_subject(db, str(actor))
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
    await set_rls_subject(db, str(actor))
    row = (await db.execute(text("""
        select id,project_id,workspace_id,bucket,object_path,status
        from public.project_assets where id=:asset
    """), {"asset": asset_id})).mappings().first()
    if row is None or row["status"] == "deleted":
        raise HTTPException(status_code=404, detail="Project asset not found")
    if row["status"] not in ("active", "deleting", "delete_failed"):
        raise HTTPException(status_code=409, detail="Project asset is already in a lifecycle transition")
    await _project_workspace(db, row["project_id"], actor, "project.update")
    referenced = await db.scalar(text("""
        select
          exists(
            select 1 from public.brand_kits bk
            where bk.workspace_id=:workspace and bk.brand_config->>'logo_asset_id'=:asset
              and bk.status='active'
          )
          or exists(
            select 1 from public.video_timelines t
            where t.workspace_id=:workspace and (
              exists(select 1 from jsonb_array_elements(coalesce(t.snapshot->'assetRefs','[]'::jsonb)) a
                     where a->>'assetId'=:asset)
              or exists(select 1 from jsonb_array_elements(coalesce(t.snapshot->'clips','[]'::jsonb)) clip
                        where clip->>'assetId'=:asset
                           or clip->'props'->>'assetId'=:asset
                           or clip->'props'->>'fontAssetId'=:asset)
            )
          )
          or exists(
            select 1 from public.composition_templates ct
            where ct.workspace_id=:workspace and ct.status='published' and (
              exists(select 1 from jsonb_array_elements(coalesce(ct.composition_snapshot->'assetRefs','[]'::jsonb)) a
                     where a->>'assetId'=:asset)
              or exists(select 1 from jsonb_array_elements(coalesce(ct.composition_snapshot->'clips','[]'::jsonb)) clip
                        where clip->>'assetId'=:asset
                           or clip->'props'->>'assetId'=:asset
                           or clip->'props'->>'fontAssetId'=:asset)
            )
          )
    """), {"workspace": row["workspace_id"], "asset": str(asset_id)})
    if referenced:
        raise HTTPException(status_code=409, detail="Asset is still referenced by a Brand Kit, saved timeline, or published template")
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
