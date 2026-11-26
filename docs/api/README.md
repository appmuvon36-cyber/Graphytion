# API Contract

FastAPI is the source of truth for HTTP route schemas. Run `pnpm api:openapi` after installing API dependencies to export `docs/api/openapi.json`.

All endpoints are versioned under `/api/v1`. Errors carry a stable code, safe message and request correlation ID. Mutating asynchronous operations must accept idempotency keys.

OpenAPI is generated, not hand-edited. Keep Zod schemas in `packages/contracts` compatible with generated API schemas.


## Integrated route groups

FastAPI mounts these route groups under `/api/v1`:

- **Identity and workspace:** Supabase Auth/session support, profiles, workspace membership, invitations, permissions, and project CRUD.
- **Creative production:** briefs, scripts, storyboards, scenes, creative runs, approval, and cancellation.
- **Project assets:** multipart upload, private asset listing, authorized signed download, and deletion.
- **Timeline:** immutable v2 snapshot save, optimistic version control, history, restore, and fresh signed asset resolution.
- **Voiceover/media:** provider-backed voiceover submission, status, retry, worker claim, heartbeat, artifact completion, failure, and recovery.
- **Subtitles:** track CRUD, segment CRUD, split/merge/reorder, revision history, SRT/WebVTT import and export.
- **Rendering:** snapshot-bound render submission, project render listing, job detail, sidecar artifacts, signed download, cancellation, worker claim/progress/artifact/failure/recovery.
- **Platform Admin:** overview, users, workspaces, projects, invitations, platform admins, audit logs, LLM provider status, render profiles, motion component controls, render jobs, and media jobs.
- **Operations:** health, readiness, system contract, and Resend webhooks.

Customer and Admin browser requests use the same-origin Next.js BFF. The BFF owns HttpOnly session cookies, CSRF checks, and server-to-server forwarding; browser code does not receive Supabase service credentials or bearer tokens.

The render contract is snapshot-first: `POST /projects/{project_id}/renders` accepts the immutable editor snapshot. The compatibility storyboard render route also requires an explicit snapshot body; it must not rebuild a second composition from scene metadata. Preview and render resolve assets from the same project-scoped asset references.

No raw invitation token is returned to the Admin UI. Invitation delivery receives the raw token only inside the server-side email provider adapter; the database stores its digest.
