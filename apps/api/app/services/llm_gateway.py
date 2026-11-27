from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
from fastapi import HTTPException, status

from app.core.config import settings


@dataclass(frozen=True)
class ModelResult:
    output: dict[str, Any]
    provider_key: str
    model_key: str
    input_tokens: int | None = None
    output_tokens: int | None = None
    request_id: str | None = None


class StructuredModelAdapter(Protocol):
    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_schema: dict[str, Any],
        idempotency_key: str,
    ) -> ModelResult: ...


class ModelRouter:
    """Server-side provider registry. Credentials never leave provider adapters."""

    def __init__(self) -> None:
        self._adapters: dict[str, StructuredModelAdapter] = {}

    def register(self, provider_key: str, adapter: StructuredModelAdapter) -> None:
        key = provider_key.strip().lower()
        if not key or key in self._adapters:
            raise ValueError("Provider key must be unique and non-empty")
        self._adapters[key] = adapter

    def resolve(self, provider_key: str) -> StructuredModelAdapter:
        adapter = self._adapters.get(provider_key.strip().lower())
        if adapter is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "code": "LLM_PROVIDER_UNAVAILABLE",
                    "message": "No configured structured LLM provider is available.",
                },
            )
        return adapter

    def available(self) -> list[str]:
        return sorted(self._adapters)


class OpenAIChatCompletionsAdapter:
    """OpenAI structured-output adapter using strict JSON schema mode."""

    provider_key = "openai"

    def __init__(self, api_key: str, model_key: str, timeout_seconds: int = 60) -> None:
        if not api_key:
            raise ValueError("OpenAI API key is required")
        self._api_key = api_key
        self._model_key = model_key
        self._timeout = httpx.Timeout(float(timeout_seconds), connect=10.0)

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_schema: dict[str, Any],
        idempotency_key: str,
    ) -> ModelResult:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key[:255],
        }
        body = {
            "model": self._model_key,
            "temperature": 0.4,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
            ],
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "graphytion_structured_output",
                    "strict": True,
                    "schema": output_schema,
                },
            },
        }
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(
                        "https://api.openai.com/v1/chat/completions",
                        headers=headers,
                        json=body,
                    )
                if response.status_code in {408, 425, 429} or response.status_code >= 500:
                    if attempt < 2:
                        retry_after = response.headers.get("Retry-After", "").strip()
                        try:
                            delay = min(max(float(retry_after), 0.0), 30.0) if retry_after else 0.5 * (2**attempt)
                        except ValueError:
                            delay = 0.5 * (2**attempt)
                        await asyncio.sleep(delay)
                        continue
                    raise HTTPException(
                        status_code=502,
                        detail={
                            "code": "LLM_PROVIDER_TEMPORARILY_UNAVAILABLE",
                            "message": f"LLM provider remained unavailable after bounded retries (HTTP {response.status_code}).",
                        },
                    )
                if response.is_error:
                    raise HTTPException(
                        status_code=502,
                        detail={
                            "code": "LLM_PROVIDER_REJECTED",
                            "message": f"LLM provider rejected the request (HTTP {response.status_code}).",
                        },
                    )
                payload = response.json()
                choices = payload.get("choices") or []
                message = choices[0].get("message", {}) if choices else {}
                raw_output = message.get("content")
                if not isinstance(raw_output, str):
                    raise ValueError("Provider response did not contain structured JSON content")
                parsed = json.loads(raw_output)
                if not isinstance(parsed, dict):
                    raise ValueError("Structured model output must be a JSON object")
                usage = payload.get("usage") or {}
                return ModelResult(
                    output=parsed,
                    provider_key=self.provider_key,
                    model_key=str(payload.get("model") or self._model_key),
                    input_tokens=usage.get("prompt_tokens"),
                    output_tokens=usage.get("completion_tokens"),
                    request_id=payload.get("id"),
                )
            except HTTPException:
                raise
            except (httpx.TimeoutException, httpx.RequestError, ValueError, KeyError, IndexError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.5 * (2**attempt))
        raise HTTPException(
            status_code=502,
            detail={
                "code": "LLM_PROVIDER_UNAVAILABLE",
                "message": "LLM provider request failed after bounded retries.",
            },
        ) from last_error


class GeminiGenerateContentAdapter:
    """Gemini JSON-mode adapter; Pydantic validates the returned domain schema."""

    provider_key = "gemini"

    def __init__(self, api_key: str, model_key: str, timeout_seconds: int = 60) -> None:
        if not api_key:
            raise ValueError("Gemini API key is required")
        self._api_key = api_key
        self._model_key = model_key
        self._timeout = httpx.Timeout(float(timeout_seconds), connect=10.0)

    async def complete_json(
        self,
        *,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_schema: dict[str, Any],
        idempotency_key: str,
    ) -> ModelResult:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model_key}:generateContent"
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
            "X-Graphytion-Idempotency-Key": idempotency_key[:255],
        }
        body = {
            "systemInstruction": {
                "parts": [{
                    "text": (
                        system_prompt
                        + "\nReturn a JSON object conforming to this schema:\n"
                        + json.dumps(output_schema, ensure_ascii=False)
                    )
                }]
            },
            "contents": [{
                "role": "user",
                "parts": [{"text": json.dumps(user_payload, ensure_ascii=False)}],
            }],
            "generationConfig": {
                "temperature": 0.4,
                "responseMimeType": "application/json",
            },
        }
        last_error: Exception | None = None
        for attempt in range(3):
            try:
                async with httpx.AsyncClient(timeout=self._timeout) as client:
                    response = await client.post(url, headers=headers, json=body)
                if response.status_code in {408, 425, 429} or response.status_code >= 500:
                    if attempt < 2:
                        retry_after = response.headers.get("Retry-After", "").strip()
                        try:
                            delay = min(max(float(retry_after), 0.0), 30.0) if retry_after else 0.5 * (2**attempt)
                        except ValueError:
                            delay = 0.5 * (2**attempt)
                        await asyncio.sleep(delay)
                        continue
                    raise HTTPException(
                        status_code=502,
                        detail={
                            "code": "LLM_PROVIDER_TEMPORARILY_UNAVAILABLE",
                            "message": f"Gemini remained unavailable after bounded retries (HTTP {response.status_code}).",
                        },
                    )
                if response.is_error:
                    raise HTTPException(
                        status_code=502,
                        detail={
                            "code": "LLM_PROVIDER_REJECTED",
                            "message": f"Gemini rejected the request (HTTP {response.status_code}).",
                        },
                    )
                payload = response.json()
                candidates = payload.get("candidates") or []
                parts = (candidates[0].get("content") or {}).get("parts") or [] if candidates else []
                raw_output = "".join(
                    part.get("text", "") for part in parts if isinstance(part.get("text"), str)
                )
                if not raw_output:
                    raise ValueError("Gemini response did not contain JSON text")
                parsed = json.loads(raw_output)
                if not isinstance(parsed, dict):
                    raise ValueError("Structured model output must be a JSON object")
                usage = payload.get("usageMetadata") or {}
                return ModelResult(
                    output=parsed,
                    provider_key=self.provider_key,
                    model_key=self._model_key,
                    input_tokens=usage.get("promptTokenCount"),
                    output_tokens=usage.get("candidatesTokenCount"),
                    request_id=payload.get("responseId"),
                )
            except HTTPException:
                raise
            except (httpx.TimeoutException, httpx.RequestError, ValueError, KeyError, IndexError) as exc:
                last_error = exc
                if attempt < 2:
                    await asyncio.sleep(0.5 * (2**attempt))
        raise HTTPException(
            status_code=502,
            detail={
                "code": "LLM_PROVIDER_UNAVAILABLE",
                "message": "Gemini request failed after bounded retries.",
            },
        ) from last_error


class LLMGateway:
    """Structured-output boundary used by all creative agents."""

    def __init__(self, router: ModelRouter, default_provider: str = "openai") -> None:
        self._router = router
        self._default_provider = default_provider

    async def generate(
        self,
        *,
        agent_key: str,
        system_prompt: str,
        user_payload: dict[str, Any],
        output_schema: dict[str, Any],
        idempotency_key: str,
        provider_key: str | None = None,
    ) -> ModelResult:
        adapter = self._router.resolve(provider_key or self._default_provider)
        return await adapter.complete_json(
            system_prompt=system_prompt,
            user_payload=user_payload,
            output_schema=output_schema,
            idempotency_key=f"graphytion:{agent_key}:{idempotency_key}",
        )


model_router = ModelRouter()
if settings.openai_api_key_value:
    model_router.register(
        "openai",
        OpenAIChatCompletionsAdapter(
            api_key=settings.openai_api_key_value,
            model_key=settings.llm_model_key,
            timeout_seconds=settings.llm_timeout_seconds,
        ),
    )
if settings.gemini_api_key_value:
    model_router.register(
        "gemini",
        GeminiGenerateContentAdapter(
            api_key=settings.gemini_api_key_value,
            model_key=settings.gemini_model_key,
            timeout_seconds=settings.llm_timeout_seconds,
        ),
    )
llm_gateway = LLMGateway(model_router, default_provider=settings.llm_default_provider)
