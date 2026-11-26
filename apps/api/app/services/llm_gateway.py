from dataclasses import dataclass
from typing import Any, Protocol

from fastapi import HTTPException, status


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
    """Server-side model adapter registry. Provider credentials stay inside adapters."""

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
                    "message": "No structured LLM provider adapter is registered for this runtime.",
                },
            )
        return adapter


class LLMGateway:
    """Structured-output boundary used by all creative agents."""

    def __init__(self, router: ModelRouter, default_provider: str = "default") -> None:
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
llm_gateway = LLMGateway(model_router)
