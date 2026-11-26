from __future__ import annotations

import hashlib
import secrets
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims
from app.core.database import get_db_session
from app.services.supabase_auth import supabase_auth
from app.services.workspace_authorization import WorkspacePermissionResolver
from app.core.redis import redis_client

router = APIRouter()
Db = Depends(get_db_session)

async def auth_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = f"graphytion:ratelimit:auth:{client_ip}:{request.url.path}"
    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, 60)
        if count > 10:
            raise HTTPException(status_code=429, detail="Too many authentication requests; retry later")
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=503, detail="Authentication rate limiter unavailable") from exc

class AuthSignup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=10, max_length=128)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)

class AuthLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    password: str = Field(min_length=1, max_length=128)

class PasswordUpdate(BaseModel):
    password: str = Field(min_length=10, max_length=128)

class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=20, max_length=4096)

class EmailRequest(BaseModel):
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

class VerifyEmail(BaseModel):
    token_hash: str = Field(min_length=20, max_length=512)
    type: str = Field(default="signup", pattern=r"^(signup|email|recovery|invite|magiclink|email_change)$")

class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    bio: str | None = Field(default=None, max_length=500)
    avatar_path: str | None = Field(default=None, max_length=512)
    locale: str | None = Field(default=None, max_length=16)
    timezone: str | None = Field(default=None, max_length=64)

class WorkspaceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    slug: str = Field(min_length=2, max_length=64, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

class WorkspaceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=120)
    settings: dict[str, Any] | None = None

class RoleUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: str = Field(pattern=r"^(admin|editor|member|viewer|billing)$")

class InviteCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    email: str = Field(pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
    role: str = Field(pattern=r"^(admin|editor|member|viewer|billing)$")

class InviteAccept(BaseModel):
    token: str = Field(min_length=32, max_length=256)

class ProjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    production_mode: str = Field(default="standard", max_length=40)
    default_language: str = Field(default="id-ID", max_length=16)
    target_duration_ms: int | None = Field(default=None, gt=0)
    aspect_ratio: str = Field(default="16:9", max_length=16)
    width: int = Field(default=1920, ge=1, le=16384)
    height: int = Field(default=1080, ge=1, le=16384)
    fps: int = Field(default=30, ge=1, le=120)
    settings: dict[str, Any] = Field(default_factory=dict)

class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    production_mode: str | None = Field(default=None, max_length=40)
    default_language: str | None = Field(default=None, max_length=16)
    target_duration_ms: int | None = Field(default=None, gt=0)
    aspect_ratio: str | None = Field(default=None, max_length=16)
    width: int | None = Field(default=None, ge=1, le=16384)
    height: int | None = Field(default=None, ge=1, le=16384)
    fps: int | None = Field(default=None, ge=1, le=120)
    settings: dict[str, Any] | None = None

def uid(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid authenticated subject") from exc

async def require_workspace(db: AsyncSession, user_id: UUID, workspace_id: UUID, roles: set[str] | None = None) -> str:
    return await WorkspacePermissionResolver().require_membership(
        session=db, user_id=str(user_id), workspace_id=str(workspace_id), allowed_roles=roles
    )

async def audit(db: AsyncSession, actor: UUID, workspace: UUID | None, action: str, resource: str, resource_id: UUID | None, request: Request) -> None:
    await db.execute(text("""
      insert into public.audit_logs(actor_user_id,workspace_id,action,resource_type,resource_id,request_id)
      values (:actor,:workspace,:action,:resource,:resource_id,:request_id)
    """), {"actor":actor,"workspace":workspace,"action":action,"resource":resource,"resource_id":resource_id,"request_id":getattr(request.state,"request_id",None)})

@router.post("/auth/signup", status_code=201, dependencies=[Depends(auth_rate_limit)])
async def signup(payload: AuthSignup):
    return await supabase_auth.signup(payload.email, payload.password, payload.display_name)

@router.post("/auth/login", dependencies=[Depends(auth_rate_limit)])
async def login(payload: AuthLogin):
    return await supabase_auth.login(payload.email, payload.password)

@router.post("/auth/refresh", dependencies=[Depends(auth_rate_limit)])
async def refresh(payload: RefreshRequest):
    return await supabase_auth.refresh(payload.refresh_token)

@router.post("/auth/logout", status_code=204, dependencies=[Depends(auth_rate_limit)])
async def logout(claims: AuthenticatedClaims, authorization: str = Header()):
    await supabase_auth.logout(authorization.removeprefix("Bearer ").strip())
    return None

@router.post("/auth/password", dependencies=[Depends(auth_rate_limit)])
async def update_password(payload: PasswordUpdate, claims: AuthenticatedClaims):
    return await supabase_auth.update_password(claims["_access_token"], payload.password)

@router.post("/auth/recovery", dependencies=[Depends(auth_rate_limit)])
async def recovery(payload: EmailRequest):
    return await supabase_auth.recover(payload.email)

@router.post("/auth/verify", dependencies=[Depends(auth_rate_limit)])
async def verify_email(payload: VerifyEmail):
    return await supabase_auth.verify_email(payload.token_hash, payload.type)

@router.post("/auth/resend-verification", dependencies=[Depends(auth_rate_limit)])
async def resend_verification(payload: EmailRequest):
    return await supabase_auth.resend_verification(payload.email)

@router.get("/me")
async def current_user(claims: AuthenticatedClaims, db: AsyncSession = Db):
    user_id = uid(claims)
    auth_user = await supabase_auth.verify_user(claims["_access_token"])
    row = (await db.execute(text("""
      insert into public.profiles(id,display_name)
      values (:id,:display_name)
      on conflict (id) do update set updated_at=now()
      returning id,display_name,avatar_path,bio,locale,timezone,created_at,updated_at
    """), {"id":user_id,"display_name":(auth_user.get("user_metadata") or {}).get("display_name")})).mappings().one()
    await db.commit()
    return {"data":dict(row)}

@router.patch("/me")
async def update_profile(payload: ProfileUpdate, claims: AuthenticatedClaims, db: AsyncSession = Db):
    user_id = uid(claims)
    values = payload.model_dump(exclude_unset=True)
    if "avatar_path" in values and values["avatar_path"] is not None:
        if not values["avatar_path"].startswith(f"{user_id}/"):
            raise HTTPException(status_code=403, detail="Avatar path must be owned by the authenticated user")
    if not values:
        raise HTTPException(status_code=400, detail="No profile fields supplied")
    assignments = ", ".join(f"{key}=:{key}" for key in values)
    row = (await db.execute(text(f"""
      update public.profiles set {assignments},updated_at=now()
      where id=:user_id returning id,display_name,avatar_path,bio,locale,timezone,updated_at
    """), {**values,"user_id":user_id})).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    await db.commit()
    return {"data":dict(row)}

@router.get("/workspaces")
async def list_workspaces(claims: AuthenticatedClaims, db: AsyncSession = Db):
    rows = (await db.execute(text("""
      select w.id,w.name,w.slug,w.owner_user_id,w.settings,w.created_at,w.updated_at,m.role
      from public.workspaces w join public.workspace_members m on m.workspace_id=w.id
      where m.user_id=:user_id and m.status='active' order by w.updated_at desc
    """), {"user_id":uid(claims)})).mappings().all()
    return {"data":[dict(row) for row in rows]}

@router.post("/workspaces", status_code=201)
async def create_workspace(payload: WorkspaceCreate, request: Request, claims: AuthenticatedClaims, db: AsyncSession = Db):
    user_id = uid(claims)
    try:
        row = (await db.execute(text("""
          insert into public.workspaces(name,slug,owner_user_id)
          values (:name,:slug,:owner) returning *
        """), {"name":payload.name.strip(),"slug":payload.slug,"owner":user_id})).mappings().one()
        await db.execute(text("""
          insert into public.workspace_members(workspace_id,user_id,role,status)
          values (:workspace,:user,'owner','active')
        """), {"workspace":row["id"],"user":user_id})
        await audit(db,user_id,row["id"],"workspace.created","workspace",row["id"],request)
        await db.commit()
        return {"data":dict(row)}
    except Exception:
        await db.rollback()
        raise

@router.get("/workspaces/{workspace_id}")
async def get_workspace(workspace_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = Db):
    await require_workspace(db,uid(claims),workspace_id)
    row = (await db.execute(text("select * from public.workspaces where id=:id"),{"id":workspace_id})).mappings().one()
    return {"data":dict(row)}

@router.patch("/workspaces/{workspace_id}")
async def update_workspace(workspace_id: UUID, payload: WorkspaceUpdate, request: Request, claims: AuthenticatedClaims, db: AsyncSession = Db):
    user_id=uid(claims); await require_workspace(db,user_id,workspace_id,{"owner","admin"})
    values=payload.model_dump(exclude_unset=True)
    if not values: raise HTTPException(status_code=400,detail="No workspace fields supplied")
    if "settings" in values:
        values["settings"] = __import__("json").dumps(values["settings"])
    assignments=", ".join(("settings=cast(:settings as jsonb)" if key=="settings" else f"{key}=:{key}") for key in values)
    row=(await db.execute(text(f"update public.workspaces set {assignments},updated_at=now() where id=:id returning *"),{**values,"id":workspace_id})).mappings().one()
    await audit(db,user_id,workspace_id,"workspace.updated","workspace",workspace_id,request); await db.commit()
    return {"data":dict(row)}


@router.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(workspace_id: UUID, request: Request, claims: AuthenticatedClaims, db: AsyncSession = Db):
    actor=uid(claims); await require_workspace(db,actor,workspace_id,{"owner"})
    project_count=(await db.execute(text("select count(*) from public.video_projects where workspace_id=:workspace"),{"workspace":workspace_id})).scalar_one()
    if project_count:
        raise HTTPException(status_code=409,detail="Workspace contains projects; archive or transfer them before deleting the workspace")
    await audit(db,actor,workspace_id,"workspace.deleted","workspace",workspace_id,request)
    await db.execute(text("delete from public.workspaces where id=:workspace"),{"workspace":workspace_id})
    await db.commit()
    return None

@router.get("/workspaces/{workspace_id}/members")
async def list_members(workspace_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = Db):
    await require_workspace(db,uid(claims),workspace_id)
    rows=(await db.execute(text("""
      select m.id,m.workspace_id,m.user_id,m.role,m.status,m.created_at,p.display_name
      from public.workspace_members m join public.profiles p on p.id=m.user_id
      where m.workspace_id=:workspace order by m.created_at
    """),{"workspace":workspace_id})).mappings().all()
    return {"data":[dict(r) for r in rows]}

@router.post("/workspaces/{workspace_id}/invitations",status_code=201)
async def create_invitation(workspace_id: UUID,payload: InviteCreate,request: Request,claims: AuthenticatedClaims,db: AsyncSession=Db):
    actor=uid(claims); await require_workspace(db,actor,workspace_id,{"owner","admin"})
    raw=secrets.token_urlsafe(36); digest=hashlib.sha256(raw.encode()).hexdigest()
    row=(await db.execute(text("""
      insert into public.workspace_invitations(workspace_id,email,role,token_hash,invited_by,expires_at)
      values (:workspace,lower(:email),:role,:digest,:actor,now()+interval '7 days')
      returning id,workspace_id,email,role,expires_at,created_at
    """),{"workspace":workspace_id,"email":payload.email,"role":payload.role,"digest":digest,"actor":actor})).mappings().one()
    await audit(db,actor,workspace_id,"workspace.invitation.created","invitation",row["id"],request); await db.commit()
    return {"data":dict(row),"invitation_token":raw}


@router.patch("/workspaces/{workspace_id}/members/{member_id}")
async def update_member_role(workspace_id: UUID, member_id: UUID, payload: RoleUpdate, request: Request, claims: AuthenticatedClaims, db: AsyncSession = Db):
    actor=uid(claims); await require_workspace(db,actor,workspace_id,{"owner","admin"})
    target=(await db.execute(text("select user_id,role from public.workspace_members where id=:member and workspace_id=:workspace and status='active'"),{"member":member_id,"workspace":workspace_id})).mappings().first()
    if not target: raise HTTPException(status_code=404,detail="Workspace member not found")
    if target["role"]=="owner": raise HTTPException(status_code=409,detail="Workspace ownership cannot be changed through role management")
    if payload.role=="owner": raise HTTPException(status_code=400,detail="Use the ownership transfer workflow")
    if target["role"]=="admin" and (await require_workspace(db,actor,workspace_id))!="owner":
        raise HTTPException(status_code=403,detail="Only the owner can change an administrator")
    await db.execute(text("update public.workspace_members set role=:role where id=:member"),{"role":payload.role,"member":member_id})
    await audit(db,actor,workspace_id,"workspace.member.role_changed","workspace_member",member_id,request)
    await db.commit()
    return {"data":{"member_id":str(member_id),"role":payload.role}}

@router.delete("/workspaces/{workspace_id}/members/{member_id}",status_code=204)
async def remove_workspace_member(workspace_id: UUID, member_id: UUID, request: Request, claims: AuthenticatedClaims, db: AsyncSession = Db):
    actor=uid(claims); actor_role=await require_workspace(db,actor,workspace_id,{"owner","admin"})
    target=(await db.execute(text("select user_id,role from public.workspace_members where id=:member and workspace_id=:workspace and status='active'"),{"member":member_id,"workspace":workspace_id})).mappings().first()
    if not target: raise HTTPException(status_code=404,detail="Workspace member not found")
    if target["role"]=="owner": raise HTTPException(status_code=409,detail="Workspace owner cannot be removed")
    if target["role"]=="admin" and actor_role!="owner": raise HTTPException(status_code=403,detail="Only the owner can remove an administrator")
    await db.execute(text("update public.workspace_members set status='left' where id=:member"),{"member":member_id})
    await audit(db,actor,workspace_id,"workspace.member.removed","workspace_member",member_id,request)
    await db.commit()
    return None

@router.delete("/workspaces/{workspace_id}/invitations/{invitation_id}",status_code=204)
async def cancel_invitation(workspace_id: UUID, invitation_id: UUID, request: Request, claims: AuthenticatedClaims, db: AsyncSession = Db):
    actor=uid(claims); await require_workspace(db,actor,workspace_id,{"owner","admin"})
    result=await db.execute(text("""
      update public.workspace_invitations set cancelled_at=now()
      where id=:invitation and workspace_id=:workspace and accepted_at is null and cancelled_at is null
    """),{"invitation":invitation_id,"workspace":workspace_id})
    if result.rowcount==0: raise HTTPException(status_code=404,detail="Pending invitation not found")
    await audit(db,actor,workspace_id,"workspace.invitation.cancelled","invitation",invitation_id,request)
    await db.commit()
    return None

@router.post("/invitations/accept")
async def accept_invitation(payload: InviteAccept,claims: AuthenticatedClaims,db: AsyncSession=Db):
    actor=uid(claims); digest=hashlib.sha256(payload.token.encode()).hexdigest()
    try:
        row=(await db.execute(text("""
          select i.* from public.workspace_invitations i
          join auth.users u on lower(u.email)=lower(i.email)
          where i.token_hash=:digest and u.id=:actor and i.accepted_at is null
            and i.cancelled_at is null and i.expires_at>now()
          for update of i
        """),{"digest":digest,"actor":actor})).mappings().first()
        if not row: raise HTTPException(status_code=404,detail="Invitation is invalid or expired")
        await db.execute(text("""
          insert into public.workspace_members(workspace_id,user_id,role,status)
          values (:workspace,:actor,:role,'active')
          on conflict (workspace_id,user_id) do update set role=excluded.role,status='active'
        """),{"workspace":row["workspace_id"],"actor":actor,"role":row["role"]})
        await db.execute(text("update public.workspace_invitations set accepted_at=now() where id=:id"),{"id":row["id"]})
        await db.commit()
        return {"data":{"workspace_id":str(row["workspace_id"]),"role":row["role"],"accepted":True}}
    except Exception:
        await db.rollback(); raise

@router.post("/workspaces/{workspace_id}/leave",status_code=204)
async def leave_workspace(workspace_id: UUID,claims: AuthenticatedClaims,db: AsyncSession=Db):
    actor=uid(claims)
    role=await require_workspace(db,actor,workspace_id)
    if role=="owner": raise HTTPException(status_code=409,detail="Transfer ownership before leaving")
    await db.execute(text("update public.workspace_members set status='left' where workspace_id=:workspace and user_id=:user"),{"workspace":workspace_id,"user":actor})
    await db.commit()
    return None

@router.get("/workspaces/{workspace_id}/projects")
async def list_projects(workspace_id: UUID,claims: AuthenticatedClaims,db: AsyncSession=Db,q: str|None=Query(default=None,max_length=160),status_filter: str|None=Query(default=None,alias="status"),sort: str=Query(default="updated_at",pattern="^(updated_at|created_at|name)$"),direction: str=Query(default="desc",pattern="^(asc|desc)$"),limit: int=Query(default=25,ge=1,le=100),offset: int=Query(default=0,ge=0)):
    await require_workspace(db,uid(claims),workspace_id)
    rows=(await db.execute(text(f"""
      select * from public.video_projects
      where workspace_id=:workspace and status<>'deleted'
        and (:q is null or name ilike '%'||:q||'%')
        and (:status is null or status=:status)
      order by {sort} {direction} limit :limit offset :offset
    """),{"workspace":workspace_id,"q":q,"status":status_filter,"limit":limit,"offset":offset})).mappings().all()
    return {"data":[dict(r) for r in rows],"page":{"limit":limit,"offset":offset}}

@router.post("/workspaces/{workspace_id}/projects",status_code=201)
async def create_project(workspace_id: UUID,payload: ProjectCreate,request: Request,claims: AuthenticatedClaims,db: AsyncSession=Db):
    actor=uid(claims); await require_workspace(db,actor,workspace_id,{"owner","admin","editor","member"})
    try:
        row=(await db.execute(text("""
          insert into public.video_projects(workspace_id,created_by,name,description,production_mode,default_language,target_duration_ms,aspect_ratio,width,height,fps)
          values (:workspace,:actor,:name,:description,:mode,:language,:duration,:ratio,:width,:height,:fps) returning *
        """),{"workspace":workspace_id,"actor":actor,"name":payload.name.strip(),"description":payload.description,"mode":payload.production_mode,"language":payload.default_language,"duration":payload.target_duration_ms,"ratio":payload.aspect_ratio,"width":payload.width,"height":payload.height,"fps":payload.fps})).mappings().one()
        await db.execute(text("insert into public.project_settings(project_id,settings) values (:id,cast(:settings as jsonb))"),{"id":row["id"],"settings":__import__("json").dumps(payload.settings)})
        await audit(db,actor,workspace_id,"project.created","video_project",row["id"],request); await db.commit()
        return {"data":dict(row)}
    except Exception:
        await db.rollback(); raise

@router.get("/projects/{project_id}")
async def get_project(project_id: UUID,claims: AuthenticatedClaims,db: AsyncSession=Db):
    actor=uid(claims)
    row=(await db.execute(text("""
      select p.*,s.settings,s.version as settings_version
      from public.video_projects p join public.workspace_members m on m.workspace_id=p.workspace_id
      left join public.project_settings s on s.project_id=p.id
      where p.id=:project and m.user_id=:actor and m.status='active' and p.status<>'deleted'
    """),{"project":project_id,"actor":actor})).mappings().first()
    if not row: raise HTTPException(status_code=404,detail="Project not found")
    return {"data":dict(row)}

@router.patch("/projects/{project_id}")
async def update_project(project_id: UUID,payload: ProjectUpdate,request: Request,claims: AuthenticatedClaims,db: AsyncSession=Db):
    actor=uid(claims)
    row=(await db.execute(text("""
      select p.workspace_id,m.role from public.video_projects p join public.workspace_members m on m.workspace_id=p.workspace_id
      where p.id=:project and m.user_id=:actor and m.status='active' and p.status<>'deleted'
    """),{"project":project_id,"actor":actor})).mappings().first()
    if not row: raise HTTPException(status_code=404,detail="Project not found")
    if row["role"] not in ("owner","admin","editor","member"): raise HTTPException(status_code=403,detail="Project update permission required")
    values=payload.model_dump(exclude_unset=True); settings=values.pop("settings",None)
    if not values and settings is None: raise HTTPException(status_code=400,detail="No project fields supplied")
    try:
        if values:
            assignments=", ".join(f"{key}=:{key}" for key in values)
            await db.execute(text(f"update public.video_projects set {assignments},updated_at=now() where id=:id"),{**values,"id":project_id})
        if settings is not None:
            await db.execute(text("""
              insert into public.project_settings(project_id,settings,version) values (:id,cast(:settings as jsonb),1)
              on conflict (project_id) do update set settings=excluded.settings,version=project_settings.version+1,updated_at=now()
            """),{"id":project_id,"settings":__import__("json").dumps(settings)})
        await audit(db,actor,row["workspace_id"],"project.updated","video_project",project_id,request)
        result=(await db.execute(text("select * from public.video_projects where id=:id"),{"id":project_id})).mappings().one()
        await db.commit(); return {"data":dict(result)}
    except Exception:
        await db.rollback(); raise

@router.post("/projects/{project_id}/archive")
async def archive_project(project_id: UUID,request: Request,claims: AuthenticatedClaims,db: AsyncSession=Db):
    return await _set_project_status(project_id,"archived",request,claims,db)

@router.post("/projects/{project_id}/restore")
async def restore_project(project_id: UUID,request: Request,claims: AuthenticatedClaims,db: AsyncSession=Db):
    return await _set_project_status(project_id,"draft",request,claims,db)

async def _set_project_status(project_id: UUID,new_status: str,request: Request,claims: AuthenticatedClaims,db: AsyncSession):
    actor=uid(claims)
    row=(await db.execute(text("""
      select p.workspace_id,m.role from public.video_projects p join public.workspace_members m on m.workspace_id=p.workspace_id
      where p.id=:project and m.user_id=:actor and m.status='active' and p.status<>'deleted'
    """),{"project":project_id,"actor":actor})).mappings().first()
    if not row: raise HTTPException(status_code=404,detail="Project not found")
    if row["role"] not in ("owner","admin","editor"): raise HTTPException(status_code=403,detail="Project lifecycle permission required")
    result=(await db.execute(text("update public.video_projects set status=:status,updated_at=now() where id=:id returning *"),{"status":new_status,"id":project_id})).mappings().one()
    await audit(db,actor,row["workspace_id"],f"project.{new_status}","video_project",project_id,request); await db.commit()
    return {"data":dict(result)}

@router.delete("/projects/{project_id}",status_code=204)
async def delete_project(project_id: UUID,request: Request,claims: AuthenticatedClaims,db: AsyncSession=Db):
    actor=uid(claims)
    row=(await db.execute(text("""
      select p.workspace_id,m.role from public.video_projects p join public.workspace_members m on m.workspace_id=p.workspace_id
      where p.id=:project and m.user_id=:actor and m.status='active' and p.status<>'deleted'
    """),{"project":project_id,"actor":actor})).mappings().first()
    if not row: raise HTTPException(status_code=404,detail="Project not found")
    if row["role"] not in ("owner","admin"): raise HTTPException(status_code=403,detail="Project delete permission required")
    await db.execute(text("update public.video_projects set status='deleted',updated_at=now() where id=:id"),{"id":project_id})
    await audit(db,actor,row["workspace_id"],"project.deleted","video_project",project_id,request); await db.commit()
    return None
