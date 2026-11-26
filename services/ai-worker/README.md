# Graphytion AI / Creative Worker

This service executes persisted creative production runs using the same
FastAPI domain package as the Graphytion API. It is not a second implementation
of the creative pipeline.

## Container build configuration

- Repository: `appmuvon36-cyber/Graphytion`
- Branch: `main`
- Build context / Railway Root Directory: repository root (leave blank)
- Dockerfile path: `services/ai-worker/Dockerfile`
- Start command: Dockerfile default, `graphytion-creative-worker`

The root build context is required because the image installs
`apps/api/pyproject.toml` and copies `apps/api/app`. Do not set the service
root directory to `services/ai-worker`.

## Runtime configuration

Configure the same server-only runtime dependencies as FastAPI:

- `GRAPHYTION_RUNTIME_DATABASE_URL`: dedicated least-privilege Graphytion
  runtime role URL with TLS. Keep the administrative `DATABASE_URL` separate.
- `APP_ENV`, `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`,
  `SUPABASE_JWT_ISSUER`, and `SUPABASE_JWKS_URL` as required by shared API
  settings.
- `OPENAI_API_KEY` and `LLM_MODEL_KEY` for creative agent execution.
- Any additional server-side settings required by the shared API package.

Never configure browser-exposed variables or commit credentials.

## Execution contract

The worker polls PostgreSQL for durable creative runs and claims work using
the existing transactional claim function and lease lifecycle. It reuses the
same prompt registry, structured-output validation, authorization context,
artifact persistence, usage ledger and workflow event handling as the API
domain implementation. PostgreSQL remains the source of truth; Redis is not
required.

This worker is separate from HTTP request handling. Do not start a second
creative worker loop inside FastAPI when this service is active.

## Verification boundary

A successful image build proves only that the shared worker package installs.
Runtime processing still requires a valid database identity, provider
credentials and a healthy PostgreSQL connection. Do not report a creative run
complete until persisted run/task/event/artifact records confirm its terminal
state.
