from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import get_db_session

router = APIRouter()
Db = Depends(get_db_session)


def verify_resend_signature(raw_body: bytes, request: Request) -> None:
    secret = settings.resend_webhook_secret_value
    message_id = request.headers.get("svix-id")
    timestamp = request.headers.get("svix-timestamp")
    signatures = request.headers.get("svix-signature", "")
    if not secret or not message_id or not timestamp or not signatures:
        raise HTTPException(status_code=401, detail="Invalid webhook signature")
    try:
        issued_at = int(timestamp)
        key = base64.b64decode(secret.removeprefix("whsec_"), validate=True)
    except (ValueError, TypeError):
        raise HTTPException(status_code=401, detail="Invalid webhook signature") from None
    if abs(time.time() - issued_at) > 300:
        raise HTTPException(status_code=401, detail="Webhook timestamp expired")
    signed = f"{message_id}.{timestamp}.".encode() + raw_body
    expected = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    valid = False
    for signature in signatures.split():
        version, separator, value = signature.partition(",")
        if separator and version == "v1" and hmac.compare_digest(expected, value):
            valid = True
            break
    if not valid:
        raise HTTPException(status_code=401, detail="Invalid webhook signature")


@router.post("/resend", status_code=202, summary="Resend delivery status webhook")
async def resend_webhook(request: Request, db: AsyncSession = Db) -> dict[str, Any]:
    raw_body = await request.body()
    verify_resend_signature(raw_body, request)
    try:
        payload = json.loads(raw_body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(status_code=400, detail="Invalid webhook payload") from None

    event_type = payload.get("type")
    data = payload.get("data") or {}
    message_id = data.get("email_id") or data.get("id")
    statuses = {
        "email.sent": ("sent", None),
        "email.delivered": ("delivered", None),
        "email.delivery_delayed": ("delivery_delayed", None),
        "email.bounced": ("bounced", "provider_bounced"),
        "email.complained": ("complained", "provider_complaint"),
        "email.failed": ("failed", "provider_failed"),
    }
    transition = statuses.get(event_type)
    if not transition or not isinstance(message_id, str):
        return {"received": True, "processed": False}

    await db.execute(text("select set_config('app.graphytion.internal','resend_webhook',true)"))
    row = (
        (
            await db.execute(
                text("""
                    select id,workspace_id,invited_by,delivery_status
                    from public.workspace_invitations
                    where provider_message_id=:message_id
                    for update
                """),
                {"message_id": message_id},
            )
        )
        .mappings()
        .first()
    )
    if not row:
        await db.rollback()
        return {"received": True, "processed": False}

    next_status, error_code = transition
    terminal = {"delivered", "bounced", "complained", "failed"}
    current_status = row["delivery_status"]
    can_advance = (
        current_status not in terminal
        and current_status != next_status
        and not (next_status == "sent" and current_status != "pending")
        and not (
            next_status == "delivery_delayed"
            and current_status not in {"pending", "sent"}
        )
    )
    if can_advance:
        await db.execute(
            text("""
                update public.workspace_invitations
                set delivery_status=:status,last_delivery_error=:error
                where id=:id
            """),
            {"status": next_status, "error": error_code, "id": row["id"]},
        )
        await db.execute(
            text("""
                insert into public.audit_logs(
                    actor_user_id,workspace_id,action,resource_type,resource_id,metadata,request_id
                )
                values (
                    null,:workspace,:action,'invitation',:invitation,
                    cast(:metadata as jsonb),:request_id
                )
            """),
            {
                "workspace": row["workspace_id"],
                "action": f"workspace.invitation.email_{next_status}",
                "invitation": row["id"],
                "metadata": json.dumps({"provider": "resend", "provider_event": event_type}),
                "request_id": getattr(request.state, "request_id", None),
            },
        )
        await db.commit()
    else:
        await db.rollback()
    return {"received": True, "processed": True}
