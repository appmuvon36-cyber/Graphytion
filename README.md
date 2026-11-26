# Graphytion

AI Motion Graphic Video Production Platform. This repository contains the production-oriented monorepo foundation and shared contracts.

## Governance and product baseline
- `AGENTS.md` — mandatory engineering governance.
- `AGENTS.MD` — uppercase compatibility copy.
- `docs/MASTER_PRD_Engineering_Specification_v1.0.md` — Master PRD and engineering specification.
- `docs/architecture/phase-01-foundation.md` — Phase 01 architecture boundaries.

**Naming note:** The source PRD uses “MotionForge AI” as a working name. Graphytion is the canonical repository/product name; preserve the PRD scope and architecture while aligning implementation naming.

## Monorepo
- `apps/web`: single Next.js application for customer dashboard and Super Admin (`/admin`, `/admin/workspaces`)
- `apps/api`: FastAPI control plane
- `apps/remotion-studio`: Remotion compositions and Player foundation
- `services/ai-worker`: AI worker process foundation
- `services/media-worker`: media worker process foundation
- `services/render-worker`: dedicated Node.js Remotion worker foundation
- `packages/*`: contracts, API client, design system, motion registry, presets, runtime, templates and prompts
- `supabase/migrations`: versioned schema changes; no Phase 01 migration is applied

## Local development
Requirements: Node.js 22.14+, pnpm 10.12.1+, Python 3.12, Docker.

1. Copy `.env.example` to `.env` and provide local credentials.
2. Run `pnpm install` at repository root.
3. Install API dependencies: `cd apps/api && pip install .`.
4. No external queue service is needed; asynchronous jobs are persisted in PostgreSQL and workers poll via FastAPI.
5. Start API: `pnpm api:dev`; customer and Super Admin web app: `pnpm --filter @graphytion/web dev` (Super Admin is served at `/admin`).
6. Remotion Studio: `pnpm --filter @graphytion/remotion-studio dev`.

## Environment and production policy
- Main branch is canonical.
- Supabase project: `xtjwmezfzexvupbfsdqt` (existing production project only).
- No staging Supabase project, preview environment, or test database is created.
- No production database mutation or deployment without explicit authorization.
- Never commit `.env`, secrets, service-role keys, or production data.
- Browser code must not perform privileged Supabase database operations; business workflows go through FastAPI.
