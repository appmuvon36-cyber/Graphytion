from __future__ import annotations

import json
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def append_message(
    db: AsyncSession, *, thread_id: UUID, actor_id: UUID, role: str,
    content: str, metadata: dict[str, Any] | None = None,
    provenance: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if role not in {"system", "user", "assistant", "tool"}:
        raise ValueError("Unsupported conversation message role")
    thread = (await db.execute(text("""
        select id,workspace_id,owner_user_id from public.conversation_threads
        where id=:thread and owner_user_id=:actor and status='active' for update
    """), {"thread": thread_id, "actor": actor_id})).mappings().first()
    if thread is None:
        raise LookupError("Conversation not found")
    sequence = await db.scalar(text("""
        select coalesce(max(sequence_no),0)+1
        from public.conversation_messages where thread_id=:thread
    """), {"thread": thread_id})
    row = (await db.execute(text("""
        insert into public.conversation_messages(
          thread_id,workspace_id,owner_user_id,sequence_no,role,content,metadata,provenance
        ) values (:thread,:workspace,:actor,:sequence,:role,:content,
          cast(:metadata as jsonb),cast(:provenance as jsonb))
        returning id,sequence_no,role,content,metadata,provenance,created_at
    """), {
        "thread": thread_id, "workspace": thread["workspace_id"], "actor": actor_id,
        "sequence": sequence, "role": role, "content": content,
        "metadata": json.dumps(metadata or {}),
        "provenance": json.dumps(provenance or []),
    })).mappings().one()
    await db.execute(text("""
        update public.conversation_threads set last_message_at=now(),updated_at=now()
        where id=:thread
    """), {"thread": thread_id})
    return dict(row)


async def assemble_agent_context(
    db: AsyncSession, *, actor_id: UUID, workspace_id: UUID,
    project_id: UUID | None, query: str, conversation_id: UUID | None = None,
    memory_limit: int = 12, message_limit: int = 12,
) -> dict[str, Any]:
    """Build bounded, tenant-scoped context; expired and deleted memories are excluded."""
    memories = (await db.execute(text("""
        select id,scope,memory_type,title,content,provenance,importance,confidence,
          project_id,updated_at
        from public.memory_items
        where workspace_id=:workspace and deleted_at is null
          and (expires_at is null or expires_at>now())
          and ((scope='personal' and owner_user_id=:actor)
            or (scope='project' and project_id=:project))
          and (nullif(btrim(:query),'') is null
            or search_document @@ websearch_to_tsquery('simple',:query))
        order by
          case when nullif(btrim(:query),'') is not null
            then ts_rank_cd(search_document,websearch_to_tsquery('simple',:query))
            else 0 end desc,
          importance desc,updated_at desc
        limit :limit
    """), {
        "workspace": workspace_id, "actor": actor_id, "project": project_id,
        "query": query[:500], "limit": max(1,min(memory_limit,30)),
    })).mappings().all()
    messages: list[dict[str, Any]] = []
    if conversation_id is not None:
        rows = (await db.execute(text("""
            select role,content,metadata,created_at from public.conversation_messages
            where thread_id=:thread and owner_user_id=:actor
            order by sequence_no desc limit :limit
        """), {
            "thread": conversation_id, "actor": actor_id,
            "limit": max(1,min(message_limit,30)),
        })).mappings().all()
        messages = [dict(row) for row in reversed(rows)]
    ids = [row["id"] for row in memories]
    if ids:
        await db.execute(text("""
            update public.memory_items set last_accessed_at=now(),access_count=access_count+1
            where id=any(cast(:ids as uuid[]))
        """), {"ids": ids})
    return {
        "memory": [dict(row) for row in memories],
        "conversation": messages,
        "provenance": [{"memory_id": str(row["id"]), "source": row["provenance"]} for row in memories],
    }


async def expire_memories(db: AsyncSession, *, workspace_id: UUID, actor_id: UUID) -> int:
    result = await db.execute(text("""
        update public.memory_items set deleted_at=now(),updated_at=now()
        where workspace_id=:workspace and owner_user_id=:actor
          and deleted_at is null and expires_at is not null and expires_at<=now()
    """), {"workspace": workspace_id, "actor": actor_id})
    return int(result.rowcount or 0)
