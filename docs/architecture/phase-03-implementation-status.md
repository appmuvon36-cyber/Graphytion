# Graphytion Phase 03 Implementation Status

**Phase:** Remotion Motion Graphic Engine Completion & Full Runtime Integration  
**Repository:** `appmuvon36-cyber/Graphytion`  
**Branch:** `main`  
**Supabase:** `xtjwmezfzexvupbfsdqt`  
**Status:** OPEN — implementation is progressing, but Phase 02 database/runtime dependencies prevent end-to-end verification.

## Current execution

| Area | Status | Evidence / blocker |
|---|---|---|
| Multi-layer composition contracts and component registry | IMPLEMENTED | Existing versioned composition runtime and allowlisted component registry remain the shared source. |
| Immutable timeline snapshots and render pinning | IMPLEMENTED | Existing snapshot/version/hash and render-job contracts are present. Runtime job execution is not verified. |
| Remotion preview and render composition reuse | IMPLEMENTED | Existing Remotion composition bundle is shared; render-worker build is being refreshed. Browser preview/render parity is not yet runtime-verified. |
| Gemini TTS provider adapter | IMPLEMENTED | Media Worker routes Gemini/OpenAI per persisted job; Gemini 3.8 Flash-Lite is the API-key default, style metadata is supported, WAV/PCM is converted to MP3 with FFmpeg. |
| Gemini TTS production generation | BLOCKED | Media Worker has the Gemini credential and latest code deployment, but FastAPI private DNS does not resolve while API is not running. No real TTS job has completed. |
| Word-level alignment | DEFERRED | Gemini TTS does not return word-level timestamps. OpenAI Whisper alignment remains optional and requires `OPENAI_API_KEY`; no fabricated alignment is written. |
| Audio metadata and waveform artifacts | IMPLEMENTED | Existing real audio-analysis pipeline remains in the Media Worker. Runtime artifact persistence awaits API connectivity. |
| PostgreSQL durable job lifecycle | IMPLEMENTED | PostgreSQL remains authoritative for job rows, atomic claims, leases, heartbeat, retry, cancellation and recovery. |
| Redis worker wake-up integration | IMPLEMENTED | API publishes best-effort queue notifications; Media/Render Workers consume them and retain PostgreSQL polling fallback. |
| Redis Railway service | BLOCKED | Railway rejected service provisioning with: “Free plan resource provision limit exceeded.” No Redis service is present in the production environment. |
| Private Supabase Storage artifacts | IMPLEMENTED | Existing private bucket, API authorization, signed URL and artifact metadata paths are present. End-to-end storage is not runtime-verified. |
| Super Admin control plane | IMPLEMENTED | Served by consolidated Web service routes `/admin` and `/admin/workspaces`; no standalone Admin service. |
| FastAPI runtime | BLOCKED | Latest Railway deployment built successfully but failed startup because `DATABASE_URL` does not use the dedicated `graphytion_api` login at the Graphytion Supabase database host with TLS. Runtime logs confirm Pydantic rejected the configured value. |
| Invitation delivery | BLOCKED | API no longer fails startup when Resend is absent, but live delivery still requires Resend API key, webhook secret and verified sender identity. |
| Full private-network worker integration | BLOCKED | Media Worker reports DNS resolution failure for `graphytionapi.railway.internal` because FastAPI is not healthy. |
| One real submit → claim → process → artifact → complete cycle | BLOCKED | Cannot run until FastAPI, database role and pending migrations are available. |

## Phase 02 dependency gate

- The last known Supabase migration inspection recorded migrations 001–003 as applied.
- Migrations 004 and 005 were last recorded as pending. Migration 005 creates the least-privilege `graphytion_api` runtime role; its LOGIN/password setup must be completed before the runtime URL can work.
- Migrations 016–019 were previously recorded as committed but unapplied. The exact current production migration history has not been re-read in this execution because the Graphytion Supabase project is not connected through the available Supabase connector.
- Do not bypass the database-role check by using `postgres`, `supabase_admin`, or an RLS-bypass role.
- The API now accepts `SUPABASE_SECRET_ROLE_KEY` as an alias for the server-side Supabase secret and can start without Resend configured; invitations remain unavailable until Resend is configured. Gemini 3.8 Flash-Lite is used with the configured Gemini API key; the full Gemini 3.8 Flash TTS endpoint requires the separate Gemini Enterprise API authentication path.

Required database URL shape after the runtime role has been created and enabled:

```text
postgresql+asyncpg://graphytion_api:<password>@db.xtjwmezfzexvupbfsdqt.supabase.co:5432/postgres?ssl=require

Or, for Supavisor transaction pooling, use the project-scoped login `graphytion_api.xtjwmezfzexvupbfsdqt` on the `*.pooler.supabase.com` host with TLS. The API disables asyncpg's prepared statement cache for Supavisor.
```

A conventional `postgresql://` or `postgres://` URL is normalized to the asyncpg scheme, but the database user and host are still strictly validated.

## Redis design decision

The owner's current Phase 03 directive supersedes the earlier brokerless decision only for transient queue coordination. Redis is used for worker wake-up notifications; PostgreSQL remains the durable source of truth. If Redis is unavailable, workers continue polling PostgreSQL and job state is not lost. The Redis service could not be provisioned under the current Railway resource quota.

## Runtime status at last inspection

- Web and Remotion Studio: RUNNING with successful deployments.
- Media Worker: deployment SUCCESS; runtime API polling BLOCKED by FastAPI private DNS.
- Render Worker: latest deployment `497a800a-e80a-4d9c-a9dc-8ac0ecd0d12e` is SUCCESS; worker private API connectivity and a real render cycle remain unverified because FastAPI is not healthy.
- FastAPI: latest deployment `a07691d9-c2ba-427a-9742-4ddf737531e3` FAILED at startup due to `DATABASE_URL` validation; the database credential itself is not readable through the connected Railway OAuth integration.
- Standalone Admin Railway service: removed; Super Admin remains part of Web.
- Redis: not provisioned; Railway resource limit prevents creating another service.

## Latest source verification

- GitHub HEAD at last check: `2cf19e1ae1994f885504f24eb6c405e10d6d1caf`.
- Workflow run `45860010134`: SUCCESS. It completed workspace typecheck, Web/Admin build, Remotion Studio bundle, migration SQL parsing, Python API/worker compile and import checks, and FastAPI startup smoke check under CI configuration. This does not replace production database connectivity verification.
- Railway latest deployments: Web SUCCESS, Remotion Studio SUCCESS, Media Worker SUCCESS, Render Worker SUCCESS, FastAPI FAILED.
- Redis service provisioning was rejected by Railway due to the plan's resource provisioning limit; no Redis deployment or private endpoint exists in this environment.

## Completion gate

Phase 03 remains OPEN. Do not mark it complete until:
1. Phase 02 migrations and the dedicated runtime DB login are applied and verified against Production.
2. FastAPI is RUNNING and `/api/v1/ready` verifies database, Supabase Auth/JWKS and private Storage.
3. Media and Render Workers resolve the private API endpoint and authenticate successfully.
4. Redis is provisioned or the owner explicitly keeps the PostgreSQL polling fallback.
5. One real voiceover job and one real render job complete with persisted private artifacts and valid download authorization.
6. Preview and final render are verified against the same immutable composition snapshot.
7. Invitation delivery and Admin authorization are verified against the live production runtime.


## Production execution correction — 2026-11-26

The Graphytion Supabase connector binding is available under the account that owns project ref `xtjwmezfzexvupbfsdqt`. The earlier inspection used the wrong linked account; this was an execution selection error, not a connector outage.

- Production project `xtjwmezfzexvupbfsdqt` was found and confirmed `ACTIVE_HEALTHY` in `ap-northeast-1`.
- Production migration history was read directly. Migrations 001–003 were already applied. Migrations 004–019 were then applied sequentially and each migration tool call returned success. The resulting history contains 19 migrations.
- The production schema now contains the Phase 03 timeline, render jobs, render attempts, render profiles, motion component controls, subtitles, audio generations, audio analysis artifacts, project assets, orchestration tables, and render artifacts.
- Storage buckets `avatars` and `project-assets` are both private. The avatars bucket has a 5 MiB limit and image MIME allowlist. The project-assets bucket is private; object metadata is tenant-scoped in `public.project_assets`.
- The `graphytion_api` and `graphytion_runtime` roles exist and were verified as NOLOGIN, NOSUPERUSER, NOCREATEDB, NOCREATEROLE, NOBYPASSRLS. This is the intended least-privilege baseline.
- Migration 005 was adapted at application time to omit ALTER ROLE attribute statements rejected by Supabase's managed-role privilege boundary; the created roles already have safe non-admin defaults. The repository migration file was updated on main to omit those unsupported ALTER ROLE statements. Runtime LOGIN/password remains a separate owner credential action.
- Latest main source commit for the migration correction: `f558a466fc3a62e2c6f08eeaaa61865f921e5cb8`.
- The API deployment triggered from this commit built successfully but still failed startup because the current Railway `DATABASE_URL` does not satisfy the required dedicated login/password validation. Do not use admin credentials to bypass this gate.
- The connected Railway OAuth account returns variable names only; it does not expose secret values. Set the `graphytion_api` login password through the Supabase SQL editor/approved secret manager, then update API service `DATABASE_URL` in Railway to the project-scoped Supavisor URL with TLS. Do not place the password in Git or chat.
- Redis is still not provisioned. PostgreSQL polling fallback remains the durable execution path; Redis is optional for wake-up coordination.

Phase 03 remains OPEN until FastAPI becomes healthy, worker private DNS/authentication succeeds, and one real media job plus one real render job persist validated private artifacts and complete through the customer flow.


## API integration continuation — 2026-11-27

Execution focus is endpoint and API integration; no synthetic production jobs, TTS calls, render calls, staging, or real end-to-end tests were run.

- Customer Studio now exposes the existing Gemini TTS provider adapter alongside OpenAI. Gemini is the default selection and uses the repository's configured `gemini-3.8-flash-lite-tts` model and supported prebuilt voice list. The selected provider/model/voice are passed to the existing FastAPI voiceover endpoint.
- Render idempotency now compares the full immutable request identity: snapshot hash, render profile, resolved render configuration, and composition version. Reusing one key for a materially different render request returns HTTP 409 rather than replaying an incompatible job.
- Voiceover idempotency now compares text, provider, model, voice, language, scene, subtitle segment, and generation configuration. Reusing one key for a different voiceover request returns HTTP 409.
- Existing FastAPI route groups remain mounted through the versioned router: identity/workspaces/projects, creative production, assets, timeline, voiceover, subtitles, render/worker lifecycle, platform administration, webhooks, health/readiness, and system contract.
- Customer Studio uses the same-origin Next.js BFF; the BFF forwards the HttpOnly session to the FastAPI base URL configured with the `/api/v1` prefix. Browser code does not receive or forward bearer tokens directly.
- No endpoint or worker runtime status is upgraded to RUNNING/VERIFIED by this source-only integration work. Production API activation still depends on the dedicated `graphytion_api` LOGIN/password and matching Railway `DATABASE_URL`; Resend remains required for live invitation delivery. Redis remains optional for durable correctness because PostgreSQL polling is the fallback.

Latest source commits for this continuation:
- `fb7a85959e9deffb6a1d99cab583df949923de26` — expose Gemini/OpenAI provider selection in Customer Studio.
- `525efea7360656e9761f2a4042402daa0dabbdf0` — validate full render idempotency payload.
- `c5154f57ea9748daa2c536fe7a974caf6723be66` — validate full voiceover idempotency payload.

Phase 03 remains OPEN. This continuation deliberately does not claim runtime completion or end-to-end verification.


## Timeline and API integration continuation — 2026-11-27

This continuation implements source-level integration fixes and editor capability completion. No production TTS, render, media, or job transaction was executed.

- Timeline save API now returns the same fresh, short-lived signed asset resolver map used during ownership validation. Customer Studio replaces its preview resolver map with that response after saving, so newly referenced project assets become previewable without storing signed URLs in the immutable snapshot.
- Shared Remotion TimelineComposition now renders an explicit missing-media placeholder for unresolved media/font references in the interactive preview instead of crashing the Player. Render submission still validates project asset ownership and availability before a worker can claim the job.
- Customer Studio no longer exposes a storyboard-card render action that reconstructed a separate composition from storyboard scene metadata. The supported render action submits the exact current editor snapshot to `POST /projects/{project_id}/renders`.
- The compatibility storyboard-render endpoint now requires an explicit `RenderCreate` snapshot body and verifies that the storyboard and its source script are approved. It no longer rebuilds a second composition from scene metadata.
- Remotion Studio registers only the canonical `GraphytionTimeline` composition. Its Player wrapper accepts `snapshot` and `resolvedAssets` and uses the same `TimelineComposition` component as Customer preview and the Node render worker. The former static title-only demo composition is no longer registered.
- Timeline Editor now exposes clip-level source trim and playback-rate controls (the prior controls wrote props that were shadowed by clip-level defaults), transition-in/out settings, paired overlapping crossfade creation, crop fit/focal point/scale/normalized region, and keyframe properties for opacity, scale, translation, rotation, and volume.
- Crop region editor clamps normalized bounds. No schema migration was required; the existing v2 composition contract already defines these fields.
- API client exposes `put` and multipart `upload` helpers while preserving same-origin BFF, HttpOnly-cookie session, CSRF, and no-browser-bearer-token rules.

Source commits in this continuation:
- `953d4ad4c3d89a0b81dc6007ae3cf78ba27df2df` — timeline save returns signed resolver map.
- `82b7d2b66b6896716e9064518b0485ed61587282` — unresolved media placeholder in Remotion preview.
- `789df3fa1c8215ff816d130ce140914e2b53412e` — Customer Studio uses current editor snapshot and removes divergent storyboard render action.
- `af4e39a9ed8aeed78e729e73009c12c2f82f8288` — storyboard render API uses caller-supplied immutable snapshot.
- `7936e2243c17c42524e6b38f3a58c2aefa5aacf6` and `5e7a3702d63e634f6dba0381d96261eb5e701db8` — canonical Remotion composition and Player.
- `001035c24b441d8d166050ee70a7fd030ab3303d`, `17d4149790860b26b89a1bce3fb439e6f9c2506f`, `c7a63db0ad0e9dacc0e5fe09b1a409f19a8489fc` — timeline editor controls, crop bounds, and crossfade pairing.
- `2b60120bd114a8a2dad444ab3a3e4941251c8c65` — storyboard render requires explicit snapshot.

Production runtime remains blocked by the dedicated database login/password and API startup validation. Railway logs still show the API deployment failing at `DATABASE_URL` validation, with worker DNS lookups failing while the API has no running replica. No Redis service is provisioned; PostgreSQL polling remains the durable queue fallback. Phase 03 remains OPEN.


## Railway dependency wiring — 2026-11-27

- Corrected production watch patterns for `@graphytion/web`, `@graphytion/remotion-studio`, and `@graphytion/render-worker`. Web and Remotion Studio now rebuild when shared `packages/**` or workspace manifests/lockfiles change; Render Worker additionally watches the Remotion Studio bundle source. These Railway config updates are live for subsequent deployments and were not staged.
- Existing service inventory confirms one API, one Web, one Media Worker, one Remotion Studio, and one Render Worker. No duplicate application service was created.
- A verified Railway Redis template deployment was requested for the production environment. The service was not yet present in the environment inventory at the time of this record; do not treat Redis as provisioned or wired until it appears and its private `REDIS_URL` is attached to API and both workers.
- Latest observed Railway API deployment still fails startup at the deliberate `DATABASE_URL` validator because the configured value does not satisfy the dedicated `graphytion_api` login/password requirement. The API private endpoint therefore has no healthy replica; worker logs show DNS lookup failures to `graphytionapi.railway.internal` while the API is down.
- Media Worker, Render Worker, Web, and Remotion Studio each have a successful deployment/online replica in the current Railway inventory. Worker process liveness is not evidence of API connectivity or successful job processing.

Phase 03 remains OPEN. No production job or media generation was executed.


## Runtime credential separation and validator correction — 2026-11-27

- Railway deployment logs now expose only sanitized database connection identity fields (host, username, port, driver), never the password.
- The observed production value was a syntactically valid SQLAlchemy URL targeting the correct Graphytion direct database host, but its login identity was `postgres`. This is not a URL-format error; it is an administrative database identity and cannot be accepted as the FastAPI least-privilege runtime role under AGENTS.md and the Phase 02 security model.
- To avoid requiring replacement of the existing `DATABASE_URL`, FastAPI now prioritizes a separate `GRAPHYTION_RUNTIME_DATABASE_URL` environment variable. The existing `DATABASE_URL` remains untouched and is only a backward-compatible fallback when the runtime-specific variable is absent.
- The runtime URL must use `graphytion_api` (or its project-scoped Supavisor login), the Graphytion database endpoint, TLS, and a real password. No administrator credentials are accepted for runtime.
- The Railway API service has not yet been supplied with `GRAPHYTION_RUNTIME_DATABASE_URL`; therefore the latest API deployment cannot become healthy until that least-privilege credential is provisioned. No Supabase schema mutation or migration was run during this continuation.
- Source commits: `40ae329732f5fd8c1bba2bd1e64c6ccba7ab13f8` (runtime URL precedence), `61579c520be0e815abbdbddbfbcaeddcaa1ed9f6` (.env example), `115c62225e63de3f77cb8f83431da861e1318c44` (diagnostic wording).

Phase 03 remains OPEN. This is a configuration boundary blocker, not a database URL syntax defect. No TTS, render, or synthetic production job was executed.


## Phase 03 continuation — global render controls, admin recovery, Railway queue wiring — 2026-11-27

- Added migration `202611270001_phase_03_platform_render_settings` and applied it to Supabase production. The singleton settings row is present with concurrency=2, lease=300 seconds, max attempts=3, max artifact size=536870912 bytes.
- Added migration `202611270002_phase_03_render_capacity_function` and applied it to Supabase production. The security-definer capacity function returns the global concurrency/lease/retry/output limits and active render count without granting workers cross-tenant render-job reads.
- FastAPI render submission pins the global max-attempt value. Worker claim serializes the capacity check with a transaction advisory lock, applies the global concurrency cap, and uses the configured lease. Artifact upload uses the configured output limit (bounded by the current 512 MiB application upload cap).
- Super Admin now has audited global render settings controls. Admin can retry failed render and media jobs; retry requests are authorized server-side, audited, preserve attempt history, and send a best-effort queue notification while PostgreSQL remains authoritative.
- Customer Studio/Admin web source changes were pushed to `main`; Railway web deployment reported SUCCESS for the updated UI. API deployment continues to fail at settings validation because `GRAPHYTION_RUNTIME_DATABASE_URL` is not configured and the existing `DATABASE_URL` authenticates as `postgres`. The database URL itself parses correctly and targets the correct Graphytion host.
- Supabase role inspection confirms `graphytion_api` and `graphytion_runtime` are both NOLOGIN, non-superuser, no-CREATEDB, no-CREATEROLE, no-BYPASSRLS; `graphytion_api` is a member of `graphytion_runtime`. The postgres login has CREATEROLE and BYPASSRLS. No change was made to the existing administrative DATABASE_URL.
- Railway Redis template deployment did not result in a Redis service appearing in the project inventory. A direct service create attempt was rejected by Railway with the Free Plan resource provision limit. The temporary unresolved Redis variable references were cleared back to empty values. Media/Render workers therefore continue to use PostgreSQL polling fallback; Redis is BLOCKED by plan capacity, not code.
- Resend invitation delivery remains dependent on provider credentials and a verified sender. Raw invitation tokens are not returned in the invitation API response; the raw token is only passed server-side to the email adapter and the database stores its digest.
- Phase 03 remains OPEN. No production TTS generation, real render, or job-cycle test was executed in this continuation.


## Worker presence registry — 2026-11-27

- Applied migration `202611270003_phase_03_worker_registry` to Supabase production. It adds a private worker heartbeat registry and security-definer upsert function; Admin reads worker status through FastAPI only.
- FastAPI now exposes authenticated `POST /api/v1/internal/workers/heartbeat` using the existing internal worker token. Render Worker and Media Worker now publish a heartbeat every 30 seconds with worker identity, type, host, deployment version, and non-secret metadata.
- Super Admin now displays workers as online or stale using a 90-second heartbeat threshold. No credentials are included in heartbeat metadata.
- Render capacity accounting now includes cancellation-in-flight jobs so a worker cannot be overcommitted while a cancellation lease remains active.
- Worker presence remains INTEGRATED in source and DB. RUNNING/VERIFIED is pending API runtime activation; the API still rejects the existing `postgres` runtime identity until a dedicated `GRAPHYTION_RUNTIME_DATABASE_URL` is configured.


## Production snapshot after latest source and runtime changes — 2026-11-27

- Latest repository HEAD at this snapshot: `63fd97f7d29af7f458e00f63e44bb3166c5db41a` on `main`.
- Supabase Graphytion is `ACTIVE_HEALTHY`. Migration history contains 22 applied migrations: the original 19 plus global render settings, render capacity function, and worker registry. The global render settings row and capacity function are present. Storage buckets `avatars`, `project-assets`, and `render-artifacts` are all private.
- Runtime role state is unchanged: `graphytion_api` and `graphytion_runtime` are NOLOGIN and least-privilege. The current Railway API deployment log confirms the URL parses and targets `db.xtjwmezfzexvupbfsdqt.supabase.co:5432`, but its username is `postgres`; API startup rejects this administrative identity by design. The new `GRAPHYTION_RUNTIME_DATABASE_URL` variable is not yet present in Railway. The existing `DATABASE_URL` has not been changed.
- Railway current services: Web online (1 replica), Media Worker online (1), Render Worker online (1), Remotion Studio latest deployment SUCCESS, API deployment FAILED during settings validation. API has no public domain; its private endpoint is `graphytionapi`. Worker logs show private DNS lookup failures for `graphytionapi.railway.internal` while the API has no healthy replica.
- Customer Web latest deployment for worker status/admin retry UI is SUCCESS. Remotion Studio has now rebuilt from the current main source and latest deployment is SUCCESS.
- Redis is not provisioned: Railway rejected service creation because the workspace Free Plan resource provision limit was reached. `REDIS_URL` was cleared on API and both workers to avoid dangling references. Workers use durable PostgreSQL polling and lease recovery until Redis capacity is available.
- The Supabase project currently has zero Auth users, zero profiles, zero workspaces, and zero platform-admin rows. Authentication schema is ready, but no one can yet sign in or access the Admin control plane until the first user is created and promoted to `super_admin`.
- The API service currently has no `RESEND_API_KEY` or `INVITATION_FROM_EMAIL`; invitation delivery is implemented but provider activation is blocked by those external credentials. Media Worker has a `GEMINI_API_KEY` variable name configured, but no real TTS was executed.
- Per the project owner's instruction, no real TTS, render, or job-cycle test was run. Phase 03 remains OPEN; source integration is materially advanced but end-to-end runtime cannot be marked VERIFIED until the API runtime login and initial identity/provider setup are completed.


## Production continuation update — 2026-11-27

This section supersedes older runtime observations above where they conflict. It records a fresh production inspection after the owner requested full runtime completion.

- Current main HEAD at inspection: `a18fd7f75ac62aebcb45898fdccda1e03f5a1541`.
- Supabase migration history was re-read and contains 22 applied migrations, including Phase 02 invitation delivery and runtime-role/RLS migrations, plus Phase 03 composition, render settings, capacity function, and worker registry. No pending migration was identified in the production migration list.
- Database endpoint diagnosis: Railway's latest API log parses the configured direct Supabase endpoint as host `db.xtjwmezfzexvupbfsdqt.supabase.co`, port `5432`, driver `postgresql+asyncpg`; the rejected login is `postgres`. This is an application identity/least-privilege rejection, not evidence of malformed URL syntax. Existing `DATABASE_URL` was not changed.
- Railway API has outbound IPv6 enabled. The API still has no healthy replica because `graphytion_api` remains `NOLOGIN`; the API service does not yet expose `GRAPHYTION_RUNTIME_DATABASE_URL`. Railway OAuth returns variable names only, so credential values were not read.
- `graphytion_api` remains non-superuser, non-createdb, non-createrole, non-replication, and non-bypassrls, and is a member of `graphytion_runtime`. Its LOGIN/password must be configured out-of-band; do not use the administrative `postgres` login to bypass the runtime guard.
- Worker DNS failures for `graphytionapi.railway.internal` are downstream of the API having no healthy deployment. Keep the existing private endpoint and re-check DNS after the API becomes healthy; do not substitute a public endpoint.
- A Redis template deployment was requested and returned an asynchronous workflow ID, but repeated live service inventories still show only the five existing Graphytion services and no Redis service. Therefore Redis is NOT RUNNING and no Redis variable references were attached. PostgreSQL polling/leases remain the safe fallback. Confirm the template workflow/plan quota before any retry to avoid duplicate services.
- Storage inspection confirms `avatars`, `project-assets`, and `render-artifacts` are all private. Auth/JWKS-related variable names exist on API, but their values and API-side readiness cannot be verified while the API is offline and the Railway OAuth connector redacts values.
- Production Auth still has zero users, profiles, workspaces, and platform-admin rows. Initial Admin bootstrap requires the owner to create and confirm the first account, then run the documented one-time promotion SQL.
- API variable inventory does not include `RESEND_API_KEY` or `INVITATION_FROM_EMAIL`; invitation delivery remains blocked pending a verified sender and provider credentials.
- The owner’s latest execution instruction now requests one real job cycle after API activation. No TTS/render/job cycle has yet been executed because the API remains offline; once available, perform one real cycle with persisted private artifact and completion evidence, without synthetic records.

**Current completion status:** Phase 03 remains OPEN. Implemented source and existing worker deployments are not equivalent to integrated runtime verification. Immediate critical dependency is a LOGIN-enabled least-privilege `graphytion_api` credential plus the API-only `GRAPHYTION_RUNTIME_DATABASE_URL`; secondary blockers are Redis service provisioning, Resend credentials, and first confirmed Admin identity.


## System development priority reset — 2026-11-27

The owner has explicitly reprioritized Phase 03: continue system/backend implementation without treating Railway availability, Redis provisioning, private DNS, or production runtime credentials as development blockers. Infrastructure activation and production E2E verification remain deferred workstreams; no deployment is authorized by this priority change.

### Implemented source correction

- The previous `services/ai-worker` container only launched an idle process and did not execute creative production runs.
- The AI Worker Dockerfile now builds from the monorepo root, installs the canonical `apps/api` package, and starts the existing `graphytion-creative-worker` entry point. This reuses the same prompt registry, structured-output validation, PostgreSQL claim/lease lifecycle, and persistence logic rather than duplicating business rules in a second worker implementation.
- Added `services/ai-worker/README.md` with the required root build context, Dockerfile path, runtime configuration contract, and verification boundary.
- This is a source-level implementation only. The worker has not been deployed or run against production in this change.

### Next implementation sequence

1. Complete the AI production-run vertical slice: persist stage inputs/checkpoints, worker claim/lease/heartbeat, prompt/model provenance, validated output, usage/cost ledger, approval gates, retry/cancel/recovery, and workflow events.
2. Complete the creative domain lifecycle: source/reference ingestion, brief → script → story arc → storyboard → scene-level revision, artifact version history, and conversion of approved scenes into timeline clips without losing provenance.
3. Complete asset operations: upload validation/quarantine, ownership, metadata extraction, asset search/selection, generated asset provider adapters, signed URL refresh, deletion/retention, and timeline references.
4. Complete voice/audio/subtitle operations: provider routing, TTS jobs, alignment, subtitle revisions/import/export, audio mix/ducking, and media artifact linkage.
5. Complete timeline and render orchestration: compiler diagnostics, render preflight, profile pinning, job lifecycle, preview/thumbnail artifacts, output QC, retries, cancellation, and download authorization.
6. Complete product operations required by the PRD MVP: model/provider registry, prompt registry administration, quotas/usage metering/cost estimates, templates, brand settings, audit visibility, and user-facing failure recovery.
7. Complete typed API-client and Studio integration for every implemented workflow; preserve existing UI and do not add fake/demo fallbacks.

### Current constraints

- Canonical source remains `main`; no feature/staging branch.
- No production schema migration or Supabase mutation was made in this source change.
- No Railway deployment, service creation, secret change, or Redis provisioning was performed.
- Phase 03 remains OPEN. Buildability and runtime behavior must be verified separately; no production completion is claimed.


## Vertical orchestration implementation update — 2026-11-27

Latest source implementation after the priority reset:

- `services/ai-worker/Dockerfile` now builds the canonical `apps/api` package from the monorepo root and invokes `graphytion-creative-worker`; the former idle-only worker container entrypoint is no longer used.
- `apps/api/app/api/v1/routes/creative.py` now persists model-stage outputs and provider provenance as durable workflow checkpoints before artifact assembly. Brief, script, story arc, storyboard, and scene regeneration can resume from their saved structured output after a worker restart/retry instead of repeating completed provider calls.
- Checkpoint writes verify active worker ownership, non-expired lease, and absence of cancellation before committing. The checkpoint hash uses the existing canonical snapshot hashing function. Existing PostgreSQL workflow checkpoint schema is reused; no migration is needed for this change.
- `apps/api/app/workers/creative.py` now supports optional Redis list wake-ups while continuing to claim jobs transactionally from PostgreSQL. If Redis is unset or unavailable, workers continue bounded PostgreSQL polling. Redis never owns job state and missed wake-ups do not lose jobs.
- The creative enqueue API sends the Redis wake-up only after the production run and agent task have committed to PostgreSQL. Redis failure does not roll back or misreport a persisted job.
- These changes complete a source-level resilience and queue-coordination slice for the P0 creative worker. They are not evidence of deployed runtime or end-to-end production execution.

### Status for this implementation slice

- AI Worker package execution entrypoint: IMPLEMENTED (source); INTEGRATED (shared API domain package); runtime VERIFIED: pending.
- Creative stage checkpoints: IMPLEMENTED and INTEGRATED with existing PostgreSQL `workflow_checkpoints`; restart/retry behavior not runtime VERIFIED.
- Redis wake-up: IMPLEMENTED as optional coordination; PostgreSQL polling remains the durable fallback; Redis runtime remains DEFERRED until provisioned.
- Creative API enqueue → durable PostgreSQL row → optional wake-up: IMPLEMENTED in source; end-to-end worker consumption remains unverified.
- Remotion renderer: existing dedicated Node.js worker and shared timeline snapshot architecture retained; no duplicate renderer or new render service created in this change.
- No production migration, secret change, Railway deployment, or synthetic production job was performed.

**Latest implementation source HEAD before this tracker update:** `e2a32a83962fc49e5e42ba846e6adede3f54f60b`. The tracker update itself is committed immediately afterward. Phase 03 remains OPEN.
## Creative worker retry lifecycle correction — 2026-11-27

- `apps/api/app/workers/creative.py` now persists the outcome when `_process_creative_run` raises an API-level execution error instead of leaving the run leased until timeout recovery.
- Transient provider statuses (`429`, `502`, `503`, `504`) use bounded exponential delay and are re-queued only while the persisted `production_runs.max_attempts` budget remains. The retry limit is read from PostgreSQL, not assumed from a hard-coded default.
- Non-retryable validation, authorization, and other permanent HTTP failures are terminally failed immediately.
- Run and task ownership are checked during release; worker ID and lease are cleared, task state/error metadata is persisted, and a sequenced workflow event records retry scheduling or terminal failure.
- The worker heartbeat is stopped before releasing a run, preventing the old worker from extending a lease after retry/terminal transition.
- No schema change is required: existing run/task status values, error fields, lease fields, and workflow event table are reused.
- This is source-level implementation. No worker execution, production job, deployment, or live provider call was performed; runtime behavior remains pending verification.
- Verification status: source diff reviewed and updated file re-fetched from `main`; Python typecheck/build was not run in this connector-only execution.

**Latest source HEAD:** `2c50f10eca6432641caa07ed1fabbe8a6f0f267d`. Phase 03 remains OPEN.
## Media worker transient-provider retry correction — 2026-11-27

- `services/media-worker/app/main.py` now treats provider HTTP `408`, `425`, `429`, and `5xx` responses as retryable; permanent client/configuration errors remain non-retryable.
- Before releasing a retryable TTS job back to PostgreSQL, the worker waits for the provider `Retry-After` value when numeric, otherwise applies bounded exponential backoff derived from the persisted attempt count (1–60 seconds). The worker heartbeat remains active during the wait.
- Retry budget enforcement remains in the FastAPI failure callback and PostgreSQL `audio_generations.max_attempts`; the worker does not fabricate job state.
- No schema migration, production DB mutation, secret change, or deployment was performed. Source was committed and re-fetched; runtime provider behavior and type/build checks remain unverified.
## Durable creative retry scheduling — 2026-11-27

- Added additive migration `202611270004_durable_creative_retry_schedule.sql`: `production_runs.available_at` and `agent_tasks.available_at` default to `now()`, plus a due-queue index.
- The creative claim function now claims queued runs only when `available_at <= now()`. Expired active leases retain the existing recovery path.
- Creative stage failures with transient HTTP statuses (`408`, `429`, `502`, `503`, `504`) now persist bounded exponential retry availability in PostgreSQL. Task/run state and workflow event carry the scheduled delay.
- Removed the worker's duplicate retry transition. `_process_creative_run` is the single owner of persisted domain retry/failure transitions; the worker no longer attempts to mutate a run after its lease has already been released.
- The migration is committed but NOT applied to Supabase production. No production data, secrets, or deployments were changed.

## Media worker provider retry correction — 2026-11-27

- TTS provider HTTP `408`, `425`, `429`, and `5xx` responses are classified as transient; permanent provider/configuration errors remain terminal.
- Before a transient job is released back to PostgreSQL, the media worker waits for a numeric `Retry-After` value when provided, otherwise bounded exponential backoff from persisted attempt count (1–60 seconds), while maintaining the lease heartbeat.
- Retry budget enforcement remains in the FastAPI failure callback and PostgreSQL `audio_generations.max_attempts`.
- Source-only implementation. Runtime execution, provider calls, typecheck/build, and migration application were not performed.

**Latest source HEAD before the next implementation slice:** `9f65584f5b7ca09e26620049d4e35ba4edb8dcda`. Phase 03 remains OPEN.

## LLM provider transient retry hardening — 2026-11-27

- The centralized OpenAI structured-output adapter now retries HTTP `408`, `425`, `429`, and `5xx` responses within its existing bounded three-attempt budget.
- When the provider supplies a numeric `Retry-After` header, the adapter honors it with a 0–30 second cap; otherwise it uses bounded exponential delay. Permanent provider/client errors remain non-retryable.
- The gateway still fails explicitly when no provider adapter is configured; no mock response or fallback output is introduced.
- Source-only change. No provider request, usage event, database migration, deployment, typecheck, or runtime verification was performed.

**Latest source HEAD:** `9f39d9417e584758f6b31012d47257533405a09b`. Phase 03 remains OPEN.


## Central LLM gateway provider expansion — 2026-11-27

- Added an optional Gemini GenerateContent structured-JSON adapter to the existing server-side LLM Gateway. It uses the server-only `GEMINI_API_KEY`, configured `GEMINI_MODEL_KEY`, JSON response mode, and returns provider/model/request metadata plus actual token counts from Gemini `usageMetadata`.
- Added `LLM_DEFAULT_PROVIDER` so the existing creative agents use the centrally selected configured adapter without changing their stage contracts. OpenAI remains the default; Gemini is registered only when its API key is present. An unconfigured provider fails explicitly with 503; no synthetic output or silent provider substitution is used.
- Both provider adapters use bounded retries for transient statuses; the Gemini adapter also validates JSON shape before the existing Pydantic domain-schema validation. Provider credentials remain server-side.
- Added placeholder environment documentation only. No Railway secret was changed and no provider call was made.
- Source-only status: IMPLEMENTED in adapter/configuration source; INTEGRATED through the existing creative pipeline gateway; runtime VERIFIED remains pending provider credentials and execution.
- No migration, production DB mutation, deployment, typecheck, or build was performed.

**Latest source HEAD:** `a768477fa74b52ab1f05083c8c71d0a6534aaa1b`. Phase 03 remains OPEN.


## Remotion timeline/render hardening — 2026-11-27

- Composition rendering now maps timeline fade/dissolve/crossfade transitions into real audio volume fades for audio clips; visual opacity transitions remain unchanged. This keeps audio transitions deterministic under the same immutable snapshot.
- FastAPI composition validation now accepts crossfade only when an outgoing and incoming clip are paired on the same track with an exact overlap, matching the shared TypeScript composition runtime. Null transition metadata is handled safely.
- Project asset resolution now validates image-kind asset references against image MIME types before signing private Storage URLs.
- Render claim responses now include the persisted `max_attempts` budget. The Node Remotion worker retries timeouts only while attempts remain, rather than hard-coding a three-attempt rule or making all timeouts terminal.
- The worker now validates the final output with ffprobe before creating/uploading a thumbnail, and validates preview MP4 container, H.264 codec, dimensions and duration before persisting the preview sidecar.
- Source-only implementation. No production migration, DB mutation, Railway configuration, deployment, or real render job was run. Typecheck/build and runtime rendering are not yet verified in this execution.

**Latest source HEAD:** `55f134bc1443d164c1c2263def1bf1e3ed1a2095`. Phase 03 remains OPEN pending the documented FastAPI runtime/database-role and migration dependencies, followed by a real end-to-end render cycle.


## Production runtime recovery — 2026-11-27

This update supersedes the earlier API/worker connectivity blockers where they conflict.

- The API Dockerfile now binds Uvicorn to Railway's `PORT` (default 8080) and exposes 8080. The previous container listened on 8000 while Railway healthchecked 8080. The API deployment passed the Railway `/api/v1/health` healthcheck; latest API deployment on commit `6c5c5ee6521d05ebc422e5a8ea9bb40e83f2170b` is SUCCESS.
- Both Media and Render Worker `GRAPHYTION_API_BASE_URL` values now target the private API endpoint including the versioned prefix: `http://graphytionapi.railway.internal:8080/api/v1`. This fixes the former port-8000 connection refusal and missing `/api/v1` prefix (404).
- Worker heartbeat exposed an ambiguous `worker_id` reference in `private.graphytion_upsert_worker_heartbeat`. Migration `20261127022404_worker_heartbeat_conflict_target_fix` now targets `worker_heartbeats_pkey` explicitly. It is applied in Production and its matching SQL file is committed to `supabase/migrations/20261127022404_worker_heartbeat_conflict_target_fix.sql`.
- Production migration history now contains 24 entries; the repository contains the matching 24 migration SQL files. The two previously pending migrations, durable creative retry scheduling and worker heartbeat conflict correction, are applied. No destructive migration or data reset was performed.
- Production DB evidence: `graphytion_api` is LOGIN-enabled, non-superuser and non-BYPASSRLS. API worker claim/recovery and heartbeat requests now return HTTP 200. `worker_heartbeats` contains one online Media Worker and one online Render Worker. This verifies API-to-PostgreSQL connectivity for those paths.
- Railway existing services: API, Media Worker, Render Worker have successful deployments on the current source/config; Web and Remotion Studio remain live on their latest successful deployments because their source paths were unchanged and Railway correctly skipped unrelated builds. No new Railway service or database was created.
- Supabase Storage buckets `avatars`, `project-assets`, and `render-artifacts` remain private. Security Advisor returned zero lint findings at this inspection.

### Remaining production gates

- No Auth users, profiles, workspaces, or platform-admin rows exist yet. Initial owner account creation and one-time super-admin promotion are still required before a real customer journey can be exercised.
- Invitation email remains inactive until the verified Resend sender and API credentials are configured on the API service.
- Redis remains unavailable due to the Railway plan's service resource limit; PostgreSQL polling and durable leases remain the active fallback.
- The repository contains the AI Worker Dockerfile and entrypoint, but the existing Railway project currently has no dedicated AI Worker service. No new service was created under the existing-service constraint.
- No real TTS or render job was submitted: there is no production user/workspace/project, and no synthetic production records were created. The worker claim/heartbeat/recovery connectivity is verified; a complete artifact-producing cycle is not.

**Phase 03 remains OPEN.** API liveness, DB-backed worker control paths, and migration parity are restored; Auth bootstrap, invitation delivery, AI Worker service provisioning, Redis capacity, and one real TTS/render artifact cycle remain release blockers.


## Consolidated execution + Templates and Brand Kit vertical slice — 2026-11-27

- Embedded the existing PostgreSQL-backed creative worker loop in the FastAPI application lifespan. The API service now owns creative/AI agent execution without requiring a separate Railway AI Worker service or duplicating the domain worker. It uses the existing atomic PostgreSQL claim, lease, checkpoint, retry, cancellation, and persistence logic. The worker is cancelled cleanly on API shutdown.
- Added persistent workspace composition_templates and brand_kits registries with tenant RLS, workspace-scoped uniqueness/versioning, category/tags/aspect-ratio metadata, JSON composition snapshots, status, and audit events. Added a composite workspace foreign key from projects to Brand Kits.
- Added FastAPI endpoints for listing/creating/applying templates and listing/creating/updating/applying Brand Kits. Template creation captures the latest saved composition while removing cross-project private media references. Applying a template creates a new immutable timeline version and validates the allowlisted component registry.
- Brand Kit tokens are applied to allowlisted timeline props and composition background at timeline save/render snapshot creation. Brand Kit configuration is also included in creative project settings and storyboard visual direction. Logo asset references are validated against active assets in the same workspace.
- Added Customer Studio controls for saving/applying reusable templates and creating/applying workspace Brand Kits through the same-origin typed API client. Existing editor state is updated from the returned immutable template snapshot.
- Service consolidation: the API process now handles AI creative execution internally. Keep existing Media Worker and Render Worker for media/Remotion workloads. The Remotion Studio bundle is already built into the Render Worker image and the Player is embedded in Customer Studio; no additional service is required. The standalone Railway Remotion Studio service had no public/custom domains and no attached volume; it was removed from the production environment after confirming the Player is embedded in Customer Studio and the composition bundle is built inside Render Worker. The existing repository workspace remains intact.
- New migration: 20261127022406_template_brand_registry.sql. It is committed only; it has NOT been applied to Production. Apply only after schema review and explicit production migration authorization.
- No provider calls, user account transactions, TTS/render jobs, staging tests, or production deployments were executed. Railway auto-deploy status must be inspected separately after source push; deployment success is not assumed.

Source-only verification boundary: files are committed after static source review. Typecheck/build and live migration verification remain pending. API/AI worker production execution depends on the existing least-privilege runtime DB configuration; the latest Railway snapshot previously showed API online, but this update does not claim fresh worker execution verification.


## Quota economics vertical integration — 2026-11-27

- Added micro-USD quota accounts, idempotent reservations, usage ledger entries, reconciliation, release, and partial reversal database functions. Reservations are transactionally locked against workspace quota availability; actual provider costs above the estimate are recorded as overage rather than silently discarded.
- Added super-admin APIs for workspace quota provisioning/period rollover, operation price-book management, usage ledger inspection, and idempotent reversals. Added corresponding Admin controls for quota limits and configured TTS/render rates. No rates or quota balances were seeded with invented values.
- Integrated creative-run reservations using the configured provider/model price book and a bounded stage token estimate. Successful runs reconcile against actual token-cost events; terminal failures and cancellations release reservations; recovery cleanup releases reservations for terminal jobs.
- Integrated fixed-rate reservations for voiceover (per 1,000 characters) and Remotion rendering (per second). Completion reconciles the configured operation rate; terminal failure/cancellation releases the reservation; retries receive a fresh reservation key; recovery cleanup handles terminal jobs.
- Voiceover queued cancellation now releases its reservation. Running TTS provider calls are not force-interrupted; cancellation is explicitly rejected while a provider call is running to avoid reporting cancellation while incurring an untracked provider cost.
- New migration 20261127022407_quota_economics.sql is applied and schema-verified in the Graphytion Supabase project. Migrations 20261127022405 (AI model price book), 20261127022406 (template/brand registry), and 20261127022407 (quota economics) are all recorded in Supabase migration history. Official standard model prices were configured for OpenAI gpt-4.1-mini (USD 0.40 input / USD 1.60 output per 1M tokens) and Gemini gemini-2.5-flash (USD 0.30 input / USD 2.50 output per 1M tokens); sources are stored in price-book notes. The database currently has zero workspaces, zero quota accounts, zero TTS/render operation rates, and zero reservations/ledger entries. Therefore no tenant quota can be provisioned yet; TTS and render submissions remain gated until Super Admin configures the actual operational rates, and creative submissions require a workspace quota account.
- Verification boundary: no customer accounts, provider calls, render jobs or test transactions were run. Static source review completed; API/web build and runtime checks will be read from Railway after the commit. The migration will be applied only after a final schema review.


Runtime verification after quota integration: Railway reports the four remaining services online (Web, API, Media Worker, Render Worker). API deployment fa094f34-c6e9-4351-9184-b904488ec5fa passed its health check. Logs confirm the API-embedded creative worker started, Media Worker and Render Worker heartbeat/claim/recovery endpoints return HTTP 200, and no generation/render jobs were created for verification. This confirms service startup and queue polling, not successful provider generation or completed rendering.


## Remaining product blockers — 2026-11-27

The following are deliberately NOT marked complete:

- Image and video generation: the existing project asset lifecycle supports upload, private Storage, signed download, and deletion; voiceover/TTS generation has a worker lifecycle. Dedicated image/video generation provider adapters and persisted generation-job workflows are still missing.
- Dynamic Agent Tool Registry: the allowlisted creative tool registry and scoped authorization are present in code, but a persistent admin-managed registration/publication lifecycle for arbitrary tools is not complete. No model-generated executable code is allowed.
- Brand Kit logo rendering: logo asset ownership validation exists, and color/typography/background tokens are applied to supported composition props. The logo asset is not yet injected as a rendered composition clip. Template snapshots deliberately omit project-private media-bound clips so they can be reused without leaking another project's asset IDs.
- TTS cancellation: queued voiceover jobs can be cancelled and their quota released. A running external TTS provider request is not forcibly interrupted; the API rejects cancellation while it is running to avoid a false cancelled state with provider cost incurred.
- Quota provisioning: migration and accounting functions are deployed, but Supabase currently contains zero workspaces, zero quota accounts and zero TTS/render operation rates. No customer workspace can be provisioned until actual workspace records exist and Super Admin configures the applicable operational rates.
- The current API default model is gpt-4.1-mini. OpenAI's current model documentation marks it deprecated. The price-book entry is present for compatibility, but a supported model migration and matching provider configuration remain required before long-term production use.
- Runtime evidence covers successful service startup, API-embedded creative worker startup, and Media/Render Worker heartbeat/claim/recovery polling. No actual user generation, TTS, image/video, or render job was executed, per the no-customer/no-external-test instruction.

These blockers prevent declaring Graphytion fully complete. Continue implementation in the existing four-service architecture; do not add services or databases to close them.


## Media generation, dynamic agent routing, Brand Kit and asset lifecycle continuation — 2026-11-27

- Media Worker image/video provider adapters and persisted media-job lifecycle are now implemented in source. Video routing uses Google Agent Platform OAuth, and the model contract was corrected to the currently supported `gemini-omni-1.2-flash` model (3–15 seconds, 360p/720p/1080p/4K); the deprecated Omni Flash preview model is no longer selected by Customer Studio.
- Customer Studio exposes image size, video duration and video resolution controls and submits typed API requests to FastAPI. A missing video-resolution state was corrected.
- Dynamic tool execution now consumes the active registered tool's provider/model configuration and agent routing identity through the structured LLM gateway. Handler execution remains a strict server-side allowlist; arbitrary executable code is not accepted. Permission discovery, grant/update/revoke, audit visibility and execution-time authorization remain enforced.
- Brand Kit logo layout configuration (fit, width, height, opacity, anchor and safe-area margin) is applied to the actual composition image clip. Brand Kit identity/version metadata is pinned into the composition snapshot.
- Workspace asset listing now exposes provenance/version fields when the corresponding migration is present. Explicit version upload is migration-gated. Asset deletion refuses to proceed when composition-reference tables are not available and prevents deleting referenced Brand Kit, template, timeline or completed-generation assets.
- New migrations 22408–22413 are committed in the repository. They have NOT been applied to the Graphytion Supabase production database in this continuation. The Graphytion Supabase project is not available through the currently connected Supabase accounts; do not infer that the database schema is current from committed migration files.
- Railway Media Worker currently has `GEMINI_API_KEY`, but its variable inventory does not include `GOOGLE_CLOUD_PROJECT` or Google service-account credentials. Therefore image provider configuration is present by variable name, but video generation remains credential-blocked until the existing Media Worker receives the required Google Cloud project and service-account/ADC configuration.
- No migration was executed, no Railway variables were changed, no deployment was run, and no provider/customer/render transaction was executed in this continuation. CI source verification is pending; no runtime success is claimed.

## Gemini Developer API media provider migration — 2026-11-27

- The repository's `AGENTS.md` authorizes production deployment for explicitly requested implementation during this deployment phase. It prohibits staging/preview deployment, not production deployment; no AGENTS.md prohibition needed removal.
- Media Worker uses model-specific Gemini Developer API contracts: image generation uses `POST /v1beta/models/gemini-3.1-flash-image:generateContent` with `generationConfig.imageConfig`; video generation uses `POST /v1beta/interactions`. Both use the `x-goog-api-key` header.
- Image model: `gemini-3.1-flash-image`. Video model: `gemini-omni-1.2-flash`. Video submission uses background execution; interaction IDs are stored in the existing `media_generation_jobs.provider_job_id` field, retrieved with GET polling, and cancellation is requested through the provider cancel endpoint.
- FastAPI accepts only `provider_key='gemini'` for image and video. Customer Studio now submits that provider key for both media types.
- Removed the Media Worker `google-auth` dependency and removed Google Cloud/Service Account variables from its environment example. No Google Cloud Project, ADC, Service Account, Vertex AI, Agent Platform OAuth, or GCS download path is required by the source adapter.
- Migration `20261127022414_gemini_developer_api_only.sql` normalizes any legacy Agent Platform provider labels and constrains media generation to Gemini. It follows existing media migrations 22409–22413 and must be applied before enabling the new API path in production.
- Provider usage and cost remain unpriced unless returned usage can be reconciled to an active price-book row. No usage or provider cost is fabricated.
- Source implementation is committed to `main`; no live generation request or synthetic transaction was run. Provider runtime, actual provider cancellation outcome, Supabase migration application, and artifact delivery remain pending production evidence.


## Remotion production integration continuation — 2026-11-27

- Render submission no longer reserves, reconciles, or releases quota operations. Render lifecycle is personal-use and has no Graphytion quota debit or pricing dependency. Existing economics tables are retained for compatibility; this slice does not drop or mutate them.
- On validated final artifact upload, FastAPI registers the MP4/WebM in `public.project_assets` using the existing private `render-artifacts` bucket. Provenance and generation metadata include the render job ID, immutable timeline hash, composition version and render profile configuration. The existing Asset Library list, signed preview/download and workspace scoping therefore expose final renders without copying the binary into a second bucket.
- Asset deletion now protects completed render outputs referenced by their persisted render-job metadata. Existing project timeline, template, Brand Kit and generation-history protection remains in place.
- No schema migration is required: the current asset metadata columns and render tables are reused. No Supabase production migration or synthetic render job was run.
- Source-level verification: render API has no quota/fixed-operation references; final artifact insertion matches the existing `project_assets` columns introduced by the applied media runtime migration; worker output still uses ffprobe validation and the existing private storage upload endpoint.
- Runtime render output and Asset Library display remain unverified until a real render is performed; this was intentionally not run under the owner's no-real-test rule.

**Implementation commits:** `aafed8b7cd806ab410da0171595252b4eb4273a8`, `cea3f121e7ad0303360427cf09b5b9c833143ae2`, `c783eeb0a67a2efb68f51e9ee4d8251ea6e62f82`. Phase 03 remains OPEN pending remaining integration and runtime evidence.


## Production database and render integration verification — 2026-11-27

- Supabase production project `xtjwmezfzexvupbfsdqt` now records 30 migrations. All 30 applied migration records have an exact matching versioned SQL file in `supabase/migrations/`; 26 legacy migration filenames were aligned to their actual applied versions without changing SQL bodies.
- Applied the missing `dynamic_agent_tool_registry` migration as version `20261127073738` because the existing FastAPI admin tool-registry routes depend on those three tables. RLS is enabled on all three tables; the four global creative tool definitions are configuration, not synthetic user records.
- Two migrations remain intentionally unapplied: `20261127022411_runtime_price_book_read_policies.sql` (unused pricing read policy in personal mode) and `20261127022413_google_agent_platform_video_provider.sql` (conflicts with the chosen direct Gemini Developer API provider identity). Neither is a Remotion dependency.
- Production schema inspection confirms `render_jobs`, `render_attempts`, `render_artifacts`, `video_timelines`, and `project_assets` exist with RLS enabled. Their tenant policies scope operations through `graphytion_api` and `private.graphytion_is_workspace_member(workspace_id)`.
- Both `project-assets` and `render-artifacts` storage buckets are private. `project_assets` supports render metadata fields used by the new output registration.
- Runtime database inspection: 5 active global render profiles, 8 enabled motion components, one recent online render worker heartbeat and one recent online media worker heartbeat. No synthetic render jobs or assets were inserted; render jobs/assets and render quota reservations remain zero.
- Source commits for Remotion delivery and typed API integration: `aafed8b7cd806ab410da0171595252b4eb4273a8`, `cea3f121e7ad0303360427cf09b5b9c833143ae2`, `c783eeb0a67a2efb68f51e9ee4d8251ea6e62f82`, `0164761ae256deb04a6cd114d06756c2e66da679`, `b83caee955fc5858b1dbf955e29eaa78024b89be`, `7a76bbb56466e6f7a46be6492d198b37e7c63d8e`. Migration alignment and registry migration commits: `0539573cab1c6a13caae031db1c8058a0a44a861`, `f1f1f6af1db08a394d5557b42f254e0461ba0c48`.
- No real render or Gemini generation was run. Output MP4 validity and final Asset Library display remain unverified at runtime by design.


## Personal-use economics removal and final deployment — 2026-11-27

- Creative production runs no longer reserve, reconcile or release AI quota. Token usage events remain for technical diagnostics; no model price book is required to create or complete a creative run.
- Voiceover/TTS create, retry, cancel, artifact completion, failure and recovery no longer reserve or reconcile quota. Remotion admin retry is also quota-free.
- Media generation no longer reads `ai_model_prices` or `quota_operation_prices`, does not estimate provider cost from a price book, and never calculates margin/markup. It records a provider-reported cost only when the provider actually returns one; otherwise the job remains unpriced. Legacy reservation cleanup remains only as a compatibility path and releases any old hold without charging.
- Platform admin no longer exposes workspace quota accounts, quota operation rates, provider price book, media operational price management or quota reversal. Admin usage view is token/event diagnostics only. Billing workspace role is no longer assignable or recognized by API/UI. Existing schema and historical price rows are retained, not used by runtime.
- Production migration `20261127074637_personal_media_no_quota_reconciliation` sets the media quota reconciliation default to `not_required` and limits recovery to legacy jobs with an actual reservation. Current production data has zero quota accounts, zero quota reservations, zero operation-price rows, zero legacy media holds and zero quota debits. Two historical model-price rows remain untouched; no application route reads them.
- Supabase now has 31 applied migrations and 31 exactly matching versioned SQL files. The unused price-book read-policy and Google Agent Platform provider migrations are archived under `supabase/archive/unused_personal_mode_migrations/`; `supabase/migrations/` now contains exactly the 31 applied migrations, with no pending production migration files.
- Latest production services: API deployment `008b7361-9e20-43d2-b1b3-a12b5c008874` SUCCESS; Web `529bfcb4-17fa-47da-825a-96d3e8190a9f` SUCCESS; Media Worker `ed7847c3-fb36-43da-93fb-b17f84689984` SUCCESS; Render Worker `4828e3b9-fae7-44fc-bb5f-34244293c16b` SUCCESS. One replica per service, no active critical/warning issues.
- API logs after deployment show `/api/v1/health` 200, worker heartbeat 200, Media Worker claim 200 and Render Worker claim 200. No image/video generation or Remotion render was run. MP4 output, Asset Library display and download remain runtime-unverified by the explicit no-real-test rule.


## Reliability continuation — 2026-11-27

- Session BFF recovery no longer clears access/refresh cookies when Supabase Auth or FastAPI returns HTTP 5xx. A temporary verification outage returns HTTP 503 and preserves cookies; definitive invalid/expired session responses still clear them. Customer Studio surfaces the temporary verification issue rather than silently treating it as a logout.
- Removed the final obsolete `billing` workspace role option from member invitation and member role controls. API authorization and role validation already accept only owner/admin/editor/member/viewer.
- Customer Studio no longer converts a failed media-generation list request into an empty array. Other project panels remain usable, and the media panel shows the actual API error.
- Media Worker heartbeat handling no longer converts transient API/network failures into user cancellation. It retries the heartbeat; a confirmed 409 lease loss stops the provider operation without attempting to mark another worker's job cancelled.
- If Gemini creates an interaction but FastAPI cannot persist its operation ID, Media Worker attempts to cancel that untracked provider interaction before surfacing the persistence error.
- Render Worker no longer cancels a valid render after a single transient API heartbeat/progress failure. It stops only on a definitive HTTP 409 lease loss or explicit cancellation.
- Gemini Developer API requests now explicitly set `response_format.delivery='inline'` for both image and video. The adapter consumes inline base64 bytes and persists them to Graphytion private Storage; no GCS/Vertex/ADC dependency is introduced.
- Render artifact registration is transactional with render job completion and Project Asset insertion. If database metadata persistence fails after upload, the API rolls back and attempts to remove the deterministic Storage object so the job can safely retry.
- No new Supabase schema changes were required in this continuation. The existing 31 applied migrations, tenant RLS, and private Storage buckets remain unchanged.
- Railway production builds/deployments for the affected web, API, media-worker and render-worker code paths succeeded. API health returned 200; API logs show worker heartbeat and media/render claim/recovery endpoints returning 200; web logged Ready; media worker logged started; render worker logged started. These are operational checks only, not proof of actual Gemini output or MP4 render completion.


## Unified Production Completion Continuation — 2026-11-27

Evidence baseline: source HEAD `ac7be36b5cf0d5a4d64a60406672809556ad70bf` before this tracker update. This section supersedes older migration-count and production-orchestration notes above where they differ.

### Implemented / integrated in this continuation

- **Unified Production Orchestrator:** persisted run/step/dependency state remains PostgreSQL-authoritative. Approval gates, dependency readiness, safe retry, cancellation/failure propagation, idempotency, checkpoints, execution events and recovery are backed by the existing orchestration schema and API. Child-job status changes now refresh the owning Production Run through database triggers on `agent_tasks`, `media_generation_jobs`, `audio_generations`, `render_jobs`, `project_assets`, `subtitle_tracks`, `video_timelines` and `render_artifacts`.
- **Agent lineage:** the Customer Studio workflow now creates a persisted `agent` step before creative review and links the run's existing `agent_task` to that step. Human/manual completion is restricted to an approved `creative` review gate; media, audio, subtitle, timeline and render steps cannot be manually marked complete to bypass their child-job/artifact evidence. Safe retry now refreshes the persisted run aggregate.
- **Production lineage:** composite scope foreign keys link run, workspace, project and parent step across agent tasks, media generation, audio generation, subtitles, timelines, render jobs, render sidecars and project assets. Step dependencies and reused/generated asset links have relational FKs. A direct schema check found zero missing FK-leading indexes.
- **Render artifact metadata:** the render worker already sends ffprobe-derived metadata. The API now validates duration, dimensions, video/audio codec and container against the immutable composition snapshot/render profile, then persists output metadata on `render_jobs`. This allows QC/delivery aggregation to rely on verified persisted metadata rather than an assumed render success.
- **Agent Intelligence:** the canonical registry contains five enabled creative agents (Prompt Interpreter, Scriptwriter, Story Director, Storyboard/Visual Director and Scene Visual Director). Four dynamic tool registry entries are present. Registry-backed permission checks, model routing, project/conversation/memory context, structured output validation and audit/provenance are shared by the creative pipeline.
- **Customer Studio:** the workflow template includes the linked agent step and review gate. Typed API client methods cover workflow state, approvals, retry, cancellation, child attachment, media generation, render and memory interactions. Backend state remains authoritative; no frontend direct database path was added.
- **Secure artifact storage:** `project-assets` and `render-artifacts` buckets are private. Render downloads use the existing authorized/signed delivery path. The final render is registered as a project asset; preview and thumbnail sidecars remain linked to the render/run.
- **Migration hygiene:** 45 production migration records are applied and match 45 versioned SQL files in the repository. The two new production-run trigger migrations were renamed to the exact versions recorded by Supabase. All 13 checked orchestration/agent/media/render tables have RLS enabled; a direct FK/index audit returned zero missing FK indexes.
- **Personal-use mode:** no new billing, subscription, wallet or quota-pricing dependency was added. Gemini Developer API direct remains configured with `GEMINI_API_KEY`; no Vertex/ADC/service-account integration was introduced.

### Production deployment evidence

Existing production services only; no additional service or database was created:

| Service | Latest deployment | Status |
|---|---|---|
| `@graphytion/api` | `5cbf51e4-57c9-454e-bd77-e0cdce3a6751` | SUCCESS |
| `@graphytion/web` | `1a3e3ed3-e57e-4778-be99-6e041a2c3b96` | SUCCESS |
| `@graphytion/media-worker` | `bb6020ca-fcda-4c2e-92c7-485aeafb6677` | SUCCESS |
| `@graphytion/render-worker` | `59d052b0-a3ca-4492-ade7-6da23e394cea` | SUCCESS |

- Render Worker internal API base was aligned to `http://graphytionapi.railway.internal:8080/api/v1`; after correcting the prefix, API logs show render-worker `recover` and `claim` requests returning HTTP 200. Transient connection-refused errors occurred during worker/API restarts; the existing retry loops recovered and subsequent claims/heartbeats returned HTTP 200.
- Required environment-variable names were checked without exposing values. `GEMINI_API_KEY` is present on API and Media Worker; internal worker-token and API-base variables are present on the worker services.
- The repository has a `services/ai-worker` source directory, but the Railway project has no separate AI Worker service. The active creative worker remains embedded in the existing API process. No new Railway service was created, in accordance with the no-additional-service constraint.

### Remaining verification boundary / Phase 03 remains OPEN

- Customer Studio initiates child-job creation when a persisted step becomes ready; the orchestrator persists and validates readiness/completion, but it is not a hands-free background planner that invents media/TTS/subtitle/render payloads without a user action. This preserves explicit creative inputs and approval gates.
- No production run, media/audio job, timeline, render job, render sidecar or project asset existed at verification time (all corresponding row counts were zero). No synthetic rows were inserted.
- Per the explicit instruction, no Gemini generation, TTS generation or Remotion rendering was executed. Therefore no real MP4, preview or thumbnail artifact can be certified, and no end-to-end runtime acceptance claim is made.
- Build/deployment, schema, RLS, FK/index and worker/API connectivity checks are verified; actual media-to-MP4 artifact delivery remains unverified until a permitted real production run is performed.


## Superseding production status — 2026-11-28

This section supersedes earlier runtime statements above where they conflict with the current connected production evidence.

**Current source:** branch `main`, HEAD `a3def8e0e9efd6482f9ed24a50725a88ce43ba5a`.  
**Dispatcher implementation commit:** `8a962bbe233e6e8ca37e3c32e839b382b7e9d441`. Subsequent integration refinements include RLS-safe reconciliation/failure recording, TTS word-alignment subtitle timing, and Studio auto-completion of the approved creative gate.  
**CI:** workflow run `46049427514` completed SUCCESS on HEAD `a3def8e0e9efd6482f9ed24a50725a88ce43ba5a`; typecheck, web/admin build, Remotion bundle, migration SQL parse, Python compile/lint/import, worker import and FastAPI startup smoke all passed. Railway rebuilt and started that HEAD successfully.

### Persistent Orchestrator Dispatcher

| Area | Current status | Evidence |
|---|---|---|
| Embedded dispatcher lifecycle | IMPLEMENTED / DEPLOYED | `apps/api/app/workers/orchestrator.py` is started from the existing FastAPI lifespan; API startup log contains `production_orchestrator_dispatcher_started`. No new Railway service was created. |
| PostgreSQL DAG claim | IMPLEMENTED / MIGRATED | `private.graphytion_claim_production_step` uses `FOR UPDATE SKIP LOCKED`, dependency readiness, run state, worker identity, attempt count and lease. |
| Lease heartbeat / recovery | IMPLEMENTED / MIGRATED | `private.graphytion_heartbeat_production_step`; 120-second lease, 30-second heartbeat, expired lease reclaim and configured step timeout handling. |
| Versioned payload contract | IMPLEMENTED | Strict Pydantic envelope and per-step configuration models; persisted `payload_schema_version`, `payload_contract`, `input_fingerprint`. |
| Retry and cancellation | IMPLEMENTED | Persisted retry count, next retry, error class and backoff; cancellation of unattached DAG steps is reconciled with Production Run cancellation. |
| Audit / lineage | INTEGRATED | Claim, start, completion, child attachment, retry, timeout, recovery, cancellation and approval are represented in workflow events; child rows retain Production Run and parent-step references. |
| Media / TTS / subtitle / timeline / render handlers | IMPLEMENTED / INTEGRATED | Dispatcher creates and attaches idempotent media, audio and render jobs; subtitle track creation uses the existing revision helper and persisted TTS word alignment when available; timeline composes persisted media, voiceover and subtitle references. |
| Derived asset/audio/composition/QC/delivery steps | INTEGRATED | Existing `private.graphytion_sync_production_run` remains the deterministic artifact-reconciliation state machine. These nodes are not redundantly claimed by the dispatcher. |
| Agent Intelligence | INTEGRATED | Existing creative worker, five-agent registry and four-tool registry remain the agent execution path; dispatcher consumes the persisted agent task and enforces the creative approval gate. |
| MP4 private delivery | INTEGRATED, NOT RUNTIME-VERIFIED | Existing Render Worker, private `render-artifacts` bucket, render metadata, lineage and secure download path remain the final delivery path. No new render was run under the no-generation/no-render instruction. |

### Supabase production migration verification

Four additive migrations are applied to project `xtjwmezfzexvupbfsdqt`:

- `20261127180420_persistent_orchestrator_dispatcher.sql`
- `20261127180559_dispatch_only_executable_production_steps.sql`
- `20261127180718_dispatcher_timeout_reconciliation.sql`
- `20261127182523_orchestrator_privileged_reconciliation.sql`

Production history contains 49 migrations; all 49 versions have matching repository migration files. The new step lease/payload/retry columns are present, the four private worker functions for claim, heartbeat, active-run reconciliation and failure recording are SECURITY DEFINER with EXECUTE granted to `graphytion_api` and `graphytion_runtime`, and RLS remains enabled on `production_run_steps`.

The five-agent/four-tool registry is retained. Storage buckets `avatars`, `project-assets`, and `render-artifacts` are all private.

### Railway production verification

The existing four-service topology remains unchanged:

- API: deployment `e16b1dfa-293a-4016-b291-5e36ac1b0757` — SUCCESS.
- Media Worker: deployment `66e095a8-b026-4d41-a009-ec9b178fcd7f` — SUCCESS.
- Web: deployment `cf6ad943-827e-47eb-8d54-aefd0fe81284` — SUCCESS.
- Render Worker: deployment `59d052b0-a3ca-4492-ade7-6da23e394cea` — SUCCESS.

API startup logs confirm both the creative worker and production orchestrator started. API healthcheck passed. Media Worker logs show successful internal API job-claim, recovery and heartbeat calls. Render Worker startup and render-job claim endpoint are operational. The API and Media Worker environment variable name lists include `GEMINI_API_KEY`; secret values are not exposed by the connected Railway account.

There is no separate AI Worker service in the existing Railway project. Agent execution remains on the existing embedded creative worker in API; the new dispatcher is embedded in that same API process. No service or queue was added.

### Explicit verification boundary

Production data counts at this inspection were zero for production runs, run steps, agent tasks, media jobs, audio generations, subtitle tracks, timelines, render jobs, render artifacts and project assets. The three private storage buckets contain no objects. This is consistent with the instruction not to execute generation or rendering.

Therefore the dispatcher code, database contracts, migration, build and service startup are verified, but a live DAG claim against an actual Production Run, real Gemini/TTS execution, completed Remotion render and actual MP4 download remain unverified by design. Phase 03 stays OPEN until a separately authorized production acceptance run can verify those external operations and the resulting artifact.
