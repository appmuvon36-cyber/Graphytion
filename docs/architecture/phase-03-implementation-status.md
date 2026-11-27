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
