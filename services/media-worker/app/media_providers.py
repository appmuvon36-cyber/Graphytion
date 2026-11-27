from __future__ import annotations

import asyncio
import base64
from typing import Any, Awaitable, Callable

import httpx


class GeminiMediaProvider:
    """Gemini Developer API adapter for image and asynchronous video generation."""

    API_BASE = "https://generativelanguage.googleapis.com/v1beta"
    IMAGE_MODELS = {"gemini-3.1-flash-image"}
    VIDEO_MODEL = "gemini-omni-1.2-flash"
    TERMINAL_STATUSES = {"completed", "failed", "cancelled"}

    def __init__(self, api_key: str, *, poll_interval: float = 5.0, timeout_seconds: int = 840):
        self.api_key = api_key.strip()
        self.poll_interval = max(2.0, min(poll_interval, 30.0))
        self.timeout_seconds = max(60, min(timeout_seconds, 900))

    def configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("GEMINI_API_KEY_NOT_CONFIGURED")
        return {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}

    @staticmethod
    def _output_blocks(body: dict[str, Any]) -> list[dict[str, Any]]:
        blocks: list[dict[str, Any]] = []
        for step in body.get("steps", []) or []:
            if isinstance(step, dict) and step.get("type") == "model_output":
                blocks.extend(item for item in (step.get("content") or []) if isinstance(item, dict))
        return blocks

    async def _create_interaction(
        self, payload: dict[str, Any], *, timeout: float = 180.0,
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=20)) as client:
            response = await client.post(
                f"{self.API_BASE}/interactions", headers=self._headers(), json=payload,
            )
            response.raise_for_status()
            body = response.json()
        if not isinstance(body, dict) or body.get("error") or not body.get("id"):
            raise RuntimeError("GEMINI_INTERACTION_RESPONSE_INVALID")
        return body

    async def _get_interaction(self, interaction_id: str, client: httpx.AsyncClient) -> dict[str, Any]:
        response = await client.get(
            f"{self.API_BASE}/interactions/{interaction_id}", headers=self._headers(),
        )
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict) or body.get("error"):
            raise RuntimeError("GEMINI_INTERACTION_POLL_RESPONSE_INVALID")
        return body

    async def cancel_interaction(self, interaction_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10)) as client:
            response = await client.post(
                f"{self.API_BASE}/interactions/{interaction_id}/cancel",
                headers=self._headers(),
            )
            if response.status_code not in {200, 202, 204, 404, 409}:
                response.raise_for_status()
            if response.status_code == 204 or not response.content:
                return {"status": "cancelled"}
            return response.json()

    async def _poll_interaction(
        self, interaction_id: str, *, cancel_event: asyncio.Event | None = None,
    ) -> dict[str, Any]:
        deadline = asyncio.get_running_loop().time() + self.timeout_seconds
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(60, connect=15),
        ) as client:
            while True:
                if asyncio.get_running_loop().time() >= deadline:
                    try:
                        await self.cancel_interaction(interaction_id)
                    except Exception:
                        pass
                    raise TimeoutError("GEMINI_INTERACTION_TIMEOUT")
                # Read provider state before honoring cancellation so a provider
                # completion that won the race is preserved as a real artifact.
                body = await self._get_interaction(interaction_id, client)
                status = str(body.get("status", "")).lower()
                if status in self.TERMINAL_STATUSES:
                    if status != "completed":
                        error = body.get("error") or {}
                        code = error.get("code") or status.upper()
                        raise RuntimeError(f"GEMINI_INTERACTION_{code}")
                    return body
                if cancel_event is not None and cancel_event.is_set():
                    try:
                        await self.cancel_interaction(interaction_id)
                    except Exception:
                        pass
                    # Cancellation may race with completion. Re-read once before
                    # reporting cancellation; never discard a completed output.
                    try:
                        final_body = await self._get_interaction(interaction_id, client)
                        final_status = str(final_body.get("status", "")).lower()
                        if final_status == "completed":
                            return final_body
                    except Exception:
                        pass
                    raise asyncio.CancelledError("GEMINI_INTERACTION_CANCELLED")
                if status not in {"in_progress", "queued", "running"}:
                    raise RuntimeError("GEMINI_INTERACTION_STATUS_UNKNOWN")
                await asyncio.sleep(self.poll_interval)

    async def generate_image(
        self, *, prompt: str, model: str, aspect_ratio: str = "1:1",
        output_format: str = "png", image_size: str = "1K",
        configuration: dict[str, Any] | None = None,
        cancel_event: asyncio.Event | None = None,
        on_operation: Callable[[str], Awaitable[None]] | None = None,
        existing_operation_id: str | None = None,
    ) -> tuple[bytes, str, dict[str, Any]]:
        if model not in self.IMAGE_MODELS:
            raise ValueError("GEMINI_IMAGE_MODEL_UNSUPPORTED")
        if aspect_ratio not in {"1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16"}:
            raise ValueError("IMAGE_ASPECT_RATIO_UNSUPPORTED")
        if output_format not in {"png", "jpeg", "webp"}:
            raise ValueError("IMAGE_OUTPUT_FORMAT_UNSUPPORTED")
        if image_size not in {"512", "1K", "2K", "4K"}:
            raise ValueError("IMAGE_SIZE_UNSUPPORTED")

        mime_type = {"png": "image/png", "jpeg": "image/jpeg", "webp": "image/webp"}[output_format]
        if existing_operation_id:
            interaction_id = existing_operation_id
            body = await self._poll_interaction(interaction_id, cancel_event=cancel_event)
        else:
            body = await self._create_interaction({
                "model": model,
                "input": [{"type": "text", "text": prompt}],
                "response_format": {
                    "type": "image",
                    "mime_type": mime_type,
                    "aspect_ratio": aspect_ratio,
                    "image_size": image_size,
                },
            }, timeout=300.0)
            interaction_id = str(body["id"])
            if on_operation is not None:
                await on_operation(interaction_id)
            status = str(body.get("status", "")).lower()
            if status not in self.TERMINAL_STATUSES:
                body = await self._poll_interaction(interaction_id, cancel_event=cancel_event)
            elif status != "completed":
                raise RuntimeError(f"GEMINI_IMAGE_{status.upper()}")

        image_block = next(
            (item for item in self._output_blocks(body)
             if item.get("type") == "image" and item.get("data")),
            None,
        )
        if image_block is None:
            output_image = body.get("output_image") or {}
            image_block = output_image if output_image.get("data") else None
        if image_block is None:
            raise RuntimeError("GEMINI_IMAGE_OUTPUT_MISSING")
        try:
            content = base64.b64decode(image_block["data"], validate=True)
        except Exception as exc:
            raise RuntimeError("GEMINI_IMAGE_OUTPUT_INVALID_BASE64") from exc
        mime = image_block.get("mime_type") or image_block.get("mimeType") or mime_type
        signatures = {
            "image/png": content.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": content.startswith(b"\xff\xd8\xff"),
            "image/webp": len(content) > 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP",
        }
        if mime not in signatures or not signatures[mime] or not content:
            raise RuntimeError("GEMINI_IMAGE_OUTPUT_MIME_MISMATCH")
        return content, mime, {
            "provider": "gemini", "model": model,
            "provider_operation_id": interaction_id,
            "response_id": body.get("id"),
            "usage": body.get("usage"),
            "image_size": image_size, "aspect_ratio": aspect_ratio,
        }

    async def generate_video(
        self, *, prompt: str, model: str, aspect_ratio: str = "16:9",
        duration_seconds: int = 8, resolution: str = "720p",
        configuration: dict[str, Any] | None = None,
        cancel_event: asyncio.Event | None = None,
        on_operation: Callable[[str], Awaitable[None]] | None = None,
        existing_operation_id: str | None = None,
    ) -> tuple[bytes, str, dict[str, Any]]:
        if model != self.VIDEO_MODEL:
            raise ValueError("GEMINI_VIDEO_MODEL_UNSUPPORTED")
        if aspect_ratio not in {"16:9", "9:16"}:
            raise ValueError("VIDEO_ASPECT_RATIO_UNSUPPORTED")
        if not 3 <= duration_seconds <= 15:
            raise ValueError("VIDEO_DURATION_UNSUPPORTED")
        if resolution not in {"360p", "720p", "1080p", "4k"}:
            raise ValueError("VIDEO_RESOLUTION_UNSUPPORTED")
        if existing_operation_id:
            interaction_id = existing_operation_id
            body = await self._poll_interaction(interaction_id, cancel_event=cancel_event)
        else:
            body = await self._create_interaction({
                "model": self.VIDEO_MODEL,
                "input": [{"type": "text", "text": prompt}],
                "response_format": {
                    "type": "video",
                    "duration": f"{duration_seconds}s",
                    "resolution": resolution,
                    "aspect_ratio": aspect_ratio,
                },
                "generation_config": {"video_config": {"task": "text_to_video"}},
                "background": True,
                "store": True,
            }, timeout=120.0)
            interaction_id = str(body["id"])
            if on_operation is not None:
                await on_operation(interaction_id)
            status = str(body.get("status", "")).lower()
            if status not in self.TERMINAL_STATUSES:
                body = await self._poll_interaction(interaction_id, cancel_event=cancel_event)
            elif status != "completed":
                raise RuntimeError(f"GEMINI_VIDEO_{status.upper()}")
        video_block = next(
            (item for item in self._output_blocks(body)
             if item.get("type") == "video" and item.get("data")),
            None,
        )
        if video_block is None:
            output_video = body.get("output_video") or {}
            video_block = output_video if output_video.get("data") else None
        if video_block is None:
            raise RuntimeError("GEMINI_VIDEO_OUTPUT_MISSING_OR_NOT_INLINE")
        try:
            content = base64.b64decode(video_block["data"], validate=True)
        except Exception as exc:
            raise RuntimeError("GEMINI_VIDEO_OUTPUT_INVALID_BASE64") from exc
        if len(content) < 12 or content[4:8] != b"ftyp":
            raise RuntimeError("GEMINI_VIDEO_OUTPUT_NOT_MP4")
        return content, "video/mp4", {
            "provider": "gemini", "model": self.VIDEO_MODEL,
            "provider_operation_id": interaction_id, "response_id": body.get("id"),
            "usage": body.get("usage"), "duration_seconds": duration_seconds,
            "aspect_ratio": aspect_ratio, "resolution": resolution,
        }
