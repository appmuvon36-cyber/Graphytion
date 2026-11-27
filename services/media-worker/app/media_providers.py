from __future__ import annotations

import asyncio
import base64
import json
import os
from typing import Any
from urllib.parse import quote

import google.auth
import httpx
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import service_account


class GeminiMediaProvider:
    """Gemini image API-key adapter and Agent Platform video OAuth adapter."""

    IMAGE_MODELS = {"gemini-3.1-flash-image"}
    VIDEO_MODEL = "gemini-omni-1.2-flash"
    CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def configured(self) -> bool:
        return bool(self.api_key)

    @staticmethod
    def video_configured() -> bool:
        return bool(os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()) and bool(
            os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
            or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
        )

    @staticmethod
    def _google_access_token() -> str:
        inline = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if inline:
            info = json.loads(inline)
            credentials = service_account.Credentials.from_service_account_info(
                info, scopes=[GeminiMediaProvider.CLOUD_SCOPE],
            )
        else:
            credentials, _ = google.auth.default(scopes=[GeminiMediaProvider.CLOUD_SCOPE])
        credentials.refresh(GoogleAuthRequest())
        if not credentials.token:
            raise RuntimeError("GOOGLE_CLOUD_ACCESS_TOKEN_UNAVAILABLE")
        return credentials.token

    async def _interaction(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not self.api_key:
            raise RuntimeError("GEMINI_MEDIA_PROVIDER_NOT_CONFIGURED")
        async with httpx.AsyncClient(timeout=httpx.Timeout(900, connect=20)) as client:
            response = await client.post(
                "https://generativelanguage.googleapis.com/v1beta/interactions",
                headers={"x-goog-api-key": self.api_key, "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict) or body.get("error"):
            raise RuntimeError("GEMINI_MEDIA_RESPONSE_INVALID")
        return body

    @staticmethod
    def _output_blocks(body: dict[str, Any]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for step in body.get("steps", []) or []:
            if step.get("type") == "model_output":
                blocks.extend(item for item in (step.get("content") or []) if isinstance(item, dict))
        return blocks

    async def generate_image(
        self, *, prompt: str, model: str, aspect_ratio: str = "1:1",
        output_format: str = "png", image_size: str = "1K",
        configuration: dict[str, Any] | None = None,
    ) -> tuple[bytes, str, dict[str, Any]]:
        if model not in self.IMAGE_MODELS:
            raise ValueError("GEMINI_IMAGE_MODEL_UNSUPPORTED")
        if aspect_ratio not in {"1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16"}:
            raise ValueError("IMAGE_ASPECT_RATIO_UNSUPPORTED")
        if output_format not in {"png", "jpeg", "webp"}:
            raise ValueError("IMAGE_OUTPUT_FORMAT_UNSUPPORTED")
        if image_size not in {"512", "1K", "2K", "4K"}:
            raise ValueError("IMAGE_SIZE_UNSUPPORTED")
        body = await self._interaction({
            "model": model,
            "input": [{"type": "text", "text": prompt}],
            "response_format": {
                "type": "image", "mime_type": {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}[output_format],
                "aspect_ratio": aspect_ratio, "image_size": image_size,
            },
            "store": False,
        })
        image_block = next((item for item in self._output_blocks(body) if item.get("type") == "image" and item.get("data")), None)
        if image_block is None:
            image_output = body.get("output_image") or {}
            image_block = image_output if image_output.get("data") else None
        if image_block is None:
            raise RuntimeError("GEMINI_IMAGE_OUTPUT_MISSING")
        try:
            content = base64.b64decode(image_block["data"], validate=True)
        except Exception as exc:
            raise RuntimeError("GEMINI_IMAGE_OUTPUT_INVALID_BASE64") from exc
        mime = image_block.get("mime_type") or image_block.get("mimeType") or "image/png"
        signatures = {
            "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": content.startswith(b"\xff\xd8\xff"),
            "image/webp": len(content) > 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP",
        }
        if mime not in signatures or not signatures[mime] or not content:
            raise RuntimeError("GEMINI_IMAGE_OUTPUT_MIME_MISMATCH")
        return content, mime, {
            "provider": "gemini", "model": model, "response_id": body.get("id"),
            "usage": body.get("usage"), "image_size": image_size,
            "aspect_ratio": aspect_ratio,
        }

    async def _video_interaction(self, *, project: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not project:
            raise RuntimeError("GOOGLE_CLOUD_PROJECT_NOT_CONFIGURED")
        token = await asyncio.to_thread(self._google_access_token)
        url = f"https://aiplatform.googleapis.com/v1beta1/projects/{quote(project, safe='')}/locations/global/interactions"
        async with httpx.AsyncClient(timeout=httpx.Timeout(900, connect=20)) as client:
            response = await client.post(
                url, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
            interaction_id = body.get("id")
            deadline = asyncio.get_running_loop().time() + 840
            while body.get("status") in {"in_progress", "queued", "running"}:
                if not interaction_id or asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError("GEMINI_VIDEO_GENERATION_TIMEOUT")
                await asyncio.sleep(10)
                response = await client.post(
                    f"{url}/{quote(str(interaction_id), safe='')}",
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={},
                )
                response.raise_for_status()
                body = response.json()
        if body.get("status") != "completed":
            raise RuntimeError("GEMINI_VIDEO_GENERATION_NOT_COMPLETED")
        return body

    async def _download_gcs_uri(self, uri: str) -> bytes:
        if not uri.startswith("gs://") or "/" not in uri[5:]:
            raise RuntimeError("GEMINI_VIDEO_GCS_URI_INVALID")
        bucket, object_name = uri[5:].split("/", 1)
        token = await asyncio.to_thread(self._google_access_token)
        url = f"https://storage.googleapis.com/storage/v1/b/{quote(bucket, safe='')}/o/{quote(object_name, safe='')}?alt=media"
        async with httpx.AsyncClient(timeout=httpx.Timeout(900, connect=20)) as client:
            response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            response.raise_for_status()
            return response.content

    async def generate_video(
        self, *, prompt: str, model: str, aspect_ratio: str = "16:9",
        duration_seconds: int = 8, resolution: str = "720p", configuration: dict[str, Any] | None = None,
    ) -> tuple[bytes, str, dict[str, Any]]:
        if model != self.VIDEO_MODEL:
            raise ValueError("GEMINI_VIDEO_MODEL_UNSUPPORTED")
        if aspect_ratio not in {"16:9", "9:16"}:
            raise ValueError("VIDEO_ASPECT_RATIO_UNSUPPORTED")
        if not 3 <= duration_seconds <= 15:
            raise ValueError("VIDEO_DURATION_UNSUPPORTED")
        if resolution not in {"360p", "720p", "1080p", "4k"}:
            raise ValueError("VIDEO_RESOLUTION_UNSUPPORTED")
        project = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
        body = await self._video_interaction(project=project, payload={
            "model": self.VIDEO_MODEL,
            "input": [{"type": "text", "text": prompt}],
            "response_format": [{
                "type": "video", "delivery": "inline",
                "aspect_ratio": aspect_ratio, "resolution": resolution, "duration": f"{duration_seconds}s",
            }],
            "background": False,
            "store": True,
            "stream": False,
            "generation_config": {"video_config": {"task": "text_to_video"}},
        })
        video_block = next((item for item in self._output_blocks(body) if item.get("type") == "video"), None)
        if video_block is None:
            output_video = body.get("output_video") or {}
            video_block = output_video if output_video else None
        if video_block is None:
            raise RuntimeError("GEMINI_VIDEO_OUTPUT_MISSING")
        video_data = video_block.get("data")
        if video_data:
            try:
                content = base64.b64decode(video_data, validate=True)
            except Exception as exc:
                raise RuntimeError("GEMINI_VIDEO_OUTPUT_INVALID_BASE64") from exc
        elif video_block.get("uri", "").startswith("gs://"):
            content = await self._download_gcs_uri(video_block["uri"])
        else:
            raise RuntimeError("GEMINI_VIDEO_OUTPUT_LOCATION_MISSING")
        if len(content) < 12 or content[4:8] != b"ftyp":
            raise RuntimeError("GEMINI_VIDEO_OUTPUT_NOT_MP4")
        return content, "video/mp4", {
            "provider": "google-agent-platform", "model": self.VIDEO_MODEL,
            "response_id": body.get("id"), "usage": body.get("usage"),
            "duration_seconds": duration_seconds, "aspect_ratio": aspect_ratio, "resolution": resolution,
        }
