from __future__ import annotations

from typing import Any

import httpx
from fastapi import HTTPException, status

from app.core.config import settings


class SupabaseAuth:
    def __init__(self) -> None:
        self.base_url = settings.supabase_url.rstrip("/") + "/auth/v1"
        self.api_key = settings.supabase_anon_key_value

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise HTTPException(status_code=503, detail="Supabase Auth is not configured")
        headers = {"apikey": self.api_key, "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(12.0)) as client:
                response = await client.request(
                    method, f"{self.base_url}{path}", headers=headers, json=payload
                )
        except httpx.TimeoutException as exc:
            raise HTTPException(status_code=504, detail="Supabase Auth request timed out") from exc
        except httpx.RequestError as exc:
            raise HTTPException(
                status_code=503, detail="Supabase Auth is temporarily unavailable"
            ) from exc
        try:
            body = response.json()
        except ValueError:
            body = {}
        if response.is_error:
            message = (
                body.get("msg")
                or body.get("message")
                or body.get("error_description")
                or "Authentication request failed"
            )
            code = (
                status.HTTP_401_UNAUTHORIZED
                if response.status_code in (400, 401, 403)
                else response.status_code
            )
            raise HTTPException(status_code=code, detail=message)
        return body if isinstance(body, dict) else {}

    async def health_check(self) -> bool:
        if not self.api_key:
            return False
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
                response = await client.get(
                    f"{self.base_url}/health",
                    headers={"apikey": self.api_key},
                )
            return response.is_success
        except httpx.RequestError:
            return False

    async def signup(self, email: str, password: str, display_name: str | None) -> dict[str, Any]:
        metadata = {"display_name": display_name} if display_name else {}
        return await self._request(
            "POST", "/signup", payload={"email": email, "password": password, "data": metadata}
        )

    async def login(self, email: str, password: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/token?grant_type=password", payload={"email": email, "password": password}
        )

    async def refresh(self, refresh_token: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/token?grant_type=refresh_token", payload={"refresh_token": refresh_token}
        )

    async def logout(self, access_token: str) -> None:
        await self._request("POST", "/logout", token=access_token)

    async def update_password(self, access_token: str, password: str) -> dict[str, Any]:
        return await self._request(
            "PUT", "/user", token=access_token, payload={"password": password}
        )

    async def recover(self, email: str) -> dict[str, Any]:
        return await self._request("POST", "/recover", payload={"email": email})

    async def verify_user(self, access_token: str) -> dict[str, Any]:
        # Auth's /user endpoint checks the live session, including revocation, beyond JWT signature.
        return await self._request("GET", "/user", token=access_token)

    async def resend_verification(self, email: str) -> dict[str, Any]:
        return await self._request("POST", "/resend", payload={"type": "signup", "email": email})

    async def verify_email(self, token_hash: str, verification_type: str) -> dict[str, Any]:
        allowed = {"signup", "email", "recovery", "invite", "magiclink", "email_change"}
        if verification_type not in allowed:
            raise HTTPException(status_code=422, detail="Unsupported verification type")
        return await self._request(
            "POST", "/verify", payload={"token_hash": token_hash, "type": verification_type}
        )


supabase_auth = SupabaseAuth()
