# Phase 01 — Foundation Architecture

## Runtime boundaries
- Next.js customer/admin apps call FastAPI through the typed API client.
- FastAPI owns authentication verification, authorization, domain services and provider access.
- Supabase PostgreSQL is the persistent source of truth. Phase 01 creates no schema and applies no migrations.
- Redis is transport/coordination only; persisted task state is owned by backend workflows in later phases.
- Remotion runs only in the dedicated Node.js render worker, never inside API request handlers.

## Contracts
- TypeScript domain validation is defined in `packages/contracts` using strict Zod schemas.
- FastAPI publishes OpenAPI as the HTTP contract source.
- Pydantic models use strict validation; keep enum values, nullability and timestamp formats aligned.
- Generate and review OpenAPI changes whenever API routes or models change.

## Security boundaries
- Browser receives only public Supabase URL and publishable key.
- Service-role key, database URL, JWT verification secrets and worker tokens are server-only.
- Authorization must use persisted workspace membership; user-editable JWT user_metadata is not an authorization source.
- Component resolution uses a static allowlist; no model-controlled imports or code execution.
