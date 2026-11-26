# Phase 01 Local Development

1. Install Node.js 22.14+ and pnpm 10.12.1+ with Corepack.
2. Copy `.env.example` to `.env`; add credentials locally only. Never commit `.env`.
3. Run `pnpm install` to resolve the pinned workspace dependencies.
4. Install API dependencies from `apps/api` in Python 3.12 with `pip install .`.
5. No queue broker is required; asynchronous jobs are persisted in PostgreSQL and workers poll through FastAPI.
6. Start API: `pnpm api:dev`; web: `pnpm --filter @graphytion/web dev`; admin: `pnpm --filter @graphytion/admin dev`.
7. Start Remotion Studio: `pnpm --filter @graphytion/remotion-studio dev`.

Phase 01 does not apply database migrations. Do not use production Supabase as a local test database.
