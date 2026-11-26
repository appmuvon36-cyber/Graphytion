# Graphytion

AI Motion Graphic Video Production Platform.

## Product baseline
- `AGENTS.md` — mandatory engineering governance and implementation rules.
- `AGENTS.MD` — uppercase compatibility copy of the same rules.
- `docs/MASTER_PRD_Engineering_Specification_v1.0.md` — Master PRD and engineering specification.

**Naming note:** The source PRD currently uses “MotionForge AI” as a working product name. Graphytion is the canonical repository/product name; treat this as a naming alignment only and do not change the approved architecture or scope.

## Architecture
- `apps/web`: customer Next.js application
- `apps/admin`: administration application
- `apps/api`: FastAPI backend and business control plane
- `apps/remotion-studio`: Remotion compositions and Player integration
- `services/ai-worker`: AI orchestration workers
- `services/media-worker`: TTS, audio, subtitle and asset processing
- `services/render-worker`: dedicated Remotion rendering
- `packages/*`: shared contracts, API client, design system, motion components, presets and runtime
- `supabase/migrations`: version-controlled production schema migrations

## Environment policy
- Canonical branch: `main`
- Supabase: existing production project `xtjwmezfzexvupbfsdqt`
- No staging branch, preview environment, or staging Supabase project.
- No deployment or production database mutation unless explicitly authorized.
- Follow root `AGENTS.md` before any implementation.
