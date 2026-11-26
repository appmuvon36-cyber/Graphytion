from __future__ import annotations

import hashlib
import json
from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


def validate_idempotency_key(value: str | None) -> str | None:
    if value is None:
        return None
    if len(value) < 16 or len(value) > 128:
        raise HTTPException(
            status_code=400, detail="Idempotency-Key must contain 16-128 characters"
        )
    return value


def request_fingerprint(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


async def reserve_idempotency(
    session: AsyncSession,
    *,
    actor_user_id: UUID,
    operation: str,
    key: str | None,
    payload: dict[str, Any],
) -> tuple[UUID | None, dict[str, Any] | None]:
    if key is None:
        return None, None
    fingerprint = request_fingerprint(payload)
    await session.execute(
        text("""
            delete from public.api_idempotency_keys
            where actor_user_id=:actor and operation=:operation
              and idempotency_key=:key and expires_at<=now()
        """),
        {"actor": actor_user_id, "operation": operation, "key": key},
    )
    reservation_id = (
        await session.execute(
            text("""
                insert into public.api_idempotency_keys(
                    actor_user_id, operation, idempotency_key, request_hash
                )
                values (:actor,:operation,:key,:fingerprint)
                on conflict (actor_user_id,operation,idempotency_key) do nothing
                returning id
            """),
            {
                "actor": actor_user_id,
                "operation": operation,
                "key": key,
                "fingerprint": fingerprint,
            },
        )
    ).scalar_one_or_none()
    if reservation_id is not None:
        return reservation_id, None
    existing = (
        (
            await session.execute(
                text("""
                    select id,request_hash,response_body
                    from public.api_idempotency_keys
                    where actor_user_id=:actor and operation=:operation
                      and idempotency_key=:key and expires_at>now()
                    for update
                """),
                {"actor": actor_user_id, "operation": operation, "key": key},
            )
        )
        .mappings()
        .first()
    )
    if existing is None:
        raise HTTPException(status_code=409, detail="Idempotency key is currently unavailable")
    if existing["request_hash"] != fingerprint:
        raise HTTPException(
            status_code=409, detail="Idempotency key was already used with a different request"
        )
    if existing["response_body"] is None:
        raise HTTPException(status_code=409, detail="An identical request is still processing")
    return None, dict(existing["response_body"])


async def complete_idempotency(
    session: AsyncSession, reservation_id: UUID | None, response_body: dict[str, Any]
) -> None:
    if reservation_id is None:
        return
    await session.execute(
        text("""
            update public.api_idempotency_keys
            set response_body=cast(:body as jsonb), completed_at=now()
            where id=:id
        """),
        {"id": reservation_id, "body": json.dumps(response_body, default=str)},
    )
