from __future__ import annotations

import json
from typing import Any, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import AuthenticatedClaims, DbSession
from app.services.memory_engine import assemble_agent_context, append_message, expire_memories
from app.services.workspace_authorization import WorkspacePermissionResolver

router = APIRouter()
permissions = WorkspacePermissionResolver()


def _actor(claims: dict[str, Any]) -> UUID:
    try:
        return UUID(str(claims["sub"]))
    except (KeyError, ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid authenticated subject") from exc


async def _workspace(db: AsyncSession, workspace_id: UUID, actor: UUID, permission: str) -> None:
    await permissions.require_permission(
        session=db, user_id=str(actor), workspace_id=str(workspace_id), permission=permission
    )


class ConversationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(default="New conversation", min_length=1, max_length=180)
    project_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MessageCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    content: str = Field(min_length=1, max_length=100000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: Literal["personal", "project"] = "personal"
    memory_type: Literal["preference", "context", "fact", "decision", "episodic", "procedural"]
    project_id: UUID | None = None
    title: str = Field(min_length=1, max_length=180)
    content: str = Field(min_length=1, max_length=20000)
    source_type: Literal["conversation", "project", "user_input", "agent_output", "import"]
    source_id: str | None = Field(default=None, max_length=180)
    provenance: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=30)
    importance: float = Field(default=0.5, ge=0, le=1)
    confidence: float = Field(default=1, ge=0, le=1)
    expires_at: str | None = None


@router.post("/workspaces/{workspace_id}/conversations", status_code=201)
async def create_conversation(
    workspace_id: UUID, payload: ConversationCreate, claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _workspace(db, workspace_id, actor, "workspace.read")
    if payload.project_id:
        valid = await db.scalar(text("""
            select exists(select 1 from public.video_projects
            where id=:project and workspace_id=:workspace and status<>'deleted')
        """), {"project": payload.project_id, "workspace": workspace_id})
        if not valid:
            raise HTTPException(404, detail="Project not found in workspace")
    row = (await db.execute(text("""
        insert into public.conversation_threads(workspace_id,project_id,owner_user_id,title,metadata)
        values(:workspace,:project,:actor,:title,cast(:metadata as jsonb))
        returning id,workspace_id,project_id,title,status,metadata,created_at,updated_at
    """), {
        "workspace": workspace_id, "project": payload.project_id, "actor": actor,
        "title": payload.title.strip(), "metadata": json.dumps(payload.metadata),
    })).mappings().one()
    await db.commit()
    return {"data": dict(row)}


@router.get("/workspaces/{workspace_id}/conversations")
async def list_conversations(
    workspace_id: UUID, claims: AuthenticatedClaims,
    limit: int = Query(default=30, ge=1, le=100), db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _workspace(db, workspace_id, actor, "workspace.read")
    rows = (await db.execute(text("""
        select id,project_id,title,status,last_message_at,created_at,updated_at
        from public.conversation_threads where workspace_id=:workspace and owner_user_id=:actor
        order by coalesce(last_message_at,created_at) desc limit :limit
    """), {"workspace": workspace_id, "actor": actor, "limit": limit})).mappings().all()
    return {"data": [dict(row) for row in rows]}


@router.get("/conversations/{conversation_id}/messages")
async def list_messages(
    conversation_id: UUID, claims: AuthenticatedClaims,
    limit: int = Query(default=50, ge=1, le=200), db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    rows = (await db.execute(text("""
        select m.id,m.sequence_no,m.role,m.content,m.metadata,m.provenance,m.created_at
        from public.conversation_messages m join public.conversation_threads t on t.id=m.thread_id
        where m.thread_id=:thread and t.owner_user_id=:actor and t.status='active'
        order by m.sequence_no desc limit :limit
    """), {"thread": conversation_id, "actor": actor, "limit": limit})).mappings().all()
    if not rows:
        exists = await db.scalar(text("""
            select exists(select 1 from public.conversation_threads
            where id=:thread and owner_user_id=:actor)
        """), {"thread": conversation_id, "actor": actor})
        if not exists:
            raise HTTPException(404, detail="Conversation not found")
    return {"data": [dict(row) for row in reversed(rows)]}


@router.post("/conversations/{conversation_id}/messages", status_code=201)
async def add_user_message(
    conversation_id: UUID, payload: MessageCreate, claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    try:
        row = await append_message(
            db, thread_id=conversation_id, actor_id=actor, role="user",
            content=payload.content, metadata=payload.metadata,
        )
    except LookupError as exc:
        raise HTTPException(404, detail="Conversation not found") from exc
    await db.commit()
    return {"data": row}


@router.post("/workspaces/{workspace_id}/memories", status_code=201)
async def create_memory(
    workspace_id: UUID, payload: MemoryCreate, claims: AuthenticatedClaims,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _workspace(db, workspace_id, actor, "workspace.read")
    if payload.scope == "project":
        if payload.project_id is None:
            raise HTTPException(422, detail="Project-scoped memory requires project_id")
        valid = await db.scalar(text("""
            select exists(select 1 from public.video_projects
            where id=:project and workspace_id=:workspace and status<>'deleted')
        """), {"project": payload.project_id, "workspace": workspace_id})
        if not valid:
            raise HTTPException(404, detail="Project not found in workspace")
    elif payload.project_id is not None:
        raise HTTPException(422, detail="Personal memory cannot be attached to a project")
    row = (await db.execute(text("""
        insert into public.memory_items(
          workspace_id,project_id,owner_user_id,scope,memory_type,title,content,
          source_type,source_id,provenance,tags,importance,confidence,retention_policy,expires_at
        ) values (
          :workspace,:project,:actor,:scope,:type,:title,:content,:source_type,:source_id,
          cast(:provenance as jsonb),:tags,:importance,:confidence,
          case when cast(:expires as timestamptz) is null then 'until_deleted' else 'expires' end,
          cast(:expires as timestamptz)
        )
        returning id,workspace_id,project_id,scope,memory_type,title,content,source_type,
          source_id,provenance,tags,importance,confidence,expires_at,created_at
    """), {
        "workspace": workspace_id, "project": payload.project_id, "actor": actor,
        "scope": payload.scope, "type": payload.memory_type, "title": payload.title.strip(),
        "content": payload.content.strip(), "source_type": payload.source_type,
        "source_id": payload.source_id, "provenance": json.dumps(payload.provenance),
        "tags": payload.tags, "importance": payload.importance, "confidence": payload.confidence,
        "expires": payload.expires_at,
    })).mappings().one()
    await db.commit()
    return {"data": dict(row)}


@router.get("/workspaces/{workspace_id}/memories")
async def search_memories(
    workspace_id: UUID, claims: AuthenticatedClaims,
    query: str = Query(default="", max_length=500), project_id: UUID | None = None,
    limit: int = Query(default=20, ge=1, le=100), db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    await _workspace(db, workspace_id, actor, "workspace.read")
    await expire_memories(db, workspace_id=workspace_id, actor_id=actor)
    rows = (await db.execute(text("""
        select id,project_id,scope,memory_type,title,content,source_type,source_id,
          provenance,tags,importance,confidence,expires_at,last_accessed_at,created_at,updated_at
        from public.memory_items
        where workspace_id=:workspace and deleted_at is null
          and (expires_at is null or expires_at>now())
          and ((scope='personal' and owner_user_id=:actor)
            or (scope='project' and :project is not null and project_id=:project))
          and (nullif(btrim(:query),'') is null
            or search_document @@ websearch_to_tsquery('simple',:query))
        order by case when nullif(btrim(:query),'') is not null
          then ts_rank_cd(search_document,websearch_to_tsquery('simple',:query)) else 0 end desc,
          importance desc,updated_at desc limit :limit
    """), {
        "workspace": workspace_id, "actor": actor, "project": project_id,
        "query": query, "limit": limit,
    })).mappings().all()
    await db.commit()
    return {"data": [dict(row) for row in rows]}


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(
    memory_id: UUID, claims: AuthenticatedClaims, db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    result = await db.execute(text("""
        update public.memory_items set deleted_at=now(),updated_at=now()
        where id=:id and owner_user_id=:actor and deleted_at is null returning id
    """), {"id": memory_id, "actor": actor})
    if result.scalar_one_or_none() is None:
        raise HTTPException(404, detail="Memory not found")
    await db.commit()
    return None


@router.get("/projects/{project_id}/memory-context")
async def get_project_memory_context(
    project_id: UUID, claims: AuthenticatedClaims,
    query: str = Query(default="", max_length=500), conversation_id: UUID | None = None,
    db: AsyncSession = DbSession,
):
    actor = _actor(claims)
    project = (await db.execute(text("""
        select workspace_id from public.video_projects
        where id=:project and status<>'deleted'
    """), {"project": project_id})).mappings().first()
    if project is None:
        raise HTTPException(404, detail="Project not found")
    workspace_id = project["workspace_id"]
    await _workspace(db, workspace_id, actor, "project.read")
    if conversation_id is not None:
        owned = await db.scalar(text("""
            select exists(select 1 from public.conversation_threads
            where id=:thread and project_id=:project and owner_user_id=:actor)
        """), {"thread": conversation_id, "project": project_id, "actor": actor})
        if not owned:
            raise HTTPException(404, detail="Conversation not found in project")
    context = await assemble_agent_context(
        db, actor_id=actor, workspace_id=workspace_id, project_id=project_id,
        query=query, conversation_id=conversation_id,
    )
    await db.commit()
    return {"data": context}
