# AGENTS.md — Graphytion Implementation Governance

## 1. Mission

Implement Graphytion as the production-grade AI Motion Graphic Video Production Platform defined in:

- `docs/MASTER_PRD_Engineering_Specification_v1.0.md`

The PRD and the repository's existing implementation are the controlling engineering references. The PRD is a target specification, not evidence that a feature has already been implemented. Inspect existing code before changing architecture or replacing working modules.

## 2. Repository and branch policy

- Canonical repository: `appmuvon36-cyber/Graphytion`
- Canonical branch: `main`
- All implementation work targets `main`, as explicitly requested by the repository owner.
- Do not create staging, preview, development, or feature branches unless the owner explicitly changes this policy.
- Do not create a Supabase staging project or database branch.
- Do not deploy or trigger a production deployment unless the owner explicitly requests deployment.
- Keep commits small, scoped, descriptive, and reversible.
- Never force-push, rewrite history, or delete existing production data.

## 3. Product and architecture invariants

- Remotion is the core composition and video-rendering engine.
- `apps/api` is the FastAPI business/API control plane.
- Remotion rendering runs in a dedicated Node.js worker; never render inside FastAPI request handlers.
- Supabase PostgreSQL is the primary persistent database.
- Supabase Auth is the identity provider; enforce workspace membership and role authorization.
- Supabase Storage stores private user assets, generated media, subtitles, and rendered outputs.
- PostgreSQL remains the durable source of truth for job state, idempotency, leases, heartbeat and recovery. Per the owner's current Phase 03 execution directive, private Redis may be used only for transient queue wake-up/coordination signals; workers must continue polling and claiming jobs transactionally from PostgreSQL so Redis loss never loses or fabricates a job.
- AI model calls go through a server-side LLM Gateway / Model Router.
- TTS, image generation, alignment, and other external services use provider adapters.
- AI output is structured, schema-validated data. Never execute model-generated JavaScript, JSX, shell commands, SQL, or arbitrary code.
- Remotion compositions may use only allowlisted, versioned components and presets.
- Preview and render must consume the same immutable timeline/composition snapshot.
- Preserve existing working UI and architecture unless a specific PRD gap requires a change.

## 4. Required implementation sequence

Follow dependency order. Do not skip foundational dependencies or mark a phase complete without implementation evidence.

1. Repository foundation, environment and shared contracts.
2. Supabase Auth, profiles, workspace membership, RBAC and project CRUD.
3. FastAPI API contracts and service boundaries.
4. LLM Gateway, model registry, prompt registry and orchestration lifecycle.
5. Prompt Interpreter, Scriptwriter, Story Director and Storyboard.
6. Asset registry, asset validation, TTS, audio and subtitle pipeline.
7. Timeline schema/compiler and Remotion component registry.
8. Remotion Player preview and scene editing.
9. Dedicated Remotion render worker, render queue, output storage and download.
10. Usage metering, billing controls, admin operations and production hardening.

Implement complete vertical slices that connect UI → FastAPI → Supabase/provider/worker → persisted result → UI. Do not build disconnected UI-only or mock-only features.

## 5. Supabase production rules

Target project:
- Project ref: `xtjwmezfzexvupbfsdqt`
- Project URL: `https://xtjwmezfzexvupbfsdqt.supabase.co`

Rules:
- Use this existing production project only.
- Do not create a staging project, preview branch, or temporary Supabase database.
- Do not run test fixtures, destructive reset commands, seed scripts, or database-wide cleanup against production.
- Store every intended schema change as a versioned migration in `supabase/migrations/`.
- Before applying a production migration, inspect the current schema and migration history, check for name/type conflicts, and prepare a rollback/recovery note.
- Apply production schema changes only when the task explicitly includes that database mutation. A code change does not implicitly authorize a production migration.
- Enable RLS on exposed tables and write tenant-aware policies. `TO authenticated` alone is not authorization.
- Use both `USING` and `WITH CHECK` for update policies.
- Never use user-editable `user_metadata` for authorization.
- Never expose Supabase service-role/secret keys in browser code or `NEXT_PUBLIC_*` variables.
- Use private Storage buckets and short-lived signed URLs.
- Never create fake/demo records in production.
- Preserve existing data and objects. No destructive migrations without explicit approval.

## 6. Testing and verification policy

The owner has requested minimal testing and no staging environment.

- Do not create or run large, repetitive, broad, or low-value test suites by default.
- Do not run staging deployments or staging Supabase tests.
- Do not perform synthetic production transactions, mass test-user creation, fake render jobs, or load tests against production.
- Do not claim end-to-end behavior is verified when it has not been exercised.
- Prefer focused static checks, type checks, lint/build checks, migration review, and targeted non-destructive checks only when needed to prevent an obvious regression.
- If the owner explicitly says to skip tests for a task, do not run them; clearly record the verification limitation.
- Never label a feature production-verified based only on compilation or a successful API response.
- For database changes, perform only the minimum safe inspection required to avoid damaging existing production data.

## 7. Main-branch production discipline

Because work is performed on `main`:
- Read the current files and current main HEAD before editing.
- Avoid broad rewrites and unrelated refactors.
- Make additive, backward-compatible changes where possible.
- Keep API changes compatible with the deployed frontend until both sides are updated.
- Keep migrations forward-safe and data-preserving.
- Do not commit secrets, local `.env` files, access tokens, service keys, private credentials, generated customer media, or production data exports.
- Do not trigger deployment workflows unless explicitly requested.
- After each coherent implementation slice, summarize changed paths, commit SHA, migration implications, and remaining work.

## 8. Frontend rules

- Use Next.js, React, TypeScript, responsive mobile-first UI.
- Keep UI clean, minimal, professional, accessible, and consistent with existing design tokens.
- Frontend must call typed FastAPI API clients for business operations.
- Do not access Supabase tables directly from the browser for privileged/business workflows.
- Include real loading, empty, progress, success, and error states.
- Do not present fake progress or fake render completion.
- Preserve user edits and version history.
- Use Remotion Player for preview from canonical composition data.

## 9. Backend and API rules

- FastAPI owns business rules, authorization, orchestration, quota enforcement and provider access.
- Define typed request/response contracts and validate all external inputs.
- Enforce workspace scope and role permissions on every resource operation.
- Use idempotency keys for async generation, billing, and render requests.
- Persist run/task/job state and checkpoints; do not rely on in-memory state.
- Implement bounded retries for transient failures only.
- Support cancellation and recovery for long-running work.
- Redact secrets and sensitive content from logs.
- Do not bypass FastAPI with frontend direct database writes.

## 10. AI and prompt rules

- Each agent has one defined responsibility and a versioned prompt.
- Every agent output must match a JSON schema before persistence.
- Store model/provider, prompt version, usage, cost metadata and artifact provenance.
- Treat uploaded files, retrieved text and user media metadata as untrusted input.
- Use an allowlisted tool interface.
- Do not let an LLM invent statistics, citations, asset availability, or production status.
- No arbitrary code execution from model output.
- Support user review/approval at configured creative checkpoints.

## 11. Remotion and media rules

- Pin Remotion and related package versions; commit lockfiles.
- Use registered components with strict prop schemas and `additionalProperties: false` where applicable.
- No dynamic import or eval based on user/model-controlled strings.
- Timeline uses integer frames at the composition boundary.
- Render jobs pin timeline hash, composition version, component versions, assets, fonts and render profile.
- Verify asset ownership and availability before rendering.
- Render asynchronously in isolated Node.js workers.
- Capture real worker progress and diagnostics.
- Validate actual output metadata before marking a render completed.
- Store outputs in private Supabase Storage and authorize downloads server-side.
- Respect Remotion licensing and all media/font/voice usage rights.

## 12. Security and privacy

- Least privilege for users, workers and providers.
- Tenant isolation is mandatory.
- Validate upload MIME type, size, duration and ownership server-side.
- Sanitize SVG and restrict risky media formats.
- Use short-lived signed URLs.
- Do not expose internal stack traces or provider secrets.
- Record security-relevant actions in audit logs.
- Implement deletion/retention behavior for project artifacts and generated media.
- Voice cloning requires documented consent and usage rights.

## 13. Code quality and dependency policy

- Prefer clear modular code over premature abstraction.
- Pin dependencies and commit lockfiles.
- Avoid adding dependencies when existing platform capabilities suffice.
- Keep shared schemas/contracts synchronized between Python and TypeScript.
- Do not silently rename public API fields or database columns.
- Update relevant docs when changing architecture, API, schema, or operations.
- Keep environment variable examples in `.env.example` with placeholders only.

## 14. Completion reporting

A task report must state:
- What was implemented.
- Files and modules changed.
- Main branch commit SHA (if committed).
- Supabase production changes, if any; otherwise explicitly state none.
- Deployment status; do not imply deployment if none occurred.
- Focused verification performed or intentionally skipped.
- Known blockers and next implementation phase.

Do not claim "complete", "production-ready", "tested", "deployed", or "verified" without evidence.

## 15. Explicit prohibitions

- No staging Supabase.
- No test/staging deployments.
- No broad or repetitive test campaigns by default.
- No fake/mock data in production paths.
- No arbitrary LLM-generated code execution.
- No frontend bypass of FastAPI.
- No public exposure of secrets or private storage.
- No destructive database changes without explicit approval.
- No force-push or history rewrite.
- No deployment without explicit instruction.
