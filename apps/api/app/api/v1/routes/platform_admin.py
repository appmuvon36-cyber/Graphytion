from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims, DbSession
from app.core.database import set_rls_subject
from app.services.supabase_auth import supabase_auth
from app.services.llm_gateway import model_router
from app.core.config import settings
from app.services.queue_notifications import notify_worker

router = APIRouter()


class RenderSettingsInput(BaseModel):
    max_concurrent_jobs: int = Field(ge=1, le=8)
    lease_seconds: int = Field(ge=60, le=3600)
    max_attempts: int = Field(ge=1, le=10)
    max_output_bytes: int = Field(ge=1048576, le=536870912)


def _actor(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid authenticated subject") from exc


async def _require_platform_admin(db: AsyncSession, actor: UUID) -> None:
    await set_rls_subject(db, str(actor))
    allowed = await db.scalar(text("select private.graphytion_is_platform_admin()"))
    if not allowed:
        raise HTTPException(status_code=403, detail="Platform administrator access required")


async def _require_super_admin(db: AsyncSession, actor: UUID) -> None:
    await set_rls_subject(db, str(actor))
    role = await db.scalar(text("""
        select role from public.platform_admins
        where user_id=:actor and status='active'
    """), {"actor": actor})
    if role != "super_admin":
        raise HTTPException(status_code=403, detail="Super administrator access required")


async def _audit(
    db: AsyncSession, request: Request, actor: UUID, action: str,
    resource_type: str, resource_id: UUID, metadata: dict[str, Any] | None = None,
) -> None:
    await db.execute(text("""
        insert into public.audit_logs(
            actor_user_id, action, resource_type, resource_id, metadata, request_id
        ) values (:actor,:action,:resource_type,:resource_id,cast(:metadata as jsonb),:request_id)
    """), {
        "actor": actor, "action": action, "resource_type": resource_type,
        "resource_id": resource_id, "metadata": json.dumps(metadata or {}),
        "request_id": getattr(request.state, "request_id", None),
    })


@router.get("/overview")
async def platform_overview(
    claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    result = (await db.execute(text("""
        select
          (select count(*) from public.profiles) as users,
          (select count(*) from public.workspaces) as workspaces,
          (select count(*) from public.workspace_members where status='active') as active_memberships,
          (select count(*) from public.video_projects where status <> 'deleted') as projects,
          (select count(*) from public.audit_logs where created_at >= now()-interval '24 hours') as audit_events_24h,
          (select count(*) from public.production_runs where status in ('planning','scripting','storyboarding','queued','running')) as active_creative_runs,
          (select count(*) from public.render_jobs where status in ('queued','rendering','cancel_requested')) as active_render_jobs,
          (select coalesce(sum(input_tokens),0) from public.ai_usage_events where created_at >= now()-interval '24 hours') as input_tokens_24h,
          (select coalesce(sum(output_tokens),0) from public.ai_usage_events where created_at >= now()-interval '24 hours') as output_tokens_24h
    """))).mappings().one()
    return {"data": dict(result)}


@router.get("/users")
async def platform_users(
    claims: AuthenticatedClaims,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
    q: str | None = Query(default=None, max_length=160),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    auth_page = await supabase_auth.list_users(page=page, per_page=per_page)
    auth_users = auth_page.get("users", [])
    ids = [UUID(str(item["id"])) for item in auth_users if item.get("id")]
    profiles: dict[str, Any] = {}
    if ids:
        rows = (await db.execute(text("""
            select id,display_name,avatar_path,bio,locale,timezone,created_at,updated_at
            from public.profiles where id = any(cast(:ids as uuid[]))
        """), {"ids": ids})).mappings().all()
        profiles = {str(row["id"]): dict(row) for row in rows}
    data = []
    for user in auth_users:
        user_id = str(user.get("id", ""))
        profile = profiles.get(user_id, {})
        item = {
            "id": user_id, "email": user.get("email"),
            "email_confirmed_at": user.get("email_confirmed_at"),
            "last_sign_in_at": user.get("last_sign_in_at"),
            "created_at": user.get("created_at"),
            "banned_until": user.get("banned_until"),
            "profile": profile,
        }
        if q and q.casefold() not in " ".join([
            str(item.get("email") or ""), str(profile.get("display_name") or ""), user_id
        ]).casefold():
            continue
        data.append(item)
    return {"data": data, "page": {"number": page, "size": per_page, "has_more": len(auth_users) == per_page}}


class AccountStatusUpdate(BaseModel):
    banned: bool
    reason: str = Field(min_length=3, max_length=500)


@router.patch("/users/{user_id}/status")
async def update_platform_user_status(
    user_id: UUID,
    payload: AccountStatusUpdate,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    if user_id == actor:
        raise HTTPException(status_code=409, detail="Administrators cannot change their own account status")
    result = await supabase_auth.set_user_ban(str(user_id), banned=payload.banned)
    await _audit(
        db, request, actor, "platform.user.banned" if payload.banned else "platform.user.unbanned",
        "user", user_id, {"reason": payload.reason},
    )
    await db.commit()
    user = result.get("user", result)
    return {"data": {
        "id": str(user_id), "banned_until": user.get("banned_until"),
        "status": "banned" if payload.banned else "active",
    }}


@router.get("/workspaces")
async def platform_workspaces(
    claims: AuthenticatedClaims,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
    q: str | None = Query(default=None, max_length=160),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    rows = (await db.execute(text("""
        select w.id,w.name,w.slug,w.owner_user_id,w.created_at,w.updated_at,
          (select count(*) from public.workspace_members m where m.workspace_id=w.id and m.status='active') as active_members,
          (select count(*) from public.video_projects p where p.workspace_id=w.id and p.status <> 'deleted') as projects
        from public.workspaces w
        where (:q is null or w.name ilike :pattern or w.slug ilike :pattern)
        order by w.updated_at desc
        limit :limit offset :offset
    """), {
        "q": q, "pattern": f"%{q}%" if q else None,
        "limit": per_page, "offset": (page - 1) * per_page,
    })).mappings().all()
    total = await db.scalar(text("""
        select count(*) from public.workspaces
        where (:q is null or name ilike :pattern or slug ilike :pattern)
    """), {"q": q, "pattern": f"%{q}%" if q else None})
    return {"data": [dict(row) for row in rows], "page": {"number": page, "size": per_page, "total": total}}


@router.get("/projects")
async def platform_projects(
    claims: AuthenticatedClaims,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=25, ge=1, le=100),
    q: str | None = Query(default=None, max_length=160),
    status: str | None = Query(default=None, max_length=32),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    rows = (await db.execute(text("""
        select p.id,p.workspace_id,p.name,p.description,p.production_mode,p.status,
               p.default_language,p.created_at,p.updated_at,w.name as workspace_name
        from public.video_projects p join public.workspaces w on w.id=p.workspace_id
        where (:q is null or p.name ilike :pattern)
          and (:status is null or p.status=:status)
        order by p.updated_at desc limit :limit offset :offset
    """), {
        "q": q, "pattern": f"%{q}%" if q else None, "status": status,
        "limit": per_page, "offset": (page - 1) * per_page,
    })).mappings().all()
    total = await db.scalar(text("""
        select count(*) from public.video_projects
        where (:q is null or name ilike :pattern) and (:status is null or status=:status)
    """), {"q": q, "pattern": f"%{q}%" if q else None, "status": status})
    return {"data": [dict(row) for row in rows], "page": {"number": page, "size": per_page, "total": total}}


@router.get("/audit-logs")
async def platform_audit_logs(
    claims: AuthenticatedClaims,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    action: str | None = Query(default=None, max_length=120),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    rows = (await db.execute(text("""
        select id,actor_user_id,workspace_id,action,resource_type,resource_id,
               metadata,request_id,created_at
        from public.audit_logs
        where (:action is null or action=:action)
        order by created_at desc limit :limit offset :offset
    """), {
        "action": action, "limit": per_page, "offset": (page - 1) * per_page,
    })).mappings().all()
    total = await db.scalar(text("""
        select count(*) from public.audit_logs where (:action is null or action=:action)
    """), {"action": action})
    return {"data": [dict(row) for row in rows], "page": {"number": page, "size": per_page, "total": total}}


class PlatformMemberRoleUpdate(BaseModel):
    role: str = Field(pattern=r"^(admin|editor|member|viewer|billing)$")


@router.get("/workspaces/{workspace_id}/members")
async def platform_workspace_members(
    workspace_id: UUID,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    rows = (await db.execute(text("""
        select m.id,m.workspace_id,m.user_id,m.role,m.status,m.created_at,p.display_name
        from public.workspace_members m
        left join public.profiles p on p.id=m.user_id
        where m.workspace_id=:workspace order by m.created_at
    """), {"workspace": workspace_id})).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.patch("/workspaces/{workspace_id}/members/{member_id}")
async def platform_update_member_role(
    workspace_id: UUID,
    member_id: UUID,
    payload: PlatformMemberRoleUpdate,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    target = (await db.execute(text("""
        select role,status from public.workspace_members
        where id=:member and workspace_id=:workspace for update
    """), {"member": member_id, "workspace": workspace_id})).mappings().first()
    if target is None:
        raise HTTPException(status_code=404, detail="Workspace membership not found")
    if target["role"] == "owner":
        raise HTTPException(status_code=409, detail="Platform role administration cannot transfer workspace ownership")
    await db.execute(text("""
        update public.workspace_members set role=:role
        where id=:member and workspace_id=:workspace
    """), {"role": payload.role, "member": member_id, "workspace": workspace_id})
    await _audit(db, request, actor, "platform.workspace_member.role_changed",
                 "workspace_member", member_id,
                 {"workspace_id": str(workspace_id), "previous_role": target["role"], "role": payload.role})
    await db.commit()
    return {"data": {"member_id": str(member_id), "role": payload.role}}


@router.delete("/workspaces/{workspace_id}/members/{member_id}", status_code=204)
async def platform_remove_member(
    workspace_id: UUID,
    member_id: UUID,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    target = (await db.execute(text("""
        select role,status from public.workspace_members
        where id=:member and workspace_id=:workspace for update
    """), {"member": member_id, "workspace": workspace_id})).mappings().first()
    if target is None:
        raise HTTPException(status_code=404, detail="Workspace membership not found")
    if target["role"] == "owner":
        raise HTTPException(status_code=409, detail="Workspace owner cannot be removed")
    await db.execute(text("""
        update public.workspace_members set status='left'
        where id=:member and workspace_id=:workspace
    """), {"member": member_id, "workspace": workspace_id})
    await _audit(db, request, actor, "platform.workspace_member.removed",
                 "workspace_member", member_id, {"workspace_id": str(workspace_id)})
    await db.commit()
    return None


@router.get("/invitations")
async def platform_invitations(
    claims: AuthenticatedClaims,
    page: int = Query(default=1, ge=1),
    per_page: int = Query(default=50, ge=1, le=100),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    rows = (await db.execute(text("""
        select i.id,i.workspace_id,w.name as workspace_name,i.email,i.role,i.invited_by,
               i.expires_at,i.accepted_at,i.cancelled_at,i.delivery_status,
               i.delivery_attempts,i.sent_at,i.created_at
        from public.workspace_invitations i
        join public.workspaces w on w.id=i.workspace_id
        order by i.created_at desc
        limit :limit offset :offset
    """), {"limit": per_page, "offset": (page - 1) * per_page})).mappings().all()
    total = await db.scalar(text("select count(*) from public.workspace_invitations"))
    return {"data": [dict(row) for row in rows], "page": {"number": page, "size": per_page, "total": total}}


@router.delete("/invitations/{invitation_id}", status_code=204)
async def platform_cancel_invitation(
    invitation_id: UUID,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    row = (await db.execute(text("""
        update public.workspace_invitations
        set cancelled_at=now()
        where id=:id and accepted_at is null and cancelled_at is null
        returning workspace_id
    """), {"id": invitation_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Pending invitation not found")
    await _audit(db, request, actor, "platform.invitation.cancelled",
                 "invitation", invitation_id, {"workspace_id": str(row["workspace_id"])})
    await db.commit()
    return None


class PlatformProjectStatusUpdate(BaseModel):
    status: str = Field(pattern=r"^(draft|archived)$")
    reason: str = Field(min_length=3, max_length=500)


@router.patch("/projects/{project_id}/status")
async def platform_update_project_status(
    project_id: UUID,
    payload: PlatformProjectStatusUpdate,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    row = (await db.execute(text("""
        select status from public.video_projects where id=:project and status <> 'deleted' for update
    """), {"project": project_id})).mappings().first()
    if row is None:
        raise HTTPException(status_code=404, detail="Project not found")
    if payload.status == "archived" and row["status"] not in ("draft", "active"):
        raise HTTPException(status_code=409, detail="Only draft or active projects can be archived")
    if payload.status == "draft" and row["status"] != "archived":
        raise HTTPException(status_code=409, detail="Only archived projects can be restored")
    await db.execute(text("""
        update public.video_projects set status=:status,updated_at=now()
        where id=:project
    """), {"status": payload.status, "project": project_id})
    await _audit(db, request, actor, "platform.project.status_changed",
                 "project", project_id, {"from": row["status"], "to": payload.status, "reason": payload.reason})
    await db.commit()
    return {"data": {"project_id": str(project_id), "status": payload.status}}


class PlatformAdminGrant(BaseModel):
    user_id: UUID
    role: str = Field(pattern=r"^(super_admin|support_admin|operations_admin)$")
    reason: str = Field(min_length=3, max_length=500)


@router.get("/platform-admins")
async def list_platform_admins(
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    rows = (await db.execute(text("""
        select user_id,role,status,granted_by,granted_at,revoked_at,reason
        from public.platform_admins order by granted_at desc
    """))).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.post("/platform-admins", status_code=201)
async def grant_platform_admin(
    payload: PlatformAdminGrant,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_super_admin(db, actor)
    exists = await db.scalar(text("select 1 from public.profiles where id=:user"), {"user": payload.user_id})
    if not exists:
        raise HTTPException(status_code=404, detail="User profile not found")
    row = (await db.execute(text("""
        insert into public.platform_admins(user_id,role,status,granted_by,granted_at,revoked_at,reason)
        values (:user,:role,'active',:actor,now(),null,:reason)
        on conflict (user_id) do update set role=excluded.role,status='active',
          granted_by=excluded.granted_by,granted_at=now(),revoked_at=null,reason=excluded.reason
        returning user_id,role,status,granted_at
    """), {
        "user": payload.user_id, "role": payload.role, "actor": actor, "reason": payload.reason,
    })).mappings().one()
    await _audit(db, request, actor, "platform.admin.granted", "platform_admin",
                 payload.user_id, {"role": payload.role, "reason": payload.reason})
    await db.commit()
    return {"data": dict(row)}


@router.delete("/platform-admins/{user_id}", status_code=204)
async def revoke_platform_admin(
    user_id: UUID,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_super_admin(db, actor)
    if user_id == actor:
        raise HTTPException(status_code=409, detail="Super administrator cannot revoke their own access")
    target = (await db.execute(text("""
        select role,status from public.platform_admins where user_id=:user for update
    """), {"user": user_id})).mappings().first()
    if target is None or target["status"] != "active":
        raise HTTPException(status_code=404, detail="Active platform administrator not found")
    if target["role"] == "super_admin":
        count = await db.scalar(text("""
            select count(*) from public.platform_admins
            where role='super_admin' and status='active'
        """))
        if count <= 1:
            raise HTTPException(status_code=409, detail="The last active super administrator cannot be revoked")
    await db.execute(text("""
        update public.platform_admins set status='revoked',revoked_at=now()
        where user_id=:user
    """), {"user": user_id})
    await _audit(db, request, actor, "platform.admin.revoked", "platform_admin", user_id)
    await db.commit()
    return None


@router.get("/llm/providers")
async def platform_llm_providers(
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    return {"data": {
        "available_providers": model_router.available(),
        "configured_model": settings.llm_model_key,
        "openai_credential_configured": bool(settings.openai_api_key_value),
        "generation_ready": "openai" in model_router.available(),
    }}


class RenderProfileInput(BaseModel):
    profile_key:str=Field(min_length=2,max_length=64,pattern=r"^[a-z0-9][a-z0-9-]*$")
    name:str=Field(min_length=2,max_length=120)
    description:str|None=Field(default=None,max_length=500)
    width:int=Field(ge=320,le=7680)
    height:int=Field(ge=240,le=4320)
    fps:int=Field(ge=1,le=120)
    container:str=Field(pattern=r"^(mp4|webm)$")
    video_codec:str=Field(pattern=r"^(h264|h265|vp8|vp9)$")
    video_crf:int=Field(ge=0,le=51)
    video_bitrate:str|None=Field(default=None,max_length=32)
    audio_codec:str=Field(pattern=r"^(aac|opus|none)$")
    audio_bitrate:str|None=Field(default=None,max_length=32)
    render_concurrency:int=Field(default=2,ge=1,le=8)
    priority:int=Field(default=10,ge=0,le=100)
    thumbnail_enabled:bool=True
    preview_enabled:bool=True
    is_default:bool=False

    def validate_codec_pair(self):
        if self.container=="mp4" and (self.video_codec not in {"h264","h265"} or self.audio_codec not in {"aac","none"}):
            raise HTTPException(422,"MP4 supports H.264/H.265 and AAC/no audio")
        if self.container=="webm" and (self.video_codec not in {"vp8","vp9"} or self.audio_codec not in {"opus","none"}):
            raise HTTPException(422,"WebM supports VP8/VP9 and Opus/no audio")
        return self


@router.get("/render-settings")
async def admin_get_render_settings(claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    row = (await db.execute(text("""
        select singleton_id,max_concurrent_jobs,lease_seconds,max_attempts,
               max_output_bytes,updated_by,updated_at
        from public.platform_render_settings
        where singleton_id=1
    """))).mappings().first()
    if row is None:
        raise HTTPException(status_code=503, detail="Global render settings are not initialized")
    return {"data": dict(row)}


@router.patch("/render-settings")
async def admin_update_render_settings(
    payload: RenderSettingsInput,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    row = (await db.execute(text("""
        update public.platform_render_settings
        set max_concurrent_jobs=:concurrency,
            lease_seconds=:lease,
            max_attempts=:attempts,
            max_output_bytes=:max_bytes,
            updated_by=:actor,
            updated_at=now()
        where singleton_id=1
        returning singleton_id,max_concurrent_jobs,lease_seconds,max_attempts,
                  max_output_bytes,updated_by,updated_at
    """), {
        "concurrency": payload.max_concurrent_jobs,
        "lease": payload.lease_seconds,
        "attempts": payload.max_attempts,
        "max_bytes": payload.max_output_bytes,
        "actor": actor,
    })).mappings().first()
    if row is None:
        raise HTTPException(status_code=503, detail="Global render settings are not initialized")
    await _audit(db, request, actor, "platform.render_settings.updated", "render_settings",
                 UUID(int=1), {
                     "max_concurrent_jobs": payload.max_concurrent_jobs,
                     "lease_seconds": payload.lease_seconds,
                     "max_attempts": payload.max_attempts,
                     "max_output_bytes": payload.max_output_bytes,
                 })
    await db.commit()
    return {"data": dict(row)}


@router.get("/render-profiles")
async def admin_list_render_profiles(claims:AuthenticatedClaims,include_archived:bool=False,db:AsyncSession=DbSession):
    actor=_actor(claims);await _require_platform_admin(db,actor)
    rows=(await db.execute(text("""
        select id,profile_key,name,description,scope,version,width,height,fps,container,video_codec,
          video_crf,video_bitrate,audio_codec,audio_bitrate,render_concurrency,priority,
          thumbnail_enabled,preview_enabled,is_default,is_archived,updated_at
        from public.render_profiles where scope='global' and (:archived or is_archived=false)
        order by profile_key,version desc
    """),{"archived":include_archived})).mappings().all()
    return {"data":[dict(r) for r in rows]}


@router.post("/render-profiles",status_code=201)
async def admin_create_render_profile(payload:RenderProfileInput,request:Request,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
    actor=_actor(claims);await _require_platform_admin(db,actor)
    payload.validate_codec_pair()
    if payload.is_default:
        await db.execute(text("update public.render_profiles set is_default=false where scope='global'"))
    row=(await db.execute(text("""
        insert into public.render_profiles(profile_key,name,description,scope,version,width,height,fps,container,
          video_codec,video_crf,video_bitrate,audio_codec,audio_bitrate,render_concurrency,priority,
          thumbnail_enabled,preview_enabled,is_default,created_by,updated_by)
        values(:key,:name,:description,'global',
          (select coalesce(max(version),0)+1 from public.render_profiles where profile_key=:key and scope='global'),
          :width,:height,:fps,:container,:video_codec,:crf,
          :video_bitrate,:audio_codec,:audio_bitrate,:concurrency,:priority,:thumbnail,:preview,:default,:actor,:actor)
        returning *
    """),{"key":payload.profile_key,"name":payload.name,"description":payload.description,"width":payload.width,
      "height":payload.height,"fps":payload.fps,"container":payload.container,"video_codec":payload.video_codec,
      "crf":payload.video_crf,"video_bitrate":payload.video_bitrate,"audio_codec":payload.audio_codec,
      "audio_bitrate":payload.audio_bitrate,"concurrency":payload.render_concurrency,"priority":payload.priority,
      "thumbnail":payload.thumbnail_enabled,"preview":payload.preview_enabled,"default":payload.is_default,"actor":actor})).mappings().one()
    await _audit(db,request,actor,"render_profile.created","render_profile",row["id"],{"profile_key":payload.profile_key,"version":row["version"]})
    await db.commit()
    return {"data":dict(row)}


@router.patch("/render-profiles/{profile_id}")
async def admin_version_render_profile(profile_id:UUID,payload:RenderProfileInput,request:Request,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
    actor=_actor(claims);await _require_platform_admin(db,actor);payload.validate_codec_pair()
    previous=(await db.execute(text("select * from public.render_profiles where id=:id and scope='global' and is_archived=false for update"),{"id":profile_id})).mappings().first()
    if not previous:raise HTTPException(404,"Active global render profile not found")
    if payload.profile_key!=previous["profile_key"]:raise HTTPException(422,"Profile key cannot be changed when versioning an existing profile")
    if payload.is_default:await db.execute(text("update public.render_profiles set is_default=false where scope='global'"))
    await db.execute(text("update public.render_profiles set is_archived=true,is_default=false,updated_by=:actor where id=:id"),{"actor":actor,"id":profile_id})
    values=payload.model_dump()
    row=(await db.execute(text("""
      insert into public.render_profiles(profile_key,name,description,scope,version,width,height,fps,container,video_codec,
       video_crf,video_bitrate,audio_codec,audio_bitrate,render_concurrency,priority,thumbnail_enabled,preview_enabled,is_default,created_by,updated_by)
      values(:profile_key,:name,:description,'global',:version,:width,:height,:fps,:container,:video_codec,:video_crf,
       :video_bitrate,:audio_codec,:audio_bitrate,:render_concurrency,:priority,:thumbnail_enabled,:preview_enabled,:is_default,:actor,:actor)
      returning *
    """),{**values,"version":int(previous["version"])+1,"actor":actor})).mappings().one()
    await _audit(db,request,actor,"render_profile.versioned","render_profile",row["id"],{"previous_id":str(profile_id),"version":row["version"]})
    await db.commit();return {"data":dict(row)}


@router.post("/render-profiles/{profile_id}/archive")
async def admin_archive_render_profile(profile_id:UUID,request:Request,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
    actor=_actor(claims);await _require_platform_admin(db,actor)
    row=(await db.execute(text("update public.render_profiles set is_archived=true,is_default=false,updated_by=:actor where id=:id and scope='global' and is_archived=false returning id,profile_key,version"),{"actor":actor,"id":profile_id})).mappings().first()
    if not row:raise HTTPException(404,"Active global render profile not found")
    await _audit(db,request,actor,"render_profile.archived","render_profile",row["id"],{"profile_key":row["profile_key"],"version":row["version"]})
    await db.commit();return {"data":dict(row)}


@router.get("/motion-components")
async def admin_list_motion_components(claims:AuthenticatedClaims,db:AsyncSession=DbSession):
    actor=_actor(claims);await _require_platform_admin(db,actor)
    rows=(await db.execute(text("select component_key,component_version,category,enabled,reason,updated_by,updated_at from public.motion_component_controls order by category,component_key"))).mappings().all()
    return {"data":[dict(r) for r in rows]}


class MotionComponentToggle(BaseModel):
    enabled:bool
    reason:str=Field(min_length=3,max_length=500)


@router.patch("/motion-components/{component_key}")
async def admin_toggle_motion_component(component_key:str,payload:MotionComponentToggle,request:Request,claims:AuthenticatedClaims,db:AsyncSession=DbSession):
    actor=_actor(claims);await _require_platform_admin(db,actor)
    row=(await db.execute(text("update public.motion_component_controls set enabled=:enabled,reason=:reason,updated_by=:actor,updated_at=now() where component_key=:key returning component_key,component_version,category,enabled,reason,updated_at"),{"enabled":payload.enabled,"reason":payload.reason,"actor":actor,"key":component_key})).mappings().first()
    if not row:raise HTTPException(404,"Allowlisted motion component not found")
    await db.execute(text("insert into public.audit_logs(actor_user_id,action,resource_type,metadata,request_id) values(:actor,'platform.motion_component.toggled','motion_component',cast(:metadata as jsonb),:request)"),{"actor":actor,"metadata":json.dumps({"component_key":component_key,"enabled":payload.enabled,"reason":payload.reason}),"request":request.state.request_id})
    await db.commit();return {"data":dict(row)}


@router.get("/workers")
async def admin_list_workers(claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    rows = (await db.execute(text("""
        select worker_id,worker_type,hostname,version,status,metadata,started_at,last_seen_at,
               case when last_seen_at > now()-interval '90 seconds' then 'online' else 'stale' end runtime_status
        from public.worker_heartbeats
        order by worker_type, last_seen_at desc
    """))).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.get("/render-jobs")
async def admin_list_render_jobs(claims:AuthenticatedClaims,page:int=Query(default=1,ge=1),per_page:int=Query(default=50,ge=1,le=100),status:str|None=Query(default=None,max_length=32),db:AsyncSession=DbSession):
    actor=_actor(claims);await _require_platform_admin(db,actor)
    rows=(await db.execute(text("""
      select r.id,r.project_id,r.workspace_id,r.status,r.progress_percent,r.attempt_count,r.worker_id,
       r.lease_expires_at,r.timeline_hash,r.snapshot_version,r.created_at,r.started_at,r.completed_at,
       p.name project_name,w.name workspace_name,rp.name render_profile,
       (select a.status from public.render_attempts a where a.render_job_id=r.id order by a.attempt_number desc limit 1) latest_attempt_status
      from public.render_jobs r join public.video_projects p on p.id=r.project_id
      join public.workspaces w on w.id=r.workspace_id left join public.render_profiles rp on rp.id=r.render_profile_id
      where (:status is null or r.status=:status) order by r.created_at desc limit :limit offset :offset
    """),{"status":status,"limit":per_page,"offset":(page-1)*per_page})).mappings().all()
    return {"data":[dict(r) for r in rows],"page":{"number":page,"size":per_page}}


@router.get("/media-jobs")
async def admin_list_media_jobs(claims:AuthenticatedClaims,page:int=Query(default=1,ge=1),per_page:int=Query(default=50,ge=1,le=100),status:str|None=Query(default=None,max_length=32),db:AsyncSession=DbSession):
    actor=_actor(claims);await _require_platform_admin(db,actor)
    rows=(await db.execute(text("""
      select a.id,a.project_id,a.workspace_id,a.status,a.provider_key,a.model_key,a.voice_key,
        a.worker_id,a.lease_expires_at,a.attempt_count,a.max_attempts,a.error_code,a.asset_id,a.created_at,a.completed_at,
        p.name project_name,w.name workspace_name
      from public.audio_generations a join public.video_projects p on p.id=a.project_id
      join public.workspaces w on w.id=a.workspace_id
      where (:status is null or a.status=:status)
      order by a.created_at desc limit :limit offset :offset
    """),{"status":status,"limit":per_page,"offset":(page-1)*per_page})).mappings().all()
    return {"data":[dict(r) for r in rows],"page":{"number":page,"size":per_page}}

@router.post("/render-jobs/{render_job_id}/retry", status_code=202)
async def admin_retry_render_job(
    render_job_id: UUID,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    row = (await db.execute(text("""
        update public.render_jobs
        set status='queued',
            progress_percent=0,
            max_attempts=greatest(max_attempts, attempt_count + 1),
            error_code=null,
            error_message_safe=null,
            worker_id=null,
            lease_expires_at=null,
            completed_at=null
        where id=:job and status='failed' and attempt_count < 10
        returning id, attempt_count, max_attempts,workspace_id,project_id,timeline_snapshot
    """), {"job": render_job_id})).mappings().first()
    if row is None:
        exists = await db.scalar(text("select exists(select 1 from public.render_jobs where id=:job)"),
                                 {"job": render_job_id})
        if not exists:
            raise HTTPException(status_code=404, detail="Render job not found")
        raise HTTPException(status_code=409, detail="Only failed render jobs can be retried")
    await _audit(db, request, actor, "platform.render_job.retried", "render_job",
                 render_job_id, {"attempt_count": row["attempt_count"], "max_attempts": row["max_attempts"]})
    await db.commit()
    await notify_worker("render", str(render_job_id))
    return {"data": {"render_job_id": str(render_job_id), "status": "queued"}}


@router.post("/media-jobs/{generation_id}/retry", status_code=202)
async def admin_retry_media_job(
    generation_id: UUID,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    row = (await db.execute(text("""
        update public.audio_generations
        set status='queued',
            max_attempts=greatest(max_attempts, attempt_count + 1),
            error_code=null,
            worker_id=null,
            lease_expires_at=null,
            completed_at=null
        where id=:job and status in ('failed','provider_unavailable') and attempt_count < 10
        returning id, attempt_count, max_attempts,workspace_id,project_id,input_text
    """), {"job": generation_id})).mappings().first()
    if row is None:
        exists = await db.scalar(text("select exists(select 1 from public.audio_generations where id=:job)"),
                                 {"job": generation_id})
        if not exists:
            raise HTTPException(status_code=404, detail="Media job not found")
        raise HTTPException(status_code=409, detail="Only failed or unavailable media jobs can be retried")
    await _audit(db, request, actor, "platform.media_job.retried", "audio_generation",
                 generation_id, {"attempt_count": row["attempt_count"], "max_attempts": row["max_attempts"]})
    await db.commit()
    await notify_worker("media", str(generation_id))
    return {"data": {"generation_id": str(generation_id), "status": "queued"}}



@router.get("/usage")
async def platform_usage(
    claims: AuthenticatedClaims, days: int = Query(default=30, ge=1, le=90),
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _require_platform_admin(db, actor)
    totals = (await db.execute(text("""
        select coalesce(sum(input_tokens),0)::bigint as input_tokens,
          coalesce(sum(output_tokens),0)::bigint as output_tokens,
          count(*)::bigint as events
        from public.ai_usage_events
        where created_at >= now()-make_interval(days => :days)
    """), {"days": days})).mappings().one()
    breakdown = (await db.execute(text("""
        select provider_key,model_key,
          coalesce(sum(input_tokens),0)::bigint as input_tokens,
          coalesce(sum(output_tokens),0)::bigint as output_tokens,
          count(*)::bigint as events
        from public.ai_usage_events
        where created_at >= now()-make_interval(days => :days)
        group by provider_key,model_key
        order by events desc limit 100
    """), {"days": days})).mappings().all()
    return {"data": {"period_days": days, "totals": dict(totals),
                     "by_provider_model": [dict(row) for row in breakdown]}}
