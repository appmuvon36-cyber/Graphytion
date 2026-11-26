from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims, DbSession
from app.core.database import set_rls_subject
from app.services.supabase_auth import supabase_auth

router = APIRouter()


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
          (select count(*) from public.production_runs where status in ('planning','scripting','storyboarding','queued','running')) as active_creative_runs
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
