# API Contract

FastAPI is the source of truth for HTTP route schemas. Run `pnpm api:openapi` after installing API dependencies to export `docs/api/openapi.json`.

All endpoints are versioned under `/api/v1`. Errors carry a stable code, safe message and request correlation ID. Mutating asynchronous operations must accept idempotency keys.

OpenAPI is generated, not hand-edited. Keep Zod schemas in `packages/contracts` compatible with generated API schemas.
