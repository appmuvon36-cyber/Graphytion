from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import secrets
from datetime import UTC, datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Header, HTTPException, Query, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims
from app.core.config import settings
from app.core.database import get_db_session, set_rls_subject
from app.core.redis import redis_client
from app.services.idempotency import (
    complete_idempotency,
    reserve_idempotency,
    validate_idempotency_key,
)
from app.services.invitation_email import (
    InvitationEmailConfigurationError,
    InvitationEmailDeliveryError,
    invitation_email,
)
from app.services.supabase_auth import supabase_auth
from app.services.supabase_storage import SupabaseStorage
from app.services.workspace_authorization import (
    ROLE_PERMISSIONS,
    WorkspacePermissionResolver,
    WorkspaceRole,
)

router = APIRouter()
Db = Depends(get_db_session)


async def require_bff(request: Request) -> None:
    expected = settings.bff_shared_secret_value
    supplied = request.headers.get("X-Graphytion-BFF-Secret", "")
    if not expected or not supplied:
        raise HTTPException(status_code=503, detail="Secure session gateway is not configured")
    if not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=403, detail="Secure session gateway authentication failed")


async def auth_rate_limit(request: Request) -> None:
    client_ip = request.client.host if request.client else "unknown"
    key = f"graphytion:ratelimit:auth:{client_ip}:{request.url.path}"
    try:
        count = await redis_client.incr(key)
        if count == 1:
            await redis_client.expire(key, 60)
        if count > 10:
            raise HTTPException(
                status_code=429,
                detail="Too many authentication requests; retry later",
            )
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=503, detail="Authentication rate limiter unavailable"
        ) from exc


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
    type: str = Field(
        default="signup",
        pattern=r"^(signup|email|recovery|invite|magiclink|email_change)$",
    )


class ProfileUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    bio: str | None = Field(default=None, max_length=500)
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
    production_mode: str = Field(
        default="motion_graphic",
        pattern=r"^(motion_graphic|explainer|presentation|social_short|documentary_lite)$",
    )
    default_language: str = Field(default="id-ID", max_length=16)
    target_duration_ms: int | None = Field(default=None, gt=0)
    aspect_ratio: str = Field(default="16:9", pattern=r"^(16:9|9:16|1:1|4:5|4:3)$")
    width: int = Field(default=1920, ge=1, le=16384)
    height: int = Field(default=1080, ge=1, le=16384)
    fps: int = Field(default=30, ge=1, le=120)
    settings: dict[str, Any] = Field(default_factory=dict)


class ProjectUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=160)
    description: str | None = Field(default=None, max_length=4000)
    production_mode: str | None = Field(
        default=None,
        pattern=r"^(motion_graphic|explainer|presentation|social_short|documentary_lite)$",
    )
    default_language: str | None = Field(default=None, max_length=16)
    target_duration_ms: int | None = Field(default=None, gt=0)
    aspect_ratio: str | None = Field(default=None, pattern=r"^(16:9|9:16|1:1|4:5|4:3)$")
    width: int | None = Field(default=None, ge=1, le=16384)
    height: int | None = Field(default=None, ge=1, le=16384)
    fps: int | None = Field(default=None, ge=1, le=120)
    settings: dict[str, Any] | None = None


def uid(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid authenticated subject") from exc


async def require_permission(
    db: AsyncSession, user_id: UUID, workspace_id: UUID, permission: str
) -> str:
    role = await WorkspacePermissionResolver().require_permission(
        session=db,
        user_id=str(user_id),
        workspace_id=str(workspace_id),
        permission=permission,
    )
    return role.value


async def audit_auth_event(
    db: AsyncSession,
    request: Request,
    action: str,
    actor: UUID | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    if actor is not None:
        await set_rls_subject(db, str(actor))
    await db.execute(
        text("""
            insert into public.audit_logs(
                actor_user_id, action, resource_type, metadata, request_id
            )
            values (:actor,:action,'auth',cast(:metadata as jsonb),:request_id)
        """),
        {
            "actor": actor,
            "action": action,
            "metadata": json.dumps(metadata or {}),
            "request_id": getattr(request.state, "request_id", None),
        },
    )
    await db.commit()


async def audit(
    db: AsyncSession,
    actor: UUID,
    workspace: UUID | None,
    action: str,
    resource: str,
    resource_id: UUID | None,
    request: Request,
) -> None:
    await db.execute(
        text("""
      insert into public.audit_logs(
        actor_user_id, workspace_id, action, resource_type, resource_id, request_id
      )
      values (:actor,:workspace,:action,:resource,:resource_id,:request_id)
    """),
        {
            "actor": actor,
            "workspace": workspace,
            "action": action,
            "resource": resource,
            "resource_id": resource_id,
            "request_id": getattr(request.state, "request_id", None),
        },
    )


@router.post("/auth/signup", status_code=201, dependencies=[Depends(auth_rate_limit), Depends(require_bff)])
async def signup(payload: AuthSignup, request: Request, db: AsyncSession = Db):
    result = await supabase_auth.signup(payload.email, payload.password, payload.display_name)
    auth_user = result.get("user") or {}
    if auth_user.get("id"):
        await set_rls_subject(db, str(auth_user["id"]))
        await db.execute(
            text("""
                insert into public.audit_logs(
                    actor_user_id, action, resource_type, resource_id, request_id
                )
                values (:actor,'auth.signup','user',:resource,:request_id)
            """),
            {
                "actor": auth_user["id"],
                "resource": auth_user["id"],
                "request_id": getattr(request.state, "request_id", None),
            },
        )
        await db.commit()
    return result


@router.post("/auth/login", dependencies=[Depends(auth_rate_limit), Depends(require_bff)])
async def login(payload: AuthLogin, request: Request, db: AsyncSession = Db):
    result = await supabase_auth.login(payload.email, payload.password)
    auth_user = result.get("user") or {}
    if auth_user.get("id"):
        await db.execute(
            text("""
                insert into public.audit_logs(
                    actor_user_id, action, resource_type, resource_id, request_id
                )
                values (:actor,'auth.login','user',:resource,:request_id)
            """),
            {
                "actor": auth_user["id"],
                "resource": auth_user["id"],
                "request_id": getattr(request.state, "request_id", None),
            },
        )
        await db.commit()
    return result


@router.post("/auth/refresh", dependencies=[Depends(auth_rate_limit), Depends(require_bff)])
async def refresh(payload: RefreshRequest):
    return await supabase_auth.refresh(payload.refresh_token)


@router.post("/auth/logout", status_code=204, dependencies=[Depends(auth_rate_limit)])
async def logout(
    request: Request,
    claims: AuthenticatedClaims,
    authorization: str = Header(),
    db: AsyncSession = Db,
):
    actor = uid(claims)
    await supabase_auth.logout(authorization.removeprefix("Bearer ").strip())
    await db.execute(
        text("""
            insert into public.audit_logs(
                actor_user_id, action, resource_type, resource_id, request_id
            )
            values (:actor,'auth.logout','user',:resource,:request_id)
        """),
        {
            "actor": actor,
            "resource": actor,
            "request_id": getattr(request.state, "request_id", None),
        },
    )
    await db.commit()
    return None


@router.post("/auth/password", dependencies=[Depends(auth_rate_limit)])
async def update_password(
    payload: PasswordUpdate,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = Db,
):
    actor = uid(claims)
    result = await supabase_auth.update_password(claims["_access_token"], payload.password)
    await audit_auth_event(db, request, "auth.password.updated", actor)
    return result


@router.post("/auth/recovery", dependencies=[Depends(auth_rate_limit)])
async def recovery(payload: EmailRequest, request: Request, db: AsyncSession = Db):
    result = await supabase_auth.recover(payload.email)
    await audit_auth_event(
        db,
        request,
        "auth.recovery.requested",
        metadata={"email_sha256": hashlib.sha256(payload.email.lower().encode()).hexdigest()},
    )
    return result


@router.post("/auth/verify", dependencies=[Depends(auth_rate_limit), Depends(require_bff)])
async def verify_email(payload: VerifyEmail, request: Request, db: AsyncSession = Db):
    result = await supabase_auth.verify_email(payload.token_hash, payload.type)
    user = result.get("user") or {}
    actor = UUID(str(user["id"])) if user.get("id") else None
    await audit_auth_event(db, request, "auth.email.verified", actor)
    return result


@router.post("/auth/resend-verification", dependencies=[Depends(auth_rate_limit)])
async def resend_verification(payload: EmailRequest, request: Request, db: AsyncSession = Db):
    result = await supabase_auth.resend_verification(payload.email)
    await audit_auth_event(
        db,
        request,
        "auth.verification.resent",
        metadata={"email_sha256": hashlib.sha256(payload.email.lower().encode()).hexdigest()},
    )
    return result


@router.get("/me")
async def current_user(claims: AuthenticatedClaims, db: AsyncSession = Db):
    user_id = uid(claims)
    row = (
        (
            await db.execute(
                text("""
      insert into public.profiles(id)
      values (:id)
      on conflict (id) do update set updated_at=now()
      returning id,display_name,avatar_path,bio,locale,timezone,created_at,updated_at
    """),
                {"id": user_id},
            )
        )
        .mappings()
        .one()
    )
    await db.commit()
    return {"data": dict(row)}


@router.patch("/me")
async def update_profile(
    payload: ProfileUpdate, claims: AuthenticatedClaims, db: AsyncSession = Db
):
    user_id = uid(claims)
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=400, detail="No profile fields supplied")
    if "display_name" in values and values["display_name"] is not None:
        values["display_name"] = values["display_name"].strip()
        if not values["display_name"]:
            raise HTTPException(status_code=422, detail="Display name cannot be blank")
    if "bio" in values and values["bio"] is not None:
        values["bio"] = values["bio"].strip() or None
    assignments = ", ".join(f"{key}=:{key}" for key in values)
    row = (
        (
            await db.execute(
                text(f"""
      update public.profiles set {assignments},updated_at=now()
      where id=:user_id returning id,display_name,avatar_path,bio,locale,timezone,updated_at
    """),
                {**values, "user_id": user_id},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    await db.commit()
    return {"data": dict(row)}


@router.post("/me/avatar", status_code=201, dependencies=[Depends(auth_rate_limit)])
async def upload_avatar(
    claims: AuthenticatedClaims,
    file: Annotated[UploadFile, File()],
    db: AsyncSession = Db,
):
    user_id = uid(claims)
    content = await file.read(5 * 1024 * 1024 + 1)
    if not content or len(content) > 5 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Avatar must be between 1 byte and 5 MB")
    mime_signatures = {
        "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
        "image/jpeg": content.startswith(b"\xff\xd8\xff"),
        "image/webp": len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP",
    }
    content_type = file.content_type or ""
    if content_type not in mime_signatures or not mime_signatures[content_type]:
        raise HTTPException(
            status_code=415, detail="Only valid PNG, JPEG, and WebP images are accepted"
        )
    extension = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp"}[content_type]
    object_path = f"{user_id}/{secrets.token_hex(16)}.{extension}"
    try:
        await SupabaseStorage().upload(
            bucket="avatars", object_path=object_path, content=content, content_type=content_type
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Avatar storage upload failed") from exc
    row = (
        (
            await db.execute(
                text("""
                update public.profiles set avatar_path=:path,updated_at=now()
                where id=:user_id
                returning id,display_name,avatar_path,bio,locale,timezone,updated_at
            """),
                {"path": object_path, "user_id": user_id},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Profile not found")
    await db.commit()
    return {"data": dict(row)}


@router.get("/me/avatar-url")
async def get_avatar_url(claims: AuthenticatedClaims, db: AsyncSession = Db):
    user_id = uid(claims)
    path = (
        await db.execute(
            text("select avatar_path from public.profiles where id=:user_id"),
            {"user_id": user_id},
        )
    ).scalar_one_or_none()
    if not path:
        raise HTTPException(status_code=404, detail="Avatar not found")
    if not path.startswith(f"{user_id}/"):
        raise HTTPException(status_code=403, detail="Avatar ownership check failed")
    try:
        signed_url = await SupabaseStorage().create_signed_url(
            bucket="avatars", object_path=path, expires_in=300
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Avatar URL could not be created") from exc
    return {"data": {"signed_url": signed_url, "expires_in": 300}}


@router.get("/workspaces")
async def list_workspaces(claims: AuthenticatedClaims, db: AsyncSession = Db):
    rows = (
        (
            await db.execute(
                text("""
      select w.id,w.name,w.slug,w.owner_user_id,w.settings,w.created_at,w.updated_at,m.role
      from public.workspaces w join public.workspace_members m on m.workspace_id=w.id
      where m.user_id=:user_id and m.status='active' order by w.updated_at desc
    """),
                {"user_id": uid(claims)},
            )
        )
        .mappings()
        .all()
    )
    return {"data": [dict(row) for row in rows]}


@router.post("/workspaces", status_code=201)
async def create_workspace(
    payload: WorkspaceCreate,
    request: Request,
    claims: AuthenticatedClaims,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Db,
):
    user_id = uid(claims)
    try:
        reservation_id, cached = await reserve_idempotency(
            db,
            actor_user_id=user_id,
            operation="workspace.create",
            key=validate_idempotency_key(idempotency_key),
            payload=payload.model_dump(),
        )
        if cached is not None:
            await db.rollback()
            return cached
        workspace_name = payload.name.strip()
        if not workspace_name:
            raise HTTPException(status_code=422, detail="Workspace name cannot be blank")
        row = (
            (
                await db.execute(
                    text("""
          insert into public.workspaces(name,slug,owner_user_id)
          values (:name,:slug,:owner) returning *
        """),
                    {"name": workspace_name, "slug": payload.slug, "owner": user_id},
                )
            )
            .mappings()
            .one()
        )
        await db.execute(
            text("""
          insert into public.workspace_members(workspace_id,user_id,role,status)
          values (:workspace,:user,'owner','active')
        """),
            {"workspace": row["id"], "user": user_id},
        )
        await audit(db, user_id, row["id"], "workspace.created", "workspace", row["id"], request)
        response_body = {"data": dict(row)}
        await complete_idempotency(db, reservation_id, response_body)
        await db.commit()
        return response_body
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Workspace slug is already in use") from exc
    except Exception:
        await db.rollback()
        raise


@router.get("/workspaces/{workspace_id}")
async def get_workspace(workspace_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = Db):
    await require_permission(db, uid(claims), workspace_id, "workspace.read")
    row = (
        (
            await db.execute(
                text("select * from public.workspaces where id=:id"), {"id": workspace_id}
            )
        )
        .mappings()
        .one()
    )
    return {"data": dict(row)}


@router.patch("/workspaces/{workspace_id}")
async def update_workspace(
    workspace_id: UUID,
    payload: WorkspaceUpdate,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = Db,
):
    user_id = uid(claims)
    await require_permission(db, user_id, workspace_id, "workspace.update")
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(status_code=400, detail="No workspace fields supplied")
    if "name" in values and values["name"] is not None:
        values["name"] = values["name"].strip()
        if not values["name"]:
            raise HTTPException(status_code=422, detail="Workspace name cannot be blank")
    if "settings" in values:
        if len(json.dumps(values["settings"], default=str)) > 65536:
            raise HTTPException(status_code=413, detail="Workspace settings exceed 64 KB")
        values["settings"] = json.dumps(values["settings"])
    assignments = ", ".join(
        ("settings=cast(:settings as jsonb)" if key == "settings" else f"{key}=:{key}")
        for key in values
    )
    row = (
        (
            await db.execute(
                text(f"""
        update public.workspaces set {assignments}, updated_at=now()
        where id=:id returning *
      """),
                {**values, "id": workspace_id},
            )
        )
        .mappings()
        .one()
    )
    await audit(db, user_id, workspace_id, "workspace.updated", "workspace", workspace_id, request)
    await db.commit()
    return {"data": dict(row)}


@router.delete("/workspaces/{workspace_id}", status_code=204)
async def delete_workspace(
    workspace_id: UUID, request: Request, claims: AuthenticatedClaims, db: AsyncSession = Db
):
    actor = uid(claims)
    await require_permission(db, actor, workspace_id, "workspace.delete")
    project_count = (
        await db.execute(
            text("select count(*) from public.video_projects where workspace_id=:workspace"),
            {"workspace": workspace_id},
        )
    ).scalar_one()
    if project_count:
        raise HTTPException(
            status_code=409,
            detail=(
                "Workspace contains project records; deletion is blocked "
                "to preserve project history."
            ),
        )
    await audit(db, actor, workspace_id, "workspace.deleted", "workspace", workspace_id, request)
    await db.execute(
        text("delete from public.workspaces where id=:workspace"), {"workspace": workspace_id}
    )
    await db.commit()
    return None


@router.get("/workspaces/{workspace_id}/permissions")
async def get_workspace_permissions(
    workspace_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = Db
):
    role = await require_permission(db, uid(claims), workspace_id, "workspace.read")
    return {
        "data": {
            "workspace_id": str(workspace_id),
            "role": role,
            "permissions": sorted(ROLE_PERMISSIONS[WorkspaceRole(role)]),
        }
    }


@router.get("/workspaces/{workspace_id}/members")
async def list_members(workspace_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = Db):
    await require_permission(db, uid(claims), workspace_id, "member.read")
    rows = (
        (
            await db.execute(
                text("""
      select m.id,m.workspace_id,m.user_id,m.role,m.status,m.created_at,p.display_name
      from public.workspace_members m join public.profiles p on p.id=m.user_id
      where m.workspace_id=:workspace order by m.created_at
    """),
                {"workspace": workspace_id},
            )
        )
        .mappings()
        .all()
    )
    return {"data": [dict(r) for r in rows]}


@router.get("/workspaces/{workspace_id}/invitations")
async def list_invitations(workspace_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = Db):
    await require_permission(db, uid(claims), workspace_id, "member.manage")
    rows = (
        (
            await db.execute(
                text("""
                    select id,workspace_id,email,role,invited_by,expires_at,created_at,
                           delivery_status,delivery_attempts,sent_at
                    from public.workspace_invitations
                    where workspace_id=:workspace and accepted_at is null
                      and cancelled_at is null and expires_at>now()
                    order by created_at desc
                """),
                {"workspace": workspace_id},
            )
        )
        .mappings()
        .all()
    )
    return {"data": [dict(row) for row in rows]}


async def deliver_invitation(
    *,
    db: AsyncSession,
    invitation_id: UUID,
    recipient: str,
    workspace_name: str,
    role: str,
    raw_token: str,
    digest: str,
    attempt_reserved: bool = False,
) -> dict[str, Any]:
    if not attempt_reserved:
        await db.execute(
            text("""
                update public.workspace_invitations
                set delivery_attempts=delivery_attempts+1,
                    last_delivery_attempt_at=now(),
                    delivery_status='pending'
                where id=:id
            """),
            {"id": invitation_id},
        )
        await db.commit()
    try:
        provider_message_id = await invitation_email.send(
            recipient=recipient,
            workspace_name=workspace_name,
            role=role,
            raw_token=raw_token,
            idempotency_key=f"graphytion-invitation-{invitation_id}-{digest[:16]}",
        )
    except (InvitationEmailConfigurationError, InvitationEmailDeliveryError) as exc:
        await db.execute(
            text("""
                update public.workspace_invitations
                set delivery_status='failed',
                    last_delivery_error=:error
                where id=:id
            """),
            {
                "id": invitation_id,
                "error": "provider_not_configured" if isinstance(
                    exc, InvitationEmailConfigurationError
                ) else "provider_delivery_failed",
            },
        )
        await db.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        await db.execute(
            text("""
                update public.workspace_invitations
                set delivery_status='failed',last_delivery_error='provider_delivery_failed'
                where id=:id
            """),
            {"id": invitation_id},
        )
        await db.commit()
        raise HTTPException(status_code=502, detail="Invitation email delivery failed") from exc

    row = (
        (
            await db.execute(
                text("""
                    update public.workspace_invitations
                    set delivery_status='sent',
                        provider_message_id=:message_id,
                        sent_at=now(),
                        last_delivery_error=null
                    where id=:id
                    returning id,workspace_id,email,role,expires_at,created_at,
                              delivery_status,delivery_attempts,sent_at
                """),
                {"id": invitation_id, "message_id": provider_message_id},
            )
        )
        .mappings()
        .one()
    )
    await db.commit()
    return dict(row)

@router.post(
    "/workspaces/{workspace_id}/members", status_code=201, dependencies=[Depends(auth_rate_limit)]
)
@router.post(
    "/workspaces/{workspace_id}/invitations",
    status_code=201,
    dependencies=[Depends(auth_rate_limit)],
)
async def create_invitation(
    workspace_id: UUID,
    payload: InviteCreate,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = Db,
):
    actor = uid(claims)
    actor_role = await require_permission(db, actor, workspace_id, "member.manage")
    if payload.role == "admin" and actor_role != "owner":
        raise HTTPException(
            status_code=403, detail="Only the workspace owner can invite an administrator"
        )
    try:
        invitation_email.assert_configured()
    except InvitationEmailConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    email = payload.email.strip().lower()
    already_member = (
        await db.execute(
            text("select private.graphytion_workspace_has_active_member_email(:workspace,:email)"),
            {"workspace": workspace_id, "email": email},
        )
    ).scalar_one()
    if already_member:
        raise HTTPException(
            status_code=409, detail="This user is already an active workspace member"
        )
    await db.execute(
        text("""
            update public.workspace_invitations
            set cancelled_at=now()
            where workspace_id=:workspace and lower(email)=:email
              and accepted_at is null and cancelled_at is null and expires_at<=now()
        """),
        {"workspace": workspace_id, "email": email},
    )
    pending = (
        await db.execute(
            text("""
                select exists (
                    select 1 from public.workspace_invitations
                    where workspace_id=:workspace and lower(email)=:email
                      and accepted_at is null and cancelled_at is null and expires_at>now()
                )
            """),
            {"workspace": workspace_id, "email": email},
        )
    ).scalar_one()
    if pending:
        raise HTTPException(
            status_code=409,
            detail="A pending invitation already exists; use resend on the existing invitation",
        )

    raw = secrets.token_urlsafe(36)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    try:
        workspace_name = (
            await db.execute(
                text("select name from public.workspaces where id=:workspace"),
                {"workspace": workspace_id},
            )
        ).scalar_one()
        row = (
            (
                await db.execute(
                    text("""
                        insert into public.workspace_invitations(
                            workspace_id,email,role,token_hash,invited_by,expires_at,
                            delivery_status,delivery_attempts,last_delivery_attempt_at
                        )
                        values (
                            :workspace,:email,:role,:digest,:actor,
                            now()+interval '7 days','pending',1,now()
                        )
                        returning id
                    """),
                    {
                        "workspace": workspace_id,
                        "email": email,
                        "role": payload.role,
                        "digest": digest,
                        "actor": actor,
                    },
                )
            )
            .mappings()
            .one()
        )
        invitation_id = row["id"]
        await audit(
            db, actor, workspace_id, "workspace.invitation.created", "invitation",
            invitation_id, request
        )
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise HTTPException(
            status_code=409, detail="A pending invitation already exists for this email"
        ) from exc

    try:
        result = await deliver_invitation(
            db=db,
            invitation_id=invitation_id,
            recipient=email,
            workspace_name=workspace_name,
            role=payload.role,
            raw_token=raw,
            digest=digest,
            attempt_reserved=True,
        )
    except HTTPException:
        await audit(
            db, actor, workspace_id, "workspace.invitation.email_failed",
            "invitation", invitation_id, request
        )
        await db.commit()
        raise
    await audit(
        db, actor, workspace_id, "workspace.invitation.email_accepted", "invitation",
        invitation_id, request
    )
    await db.commit()
    return {"data": result}


@router.post(
    "/workspaces/{workspace_id}/invitations/{invitation_id}/resend",
    status_code=202,
    dependencies=[Depends(auth_rate_limit)],
)
async def resend_invitation(
    workspace_id: UUID,
    invitation_id: UUID,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = Db,
):
    actor = uid(claims)
    await require_permission(db, actor, workspace_id, "member.manage")
    try:
        invitation_email.assert_configured()
    except InvitationEmailConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    row = (
        (
            await db.execute(
                text("""
                    select i.email,i.role,i.delivery_status,i.expires_at,
                           w.name as workspace_name
                    from public.workspace_invitations i
                    join public.workspaces w on w.id=i.workspace_id
                    where i.id=:invitation and i.workspace_id=:workspace
                      and i.accepted_at is null and i.cancelled_at is null
                    for update of i
                """),
                {"invitation": invitation_id, "workspace": workspace_id},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Pending invitation not found")
    if row["delivery_status"] in ("bounced", "complained"):
        raise HTTPException(
            status_code=409,
            detail=(
                "Provider reported a recipient problem; correct the address "
                "before sending again"
            ),
        )
    if row["delivery_status"] != "failed" and row["expires_at"] > datetime.now(UTC):
        raise HTTPException(
            status_code=409,
            detail=(
                "Invitation is not eligible for resend until delivery fails "
                "or the invitation expires"
            ),
        )
    if row["role"] == "admin":
        actor_role = await require_permission(db, actor, workspace_id, "member.manage")
        if actor_role != "owner":
            raise HTTPException(
                status_code=403, detail="Only the workspace owner can resend administrator invitations"
            )

    raw = secrets.token_urlsafe(36)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    await db.execute(
        text("""
            update public.workspace_invitations
            set token_hash=:digest,expires_at=now()+interval '7 days',
                delivery_status='pending',provider_message_id=null,sent_at=null,
                delivery_attempts=delivery_attempts+1,last_delivery_attempt_at=now(),
                last_delivery_error=null
            where id=:id
        """),
        {"id": invitation_id, "digest": digest},
    )
    await db.commit()
    try:
        result = await deliver_invitation(
            db=db,
            invitation_id=invitation_id,
            recipient=row["email"],
            workspace_name=row["workspace_name"],
            role=row["role"],
            raw_token=raw,
            digest=digest,
            attempt_reserved=True,
        )
    except HTTPException:
        await audit(
            db, actor, workspace_id, "workspace.invitation.email_failed",
            "invitation", invitation_id, request
        )
        await db.commit()
        raise
    await audit(
        db, actor, workspace_id, "workspace.invitation.resent", "invitation",
        invitation_id, request
    )
    await db.commit()
    return {"data": result}


@router.patch(
    "/workspaces/{workspace_id}/members/{member_id}", dependencies=[Depends(auth_rate_limit)]
)
async def update_member_role(
    workspace_id: UUID,
    member_id: UUID,
    payload: RoleUpdate,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = Db,
):
    actor = uid(claims)
    actor_role = await require_permission(db, actor, workspace_id, "member.manage")
    target = (
        (
            await db.execute(
                text("""
        select user_id, role
        from public.workspace_members
        where id=:member and workspace_id=:workspace and status='active'
    """),
                {"member": member_id, "workspace": workspace_id},
            )
        )
        .mappings()
        .first()
    )
    if not target:
        raise HTTPException(status_code=404, detail="Workspace member not found")
    if target["role"] == "owner":
        raise HTTPException(
            status_code=409, detail="Workspace ownership cannot be changed through role management"
        )
    if payload.role == "owner":
        raise HTTPException(status_code=400, detail="Use the ownership transfer workflow")
    if (target["role"] == "admin" or payload.role == "admin") and actor_role != "owner":
        raise HTTPException(
            status_code=403, detail="Only the owner can grant or change administrator access"
        )
    await db.execute(
        text("update public.workspace_members set role=:role where id=:member"),
        {"role": payload.role, "member": member_id},
    )
    await audit(
        db,
        actor,
        workspace_id,
        "workspace.member.role_changed",
        "workspace_member",
        member_id,
        request,
    )
    await db.commit()
    return {"data": {"member_id": str(member_id), "role": payload.role}}


@router.delete(
    "/workspaces/{workspace_id}/members/{member_id}",
    status_code=204,
    dependencies=[Depends(auth_rate_limit)],
)
async def remove_workspace_member(
    workspace_id: UUID,
    member_id: UUID,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = Db,
):
    actor = uid(claims)
    actor_role = await require_permission(db, actor, workspace_id, "member.manage")
    target = (
        (
            await db.execute(
                text("""
        select user_id, role
        from public.workspace_members
        where id=:member and workspace_id=:workspace and status='active'
    """),
                {"member": member_id, "workspace": workspace_id},
            )
        )
        .mappings()
        .first()
    )
    if not target:
        raise HTTPException(status_code=404, detail="Workspace member not found")
    if target["role"] == "owner":
        raise HTTPException(status_code=409, detail="Workspace owner cannot be removed")
    if target["role"] == "admin" and actor_role != "owner":
        raise HTTPException(status_code=403, detail="Only the owner can remove an administrator")
    await db.execute(
        text("update public.workspace_members set status='left' where id=:member"),
        {"member": member_id},
    )
    await audit(
        db, actor, workspace_id, "workspace.member.removed", "workspace_member", member_id, request
    )
    await db.commit()
    return None


@router.delete(
    "/workspaces/{workspace_id}/invitations/{invitation_id}",
    status_code=204,
    dependencies=[Depends(auth_rate_limit)],
)
async def cancel_invitation(
    workspace_id: UUID,
    invitation_id: UUID,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = Db,
):
    actor = uid(claims)
    await require_permission(db, actor, workspace_id, "member.manage")
    result = await db.execute(
        text("""
      update public.workspace_invitations set cancelled_at=now()
      where id=:invitation and workspace_id=:workspace
        and accepted_at is null and cancelled_at is null
    """),
        {"invitation": invitation_id, "workspace": workspace_id},
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="Pending invitation not found")
    await audit(
        db,
        actor,
        workspace_id,
        "workspace.invitation.cancelled",
        "invitation",
        invitation_id,
        request,
    )
    await db.commit()
    return None


@router.post("/invitations/accept", dependencies=[Depends(auth_rate_limit)])
async def accept_invitation(
    payload: InviteAccept, request: Request, claims: AuthenticatedClaims, db: AsyncSession = Db
):
    actor = uid(claims)
    digest = hashlib.sha256(payload.token.encode()).hexdigest()
    try:
        row = (
            (
                await db.execute(
                    text("""
          select i.* from public.workspace_invitations i
          where i.token_hash=:digest
            and private.graphytion_invitation_matches_user(i.email,:actor)
            and i.accepted_at is null
            and i.cancelled_at is null and i.expires_at>now()
          for update of i
        """),
                    {"digest": digest, "actor": actor},
                )
            )
            .mappings()
            .first()
        )
        if not row:
            raise HTTPException(status_code=404, detail="Invitation is invalid or expired")
        membership_result = await db.execute(
            text("""
          insert into public.workspace_members(workspace_id,user_id,role,status)
          values (:workspace,:actor,:role,'active')
          on conflict (workspace_id,user_id) do update
            set role=excluded.role,status='active'
            where public.workspace_members.status <> 'active'
          returning id
        """),
            {"workspace": row["workspace_id"], "actor": actor, "role": row["role"]},
        )
        if membership_result.rowcount == 0:
            raise HTTPException(
                status_code=409, detail="User is already an active workspace member"
            )
        await db.execute(
            text("update public.workspace_invitations set accepted_at=now() where id=:id"),
            {"id": row["id"]},
        )
        await audit(
            db,
            actor,
            row["workspace_id"],
            "workspace.invitation.accepted",
            "invitation",
            row["id"],
            request,
        )
        await db.commit()
        return {
            "data": {
                "workspace_id": str(row["workspace_id"]),
                "role": row["role"],
                "accepted": True,
            }
        }
    except Exception:
        await db.rollback()
        raise


@router.post("/workspaces/{workspace_id}/leave", status_code=204)
async def leave_workspace(
    workspace_id: UUID, request: Request, claims: AuthenticatedClaims, db: AsyncSession = Db
):
    actor = uid(claims)
    role = await require_permission(db, actor, workspace_id, "workspace.read")
    if role == "owner":
        raise HTTPException(status_code=409, detail="Transfer ownership before leaving")
    await db.execute(
        text("""
        update public.workspace_members set status='left'
        where workspace_id=:workspace and user_id=:user
    """),
        {"workspace": workspace_id, "user": actor},
    )
    await audit(db, actor, workspace_id, "workspace.member.left", "workspace_member", None, request)
    await db.commit()
    return None


@router.get("/projects")
@router.get("/workspaces/{workspace_id}/projects")
async def list_projects(
    workspace_id: UUID,
    claims: AuthenticatedClaims,
    db: AsyncSession = Db,
    q: str | None = Query(default=None, max_length=160),
    status_filter: str | None = Query(
        default=None, alias="status", pattern="^(draft|active|archived)$"
    ),
    sort: str = Query(default="updated_at", pattern="^(updated_at|created_at|name)$"),
    direction: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    cursor: str | None = Query(default=None, max_length=128),
):
    if cursor:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            decoded_offset = int(base64.urlsafe_b64decode(padded.encode()).decode())
            if decoded_offset < 0:
                raise ValueError("negative cursor")
            if offset not in (0, decoded_offset):
                raise ValueError("cursor and offset conflict")
            offset = decoded_offset
        except (ValueError, UnicodeDecodeError, binascii.Error) as exc:
            raise HTTPException(
                status_code=400, detail="Invalid project pagination cursor"
            ) from exc
    await require_permission(db, uid(claims), workspace_id, "project.read")
    rows = (
        (
            await db.execute(
                text(f"""
      select * from public.video_projects
      where workspace_id=:workspace and status<>'deleted'
        and (:q is null or name ilike '%'||:q||'%' or coalesce(description,'') ilike '%'||:q||'%')
        and (:status is null or status=:status)
      order by {sort} {direction} limit :limit offset :offset
    """),
                {
                    "workspace": workspace_id,
                    "q": q,
                    "status": status_filter,
                    "limit": limit,
                    "offset": offset,
                },
            )
        )
        .mappings()
        .all()
    )
    total = (
        await db.execute(
            text("""
                select count(*) from public.video_projects
                where workspace_id=:workspace and status<>'deleted'
                  and (
                    :q is null
                    or name ilike '%'||:q||'%'
                    or coalesce(description,'') ilike '%'||:q||'%'
                  )
                  and (:status is null or status=:status)
            """),
            {"workspace": workspace_id, "q": q, "status": status_filter},
        )
    ).scalar_one()
    return {
        "data": [dict(r) for r in rows],
        "page": {
            "limit": limit,
            "offset": offset,
            "total": total,
            "has_more": offset + len(rows) < total,
            "next_cursor": (
                base64.urlsafe_b64encode(str(offset + len(rows)).encode()).decode().rstrip("=")
                if offset + len(rows) < total
                else None
            ),
        },
    }


@router.post("/projects", status_code=201)
@router.post("/workspaces/{workspace_id}/projects", status_code=201)
async def create_project(
    workspace_id: UUID,
    payload: ProjectCreate,
    request: Request,
    claims: AuthenticatedClaims,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    db: AsyncSession = Db,
):
    actor = uid(claims)
    await require_permission(db, actor, workspace_id, "project.create")
    project_name = payload.name.strip()
    if not project_name:
        raise HTTPException(status_code=422, detail="Project name cannot be blank")
    if len(json.dumps(payload.settings, default=str)) > 65536:
        raise HTTPException(status_code=413, detail="Project settings exceed 64 KB")
    try:
        reservation_id, cached = await reserve_idempotency(
            db,
            actor_user_id=actor,
            operation=f"project.create:{workspace_id}",
            key=validate_idempotency_key(idempotency_key),
            payload={"workspace_id": str(workspace_id), **payload.model_dump()},
        )
        if cached is not None:
            await db.rollback()
            return cached
        row = (
            (
                await db.execute(
                    text("""
          insert into public.video_projects(
            workspace_id, created_by, name, description, production_mode,
            default_language, target_duration_ms, aspect_ratio, width, height, fps
          )
          values (
            :workspace, :actor, :name, :description, :mode, :language,
            :duration, :ratio, :width, :height, :fps
          ) returning *
        """),
                    {
                        "workspace": workspace_id,
                        "actor": actor,
                        "name": project_name,
                        "description": payload.description,
                        "mode": payload.production_mode,
                        "language": payload.default_language,
                        "duration": payload.target_duration_ms,
                        "ratio": payload.aspect_ratio,
                        "width": payload.width,
                        "height": payload.height,
                        "fps": payload.fps,
                    },
                )
            )
            .mappings()
            .one()
        )
        await db.execute(
            text("""
            insert into public.project_settings(project_id, settings)
            values (:id, cast(:settings as jsonb))
        """),
            {"id": row["id"], "settings": json.dumps(payload.settings)},
        )
        await audit(db, actor, workspace_id, "project.created", "video_project", row["id"], request)
        response_body = {"data": dict(row)}
        await complete_idempotency(db, reservation_id, response_body)
        await db.commit()
        return response_body
    except Exception:
        await db.rollback()
        raise


@router.get("/projects/{project_id}")
async def get_project(project_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = Db):
    actor = uid(claims)
    workspace_id = (
        await db.execute(
            text("""
                select workspace_id from public.video_projects
                where id=:project and status<>'deleted'
            """),
            {"project": project_id},
        )
    ).scalar_one_or_none()
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await require_permission(db, actor, workspace_id, "project.read")
    row = (
        (
            await db.execute(
                text("""
                    select p.*,s.settings,s.version as settings_version
                    from public.video_projects p
                    left join public.project_settings s on s.project_id=p.id
                    where p.id=:project and p.workspace_id=:workspace
                """),
                {"project": project_id, "workspace": workspace_id},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return {"data": dict(row)}


@router.patch("/projects/{project_id}")
async def update_project(
    project_id: UUID,
    payload: ProjectUpdate,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession = Db,
):
    actor = uid(claims)
    workspace_id = (
        await db.execute(
            text("""
                select workspace_id from public.video_projects
                where id=:project and status<>'deleted'
            """),
            {"project": project_id},
        )
    ).scalar_one_or_none()
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await require_permission(db, actor, workspace_id, "project.update")
    values = payload.model_dump(exclude_unset=True)
    settings = values.pop("settings", None)
    if "name" in values:
        values["name"] = values["name"].strip()
        if not values["name"]:
            raise HTTPException(status_code=422, detail="Project name cannot be blank")
    if settings is not None and len(json.dumps(settings, default=str)) > 65536:
        raise HTTPException(status_code=413, detail="Project settings exceed 64 KB")
    if not values and settings is None:
        raise HTTPException(status_code=400, detail="No project fields supplied")
    try:
        if values:
            assignments = ", ".join(f"{key}=:{key}" for key in values)
            await db.execute(
                text(
                    f"update public.video_projects set {assignments},updated_at=now() where id=:id"
                ),
                {**values, "id": project_id},
            )
        if settings is not None:
            await db.execute(
                text("""
              insert into public.project_settings(project_id, settings, version)
                values (:id, cast(:settings as jsonb), 1)
              on conflict (project_id) do update set
                settings=excluded.settings,
                version=project_settings.version+1,
                updated_at=now()
            """),
                {"id": project_id, "settings": json.dumps(settings)},
            )
        await audit(
            db, actor, workspace_id, "project.updated", "video_project", project_id, request
        )
        result = (
            (
                await db.execute(
                    text("""
                        select p.*,s.settings,s.version as settings_version
                        from public.video_projects p
                        left join public.project_settings s on s.project_id=p.id
                        where p.id=:id
                    """),
                    {"id": project_id},
                )
            )
            .mappings()
            .one()
        )
        await db.commit()
        return {"data": dict(result)}
    except Exception:
        await db.rollback()
        raise


@router.post("/projects/{project_id}/archive")
async def archive_project(
    project_id: UUID, request: Request, claims: AuthenticatedClaims, db: AsyncSession = Db
):
    return await _set_project_status(project_id, "archived", request, claims, db)


@router.post("/projects/{project_id}/restore")
async def restore_project(
    project_id: UUID, request: Request, claims: AuthenticatedClaims, db: AsyncSession = Db
):
    return await _set_project_status(project_id, "draft", request, claims, db)


async def _set_project_status(
    project_id: UUID,
    new_status: str,
    request: Request,
    claims: AuthenticatedClaims,
    db: AsyncSession,
):
    actor = uid(claims)
    row = (
        (
            await db.execute(
                text("""
                    select workspace_id,status from public.video_projects
                    where id=:project and status<>'deleted'
                    for update
                """),
                {"project": project_id},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    await require_permission(db, actor, row["workspace_id"], "project.archive")
    if new_status == "archived" and row["status"] not in ("draft", "active"):
        raise HTTPException(status_code=409, detail="Only draft or active projects can be archived")
    if new_status == "draft" and row["status"] != "archived":
        raise HTTPException(status_code=409, detail="Only archived projects can be restored")
    result = (
        (
            await db.execute(
                text("""
                    update public.video_projects set status=:status, updated_at=now()
                    where id=:id and status=:current_status returning *
                """),
                {"status": new_status, "id": project_id, "current_status": row["status"]},
            )
        )
        .mappings()
        .one()
    )
    await audit(
        db,
        actor,
        row["workspace_id"],
        f"project.{new_status}",
        "video_project",
        project_id,
        request,
    )
    await db.commit()
    return {"data": dict(result)}


@router.delete("/projects/{project_id}", status_code=204)
async def delete_project(
    project_id: UUID, request: Request, claims: AuthenticatedClaims, db: AsyncSession = Db
):
    actor = uid(claims)
    workspace_id = (
        await db.execute(
            text("""
                select workspace_id from public.video_projects
                where id=:project and status<>'deleted'
            """),
            {"project": project_id},
        )
    ).scalar_one_or_none()
    if workspace_id is None:
        raise HTTPException(status_code=404, detail="Project not found")
    await require_permission(db, actor, workspace_id, "project.delete")
    await db.execute(
        text("""
            update public.video_projects set status='deleted', updated_at=now()
            where id=:id
        """),
        {"id": project_id},
    )
    await audit(db, actor, workspace_id, "project.deleted", "video_project", project_id, request)
    await db.commit()
    return None
