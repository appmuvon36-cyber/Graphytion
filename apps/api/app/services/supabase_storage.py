from urllib.parse import quote

import httpx

from app.core.config import settings


class SupabaseStorage:
    """Server-only Supabase Storage adapter; service credentials never leave FastAPI."""

    def _headers(self) -> dict[str, str]:
        key = settings.supabase_service_role_key_value
        if not key:
            raise RuntimeError("SUPABASE_SERVICE_ROLE_KEY is not configured")
        return {"Authorization": f"Bearer {key}", "apikey": key}

    async def health_check(self, bucket: str = "avatars") -> bool:
        try:
            base_url = settings.supabase_url.rstrip("/")
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(
                    f"{base_url}/storage/v1/bucket/{quote(bucket, safe='')}",
                    headers=self._headers(),
                )
            return response.is_success
        except (httpx.RequestError, RuntimeError):
            return False

    async def upload(
        self,
        *,
        bucket: str,
        object_path: str,
        content: bytes,
        content_type: str,
        upsert: bool = False,
        timeout_seconds: int = 60,
    ) -> None:
        base_url = settings.supabase_url.rstrip("/")
        bucket_segment = quote(bucket, safe="")
        object_segment = quote(object_path, safe="/")
        url = f"{base_url}/storage/v1/object/{bucket_segment}/{object_segment}"
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(float(timeout_seconds), connect=15.0)
        ) as client:
            response = await client.post(
                url,
                headers={
                    **self._headers(),
                    "Content-Type": content_type,
                    "x-upsert": "true" if upsert else "false",
                },
                content=content,
            )
            response.raise_for_status()

    async def create_signed_url(
        self, *, bucket: str, object_path: str, expires_in: int = 300
    ) -> str:
        if not 30 <= expires_in <= 21600:
            raise ValueError("Signed URL expiry must be between 30 seconds and 6 hours")
        base_url = settings.supabase_url.rstrip("/")
        bucket_segment = quote(bucket, safe="")
        object_segment = quote(object_path, safe="/")
        url = f"{base_url}/storage/v1/object/sign/{bucket_segment}/{object_segment}"
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                url, headers=self._headers(), json={"expiresIn": expires_in}
            )
            response.raise_for_status()
            payload = response.json()
        signed = payload.get("signedURL")
        if not isinstance(signed, str) or not signed:
            raise RuntimeError("Storage provider returned no signed URL")
        return (
            signed
            if signed.startswith("http")
            else f"{settings.supabase_url.rstrip('/')}/storage/v1{signed}"
        )

    async def remove(self, *, bucket: str, object_path: str) -> None:
        base_url = settings.supabase_url.rstrip("/")
        bucket_segment = quote(bucket, safe="")
        object_segment = quote(object_path, safe="/")
        url = f"{base_url}/storage/v1/object/{bucket_segment}/{object_segment}"
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.delete(url, headers=self._headers())
            if response.status_code != 404:
                response.raise_for_status()
