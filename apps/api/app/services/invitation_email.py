from __future__ import annotations

import asyncio
from html import escape
from typing import Any
from urllib.parse import quote

import httpx

from app.core.config import settings


class InvitationEmailConfigurationError(RuntimeError):
    pass


class InvitationEmailDeliveryError(RuntimeError):
    pass


class ResendInvitationEmail:
    """Server-only invitation email adapter using Resend's idempotency support."""

    endpoint = "https://api.resend.com/emails"

    def assert_configured(self) -> None:
        if not (
            settings.resend_api_key_value
            and settings.invitation_from_email
            and settings.app_public_url.startswith("https://")
        ):
            raise InvitationEmailConfigurationError(
                "Invitation email requires RESEND_API_KEY, INVITATION_FROM_EMAIL "
                "and HTTPS APP_PUBLIC_URL"
            )

    async def send(
        self,
        *,
        recipient: str,
        workspace_name: str,
        role: str,
        raw_token: str,
        idempotency_key: str,
    ) -> str:
        self.assert_configured()
        safe_workspace = escape(workspace_name)
        safe_role = escape(role)
        invitation_url = (
            f"{settings.app_public_url.rstrip('/')}/#invite={quote(raw_token, safe='')}"
        )
        html = (
            "<div style='font-family:Arial,sans-serif;max-width:560px;margin:auto;color:#172b4d'>"
            "<h2>Undangan workspace Graphytion</h2>"
            f"<p>Anda diundang bergabung ke <strong>{safe_workspace}</strong> "
            f"dengan peran <strong>{safe_role}</strong>.</p>"
            f"<p><a href='{escape(invitation_url, quote=True)}'>Terima undangan</a></p>"
            "<p>Tautan berlaku selama 7 hari, hanya dapat digunakan satu kali, "
            "dan tidak boleh dibagikan kepada orang lain.</p>"
            "</div>"
        )
        payload: dict[str, Any] = {
            "from": settings.invitation_from_email,
            "to": [recipient],
            "subject": f"Undangan bergabung ke {workspace_name} di Graphytion",
            "html": html,
            "text": (
                f"Anda diundang ke {workspace_name} sebagai {role}. "
                f"Terima undangan: {invitation_url}. Tautan berlaku selama 7 hari."
            ),
        }
        headers = {
            "Authorization": f"Bearer {settings.resend_api_key_value}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        }
        last_error: Exception | None = None
        for attempt in range(2):
            try:
                async with httpx.AsyncClient(timeout=httpx.Timeout(12.0)) as client:
                    response = await client.post(self.endpoint, headers=headers, json=payload)
                if response.status_code in (429, 500, 502, 503, 504) and attempt == 0:
                    await asyncio.sleep(1)
                    continue
                response.raise_for_status()
                body = response.json()
                message_id = body.get("id")
                if not isinstance(message_id, str) or not message_id:
                    raise InvitationEmailDeliveryError("Email provider returned no message identifier")
                return message_id
            except (httpx.TimeoutException, httpx.RequestError, httpx.HTTPStatusError) as exc:
                last_error = exc
                if attempt == 0:
                    await asyncio.sleep(1)
                    continue
        raise InvitationEmailDeliveryError(
            "Invitation email provider did not confirm delivery acceptance"
        ) from last_error


invitation_email = ResendInvitationEmail()
