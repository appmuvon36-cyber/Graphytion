# Phase 01 Local Development

1. Install Node.js 22.14+ and pnpm 10.12.1+ (Corepack recommended).
2. Copy `.env.example` to `.env` and supply credentials locally. Never commit `.env`.
3. Install JavaScript workspace dependencies with `pnpm install`.
4. Install API dependencies in a Python 3.12 environment with `pip install .` from `apps/api`.
5. Start local Redis with `docker compose up redis -d`.
6. Start API: `pnpm api:dev`; customer app: `pnpm --filter @graphytion/web dev`; admin: `pnpm --filter @graphytion/admin dev`.
7. Start Remotion Studio with `pnpm --filter @graphytion/remotion-studio dev`.

No database migration is included in Phase 01. Do not use the production Supabase project as a local test database.
