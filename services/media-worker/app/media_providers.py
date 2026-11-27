from __future__ import annotations

import base64
from typing import Any

import httpx


class GeminiMediaProvider:
    """Gemini Interactions API adapter for image and short-video generation."""

    IMAGE_MODELS = {"gemini-3.1-flash-image"}
    VIDEO_MODELS = {"gemini-omni-1.2-flash", "gemini-omni-1.1-flash"}

    def __init__(self, api_key: str):
        self.api_key = api_key

    def configured(self) -> bool:
        return bool(self.api_key)

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
        if not isinstance(body, dict):
            raise RuntimeError("GEMINI_MEDIA_RESPONSE_INVALID")
        if body.get("error"):
            raise RuntimeError("GEMINI_MEDIA_PROVIDER_ERROR")
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
        output_format: str = "png", configuration: dict[str, Any] | None = None,
    ) -> tuple[bytes, str, dict[str, Any]]:
        if model not in self.IMAGE_MODELS:
            raise ValueError("GEMINI_IMAGE_MODEL_UNSUPPORTED")
        if aspect_ratio not in {"1:1", "3:2", "2:3", "4:3", "3:4", "16:9", "9:16"}:
            raise ValueError("IMAGE_ASPECT_RATIO_UNSUPPORTED")
        if output_format not in {"png", "jpeg", "webp"}:
            raise ValueError("IMAGE_OUTPUT_FORMAT_UNSUPPORTED")
        body = await self._interaction({
            "model": model,
            "input": [{"type": "text", "text": prompt}],
            "response_format": {"type": "image", "aspect_ratio": aspect_ratio},
            "store": False,
            "stream": False,
        })
        image_block = next((item for item in self._output_blocks(body) if item.get("type") == "image" and item.get("data")), None)
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
            "usage": body.get("usage"), "revised_prompt": body.get("revised_prompt"),
        }

    async def generate_video(
        self, *, prompt: str, model: str, aspect_ratio: str = "16:9",
        duration_seconds: int = 8, resolution: str = "720p",
        configuration: dict[str, Any] | None = None,
    ) -> tuple[bytes, str, dict[str, Any]]:
        if model not in self.VIDEO_MODELS:
            raise ValueError("GEMINI_VIDEO_MODEL_UNSUPPORTED")
        if aspect_ratio not in {"16:9", "9:16"}:
            raise ValueError("VIDEO_ASPECT_RATIO_UNSUPPORTED")
        if not 3 <= duration_seconds <= 15:
            raise ValueError("VIDEO_DURATION_UNSUPPORTED")
        if resolution not in {"360p", "720p", "1080p", "4k"}:
            raise ValueError("VIDEO_RESOLUTION_UNSUPPORTED")
        body = await self._interaction({
            "model": model,
            "input": [{"type": "text", "text": prompt}],
            "response_format": {
                "type": "video", "duration": f"{duration_seconds}s",
                "resolution": resolution, "aspect_ratio": aspect_ratio,
            },
            "background": False,
            "store": False,
            "stream": False,
        })
        video_data = (body.get("output_video") or {}).get("data")
        if not video_data:
            video_block = next((item for item in self._output_blocks(body) if item.get("type") == "video" and item.get("data")), None)
            video_data = video_block.get("data") if video_block else None
        if not video_data:
            raise RuntimeError("GEMINI_VIDEO_OUTPUT_MISSING")
        try:
            content = base64.b64decode(video_data, validate=True)
        except Exception as exc:
            raise RuntimeError("GEMINI_VIDEO_OUTPUT_INVALID_BASE64") from exc
        if len(content) < 12 or content[4:8] != b"ftyp":
            raise RuntimeError("GEMINI_VIDEO_OUTPUT_NOT_MP4")
        return content, "video/mp4", {
            "provider": "gemini", "model": model, "response_id": body.get("id"),
            "usage": body.get("usage"), "duration_seconds": duration_seconds,
            "resolution": resolution, "aspect_ratio": aspect_ratio,
        }
