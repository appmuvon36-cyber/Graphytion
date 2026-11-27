from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims, DbSession
from app.core.database import set_rls_subject

router = APIRouter()
HANDLERS = {
    "creative.generate_brief": "brief",
    "creative.write_script": "script",
    "creative.create_storyboard": "storyboard",
    "creative.regenerate_scene": "scene",
}


def _actor(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(401, "Invalid authenticated subject") from exc


async def _admin(db: AsyncSession, actor: UUID) -> None:
    await set_rls_subject(db, str(actor))
    if not await db.scalar(text("select private.graphytion_is_platform_admin()")):
        raise HTTPException(403, "Platform administrator access required")


async def _audit(db: AsyncSession, request: Request, actor: UUID, workspace: UUID | None,
                 tool_key: str | None, action: str, resource_id: str | None,
                 metadata: dict[str, Any] | None = None) -> None:
    await db.execute(text("""
        insert into public.agent_tool_audit_events(
          workspace_id,actor_user_id,tool_key,action,resource_id,request_id,metadata
        ) values (:workspace,:actor,:tool,:action,:resource,:request,cast(:metadata as jsonb))
    """), {"workspace": workspace, "actor": actor, "tool": tool_key, "action": action,
           "resource": resource_id, "request": getattr(request.state, "request_id", None),
           "metadata": json.dumps(metadata or {})})


class ToolRegistration(BaseModel):
    workspace_id: UUID | None = None
    tool_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{2,127}$")
    agent_key: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,95}$")
    stage: Literal["brief", "script", "storyboard", "scene"]
    handler_key: Literal[
        "creative.generate_brief", "creative.write_script",
        "creative.create_storyboard", "creative.regenerate_scene",
    ]
    description: str = Field(min_length=1, max_length=500)
    permission_key: str = Field(default="project.update", min_length=1, max_length=100)
    input_schema: dict[str, Any]
    configuration: dict[str, Any] = Field(default_factory=dict)
    is_active: bool = True


class ToolUpdate(BaseModel):
    description: str | None = Field(default=None, min_length=1, max_length=500)
    permission_key: str | None = Field(default=None, min_length=1, max_length=100)
    input_schema: dict[str, Any] | None = None
    configuration: dict[str, Any] | None = None
    is_active: bool | None = None


class PermissionGrant(BaseModel):
    workspace_id: UUID
    principal_type: Literal["user", "workspace", "agent", "tool", "resource"]
    principal_id: str = Field(min_length=1, max_length=180)
    tool_key: str | None = Field(default=None, max_length=128)
    permission_key: str = Field(default="*", min_length=1, max_length=100)
    effect: Literal["allow", "deny"]
    expires_at: datetime | None = None


class PermissionUpdate(BaseModel):
    effect: Literal["allow", "deny"] | None = None
    permission_key: str | None = Field(default=None, min_length=1, max_length=100)
    expires_at: datetime | None = None


@router.get("/agent-tools")
async def list_agent_tools(claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = _actor(claims)
    await _admin(db, actor)
    rows = (await db.execute(text("""
        select id,workspace_id,tool_key,agent_key,stage,handler_key,description,
               permission_key,input_schema,configuration,is_active,version,created_at,updated_at
        from public.agent_tool_registry order by workspace_id nulls first,stage,tool_key
    """))).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.post("/agent-tools", status_code=201)
async def register_agent_tool(payload: ToolRegistration, request: Request,
                              claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = _actor(claims)
    await _admin(db, actor)
    if HANDLERS[payload.handler_key] != payload.stage:
        raise HTTPException(422, "Handler key does not implement the selected stage")
    if payload.input_schema.get("type") != "object" or payload.input_schema.get("additionalProperties", False) is not False:
        raise HTTPException(422, "Tool input schema must be a strict JSON object schema")
    if len(json.dumps(payload.input_schema)) > 24000 or len(json.dumps(payload.configuration)) > 12000:
        raise HTTPException(413, "Tool schema or configuration exceeds the allowed size")
    row = (await db.execute(text("""
        insert into public.agent_tool_registry(
          workspace_id,tool_key,agent_key,stage,handler_key,description,permission_key,
          input_schema,configuration,is_active,created_by,updated_by
        ) values (:workspace,:key,:agent,:stage,:handler,:description,:permission,
          cast(:schema as jsonb),cast(:configuration as jsonb),:active,:actor,:actor)
        returning id,workspace_id,tool_key,agent_key,stage,handler_key,version,is_active
    """), {"workspace": payload.workspace_id, "key": payload.tool_key,
           "agent": payload.agent_key, "stage": payload.stage,
           "handler": payload.handler_key, "description": payload.description,
           "permission": payload.permission_key,
           "schema": json.dumps(payload.input_schema),
           "configuration": json.dumps(payload.configuration),
           "active": payload.is_active, "actor": actor})).mappings().one()
    await _audit(db, request, actor, payload.workspace_id, payload.tool_key,
                 "tool.registered", str(row["id"]), {"stage": payload.stage})
    await db.commit()
    return {"data": dict(row)}


@router.patch("/agent-tools/{tool_id}")
async def update_agent_tool(tool_id: UUID, payload: ToolUpdate, request: Request,
                            claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = _actor(claims)
    await _admin(db, actor)
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(422, "At least one tool field must be updated")
    if "input_schema" in values:
        schema = values["input_schema"]
        if schema.get("type") != "object" or schema.get("additionalProperties", False) is not False:
            raise HTTPException(422, "Tool input schema must be a strict JSON object schema")
        if len(json.dumps(schema)) > 24000:
            raise HTTPException(413, "Tool schema exceeds the allowed size")
    current = (await db.execute(text("""
        select workspace_id,tool_key,stage,handler_key from public.agent_tool_registry
        where id=:id for update
    """), {"id": tool_id})).mappings().first()
    if current is None:
        raise HTTPException(404, "Agent tool not found")
    row = (await db.execute(text("""
        update public.agent_tool_registry set
          description=coalesce(:description,description),
          permission_key=coalesce(:permission,permission_key),
          input_schema=coalesce(cast(:schema as jsonb),input_schema),
          configuration=coalesce(cast(:configuration as jsonb),configuration),
          is_active=coalesce(:active,is_active),version=version+1,
          updated_by=:actor,updated_at=now()
        where id=:id returning id,tool_key,stage,is_active,version
    """), {"id": tool_id, "description": values.get("description"),
           "permission": values.get("permission_key"),
           "schema": json.dumps(values["input_schema"]) if "input_schema" in values else None,
           "configuration": json.dumps(values["configuration"]) if "configuration" in values else None,
           "active": values.get("is_active"), "actor": actor})).mappings().one()
    await _audit(db, request, actor, current["workspace_id"], current["tool_key"],
                 "tool.updated", str(tool_id), {"fields": sorted(values), "active": row["is_active"]})
    await db.commit()
    return {"data": dict(row)}



@router.get("/agent-tool-permissions")
async def list_agent_tool_permissions(
    claims: AuthenticatedClaims, workspace_id: UUID | None = Query(default=None),
    include_revoked: bool = Query(default=False), db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _admin(db, actor)
    rows = (await db.execute(text("""
        select id,workspace_id,principal_type,principal_id,tool_key,permission_key,
               effect,valid_from,expires_at,revoked_at,created_by,updated_by,created_at,updated_at
        from public.agent_tool_permissions
        where (:workspace is null or workspace_id=:workspace)
          and (:include_revoked or revoked_at is null)
        order by created_at desc limit 1000
    """), {"workspace": workspace_id, "include_revoked": include_revoked})).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.get("/agent-tool-audit")
async def list_agent_tool_audit(
    claims: AuthenticatedClaims, workspace_id: UUID | None = Query(default=None),
    limit: int = Query(default=200, ge=1, le=500), db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _admin(db, actor)
    rows = (await db.execute(text("""
        select id,workspace_id,actor_user_id,tool_key,action,resource_id,request_id,metadata,created_at
        from public.agent_tool_audit_events
        where (:workspace is null or workspace_id=:workspace)
        order by created_at desc limit :limit
    """), {"workspace": workspace_id, "limit": limit})).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.post("/agent-tool-permissions", status_code=201)
async def grant_agent_tool_permission(payload: PermissionGrant, request: Request,
                                      claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = _actor(claims)
    await _admin(db, actor)
    if payload.principal_type == "tool" and not payload.tool_key:
        raise HTTPException(422, "Tool-scoped principal requires tool_key")
    row = (await db.execute(text("""
        insert into public.agent_tool_permissions(
          workspace_id,principal_type,principal_id,tool_key,permission_key,effect,expires_at,created_by
        ) values (:workspace,:type,:principal,:tool,:permission,:effect,:expires,:actor)
        returning id,workspace_id,principal_type,principal_id,tool_key,permission_key,effect,expires_at
    """), {"workspace": payload.workspace_id, "type": payload.principal_type,
           "principal": payload.principal_id, "tool": payload.tool_key,
           "permission": payload.permission_key, "effect": payload.effect,
           "expires": payload.expires_at, "actor": actor})).mappings().one()
    await _audit(db, request, actor, payload.workspace_id, payload.tool_key,
                 "permission.granted", str(row["id"]), {"principal_type": payload.principal_type,
                 "principal_id": payload.principal_id, "effect": payload.effect})
    await db.commit()
    return {"data": dict(row)}


@router.patch("/agent-tool-permissions/{permission_id}")
async def update_agent_tool_permission(permission_id: UUID, payload: PermissionUpdate,
                                       request: Request, claims: AuthenticatedClaims,
                                       db: AsyncSession = DbSession):
    actor = _actor(claims)
    await _admin(db, actor)
    values = payload.model_dump(exclude_unset=True)
    if not values:
        raise HTTPException(422, "At least one permission field must be updated")
    row = (await db.execute(text("""
        update public.agent_tool_permissions set
          effect=coalesce(:effect,effect),permission_key=coalesce(:permission,permission_key),
          expires_at=case when :expiry_set then :expires else expires_at end,
          updated_by=:actor,updated_at=now()
        where id=:id and revoked_at is null
        returning id,workspace_id,tool_key,effect,permission_key,expires_at
    """), {"id": permission_id, "effect": values.get("effect"),
           "permission": values.get("permission_key"), "expiry_set": "expires_at" in values,
           "expires": values.get("expires_at"), "actor": actor})).mappings().first()
    if row is None:
        raise HTTPException(404, "Active tool permission not found")
    await _audit(db, request, actor, row["workspace_id"], row["tool_key"],
                 "permission.updated", str(permission_id), values)
    await db.commit()
    return {"data": dict(row)}


@router.delete("/agent-tool-permissions/{permission_id}")
async def revoke_agent_tool_permission(permission_id: UUID, request: Request,
                                       claims: AuthenticatedClaims, db: AsyncSession = DbSession):
    actor = _actor(claims)
    await _admin(db, actor)
    row = (await db.execute(text("""
        update public.agent_tool_permissions set revoked_at=now(),updated_by=:actor,updated_at=now()
        where id=:id and revoked_at is null
        returning id,workspace_id,tool_key,principal_type,principal_id
    """), {"id": permission_id, "actor": actor})).mappings().first()
    if row is None:
        raise HTTPException(404, "Active tool permission not found")
    await _audit(db, request, actor, row["workspace_id"], row["tool_key"],
                 "permission.revoked", str(permission_id), {
                     "principal_type": row["principal_type"], "principal_id": row["principal_id"]})
    await db.commit()
    return {"data": {"id": str(permission_id), "revoked": True}}
