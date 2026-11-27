# Graphytion Remotion Phase 03

## Runtime contract

CompositionSnapshot v2 (compositionVersion=2.0.0) is the only editable/renderable timeline format. It contains frame-based tracks, clips, allowlisted component IDs and versions, transitions, keyframes and stable project asset UUID references. Binary media and signed URLs are never persisted in the snapshot.

packages/motion-components is the compiled component registry and shared Remotion composition. Both the Customer preview player and the dedicated Node render worker render TimelineComposition with the same snapshot and asset-resolution map. A render job pins the exact snapshot JSON, SHA-256 hash, schema version, asset manifest and render-profile version. Later editor changes cannot mutate a queued render.

## Component registry

The registry contains versioned title-card, image, video, shape, typography, chart, audio and subtitle components. FastAPI validates props, track compatibility, frame ranges, transition/keyframe schemas and the enabled registry version before save or render. Platform Admin can disable a component; user-supplied component code is never evaluated.

## Timeline and media APIs

- GET /projects/{project_id}/timeline: latest saved snapshot and fresh signed asset URLs.
- PUT /projects/{project_id}/timeline: immutable version save with optimistic expected_version.
- GET /projects/{project_id}/timelines: version history.
- GET /projects/{project_id}/timelines/{timeline_id}: restore source snapshot and fresh signed URLs.
- POST /projects/{project_id}/voiceovers: provider-backed TTS job; returns provider_unavailable without configured credentials and does not fabricate media.
- GET/POST/PUT /projects/{project_id}/subtitles: subtitle track/segment lifecycle, SRT and WebVTT import/export.

Project assets are authorized by FastAPI against project and workspace ownership. Supported media types are checked by MIME and signature. SVG files are sanitized before storage. Signed URLs are created on preview or worker claim, never stored as permanent asset identity.

## Render profiles

The migration seeds Draft Preview, Standard, High Quality, Full HD and 4K global profiles. Platform Admin can create, version and archive profiles. Each render job pins profile settings and enforces that output dimensions and FPS match the immutable snapshot. MP4 uses H.264/H.265 and AAC/no audio; WebM uses VP8/VP9 and Opus/no audio.

## Worker lifecycle

PostgreSQL render/audio job rows are both the durable queue and source of truth. Workers poll authenticated FastAPI claim endpoints backed by `FOR UPDATE SKIP LOCKED`, heartbeat leases, recover expired jobs, report progress, validate output with ffprobe and upload artifacts through authenticated FastAPI endpoints. Voice-over generation runs in the separate media worker; FastAPI writes generated MP3 files into private project storage and creates project-asset metadata. Both workers support retry/recovery without client-side database access.

## Deployment-only configuration

The following values are intentionally not configured in this phase:
- FastAPI INTERNAL_WORKER_TOKEN, Supabase server credentials, and optional private REDIS_URL for transient worker wake-up signals.
- Render worker GRAPHYTION_API_BASE_URL, INTERNAL_WORKER_TOKEN, private REDIS_URL, optional REMOTION_BROWSER_EXECUTABLE.
- Media worker GRAPHYTION_API_BASE_URL, INTERNAL_WORKER_TOKEN, GEMINI_API_KEY and optional GEMINI_TTS_MODEL (default `gemini-3.8-flash-tts`); OPENAI_API_KEY remains optional for Whisper word alignment and OpenAI fallback TTS.

Apply the new migration only during the separately authorized deployment/database rollout. No migration, secret update, Railway change or deployment was performed as part of this implementation.


## Snapshot identity and editor asset resolution

- The Customer Studio preview and Node render worker both use the registered `GraphytionTimeline` composition from `@graphytion/motion-components`. The title-only demo composition is not registered.
- Render MP4 must be submitted from the current editor snapshot through `POST /projects/{project_id}/renders`. The compatibility storyboard-render endpoint also requires the caller to submit that exact snapshot; it does not reconstruct clips from storyboard scene metadata.
- `PUT /projects/{project_id}/timeline` returns a new short-lived `resolved_assets` map after validating project ownership. The client replaces its preview resolver map with that response. Signed URLs remain transient and are not written into the immutable snapshot.
- Interactive preview displays an explicit missing-media placeholder when an asset URL is not resolved. The render API continues to reject missing, foreign-project, or unavailable asset references before queuing a render.
- Timeline Editor exposes clip-level trim/playback rate, transition-in/out, paired crossfade, crop geometry, and keyframe controls. Crossfade pairing adjusts the next clip start to create the required exact overlap.


## Runtime database credential separation

Keep the existing `DATABASE_URL` unchanged if it is the administrative/migration connection. FastAPI now prioritizes `GRAPHYTION_RUNTIME_DATABASE_URL` for its SQLAlchemy engine. Configure this new server-only variable on the Railway API service with a URL for the dedicated `graphytion_api` login, using the Graphytion direct database host or project-scoped Supavisor endpoint and TLS. Do not use the `postgres` login for the API runtime: it has BYPASSRLS and elevated role-management privileges. The role `graphytion_api` must be granted LOGIN and a unique password out-of-band; never commit or send the password through source control.

## Redis capacity fallback

Redis is an optional queue wake-up accelerator; PostgreSQL remains the durable job source of truth. If Railway cannot provision a Redis service because of workspace resource limits, leave `REDIS_URL` empty on API, Media Worker, and Render Worker. Both workers fall back to PostgreSQL polling and lease recovery. Do not set a reference to a Redis service that is absent from the environment.

## Global render controls

The Super Admin `/admin` control plane manages the singleton `platform_render_settings` record. Settings are audited and validated server-side. Render claims serialize the capacity check with a PostgreSQL advisory transaction lock and call `private.graphytion_render_runtime_capacity()` to enforce the concurrency cap and lease. The global artifact limit is bounded by the current 512 MiB API upload cap.


## Worker presence and Admin visibility

Media Worker and Render Worker send authenticated presence to `POST /api/v1/internal/workers/heartbeat` every 30 seconds using `INTERNAL_WORKER_TOKEN`. The worker registry is private in PostgreSQL; only the server-authorized Admin endpoint reads it. Admin marks a worker stale after 90 seconds without a heartbeat. A missing heartbeat is not reported as a running worker.


## First platform administrator bootstrap

The initial Supabase production project currently has no Auth users or platform-admin rows. After the owner creates and confirms the first Graphytion account through the normal signup flow, run the following once in the Supabase SQL Editor, replacing the email with the confirmed account email:

```sql
insert into public.platform_admins(user_id, role, status, reason)
select id, 'super_admin', 'active', 'Initial Graphytion platform administrator bootstrap'
from auth.users
where lower(email)=lower('<YOUR_CONFIRMED_SIGNUP_EMAIL>')
  and email_confirmed_at is not null
on conflict (user_id) do update
set role='super_admin', status='active', revoked_at=null,
    reason='Initial Graphytion platform administrator bootstrap';
```

This is a one-time owner action; do not expose a public self-service admin promotion endpoint.

## Invitation email activation

Set `RESEND_API_KEY` and `INVITATION_FROM_EMAIL` on the API service only after the sender domain is verified in Resend. Until both are configured, invitation creation returns a provider-configuration error and does not expose the raw invitation token to Admin or Customer clients.


## Recent render correctness hardening

- The API rejects unpaired crossfade metadata before persisting a timeline or accepting a render request. The browser Player and render bundle use the same registered transition implementation.
- Audio clips receive transition-derived fade-in/fade-out frame values from the immutable timeline snapshot; this is a real volume envelope, not a visual opacity effect.
- Worker retries use the database-persisted `max_attempts` budget, including bounded timeout retries. PostgreSQL remains authoritative for the attempt count.
- Final output metadata is checked with ffprobe before thumbnail upload. Preview renditions are independently checked for MP4/H.264, expected half-resolution even dimensions, and duration within one frame before the API persists the sidecar.
- These code changes do not apply database migrations or deploy Railway services. A real render remains blocked until FastAPI is healthy with the dedicated runtime database role and required migrations are applied through the authorized production procedure.


## Railway private API connectivity (2026-11-27)

The FastAPI container binds to `PORT` and defaults to 8080 to match the Railway healthcheck. Keep the API private; workers must use the Railway private endpoint and include the versioned API prefix:

```text
GRAPHYTION_API_BASE_URL=http://graphytionapi.railway.internal:8080/api/v1
```

Do not use port 8000 or omit `/api/v1`. The worker client appends relative paths such as `internal/workers/heartbeat` and `internal/render-jobs/claim` to this base URL.

If worker claims return 200 but heartbeat returns 500 with PostgreSQL `AmbiguousColumnError: column reference "worker_id" is ambiguous`, verify migration `20261127022404_worker_heartbeat_conflict_target_fix` is applied. It changes the upsert conflict target to the named `worker_heartbeats_pkey` constraint. Confirm both worker types appear as `online` in `public.worker_heartbeats` and inspect API logs for HTTP 200 on heartbeat and recovery calls.


## Personal render delivery and Asset Library integration

- Render jobs are personal-use operations: no quota reservation, debit, reconciliation, or billing dependency is executed by the render API. Keep existing legacy economics tables intact for compatibility; do not create pricing records for personal rendering.
- The validated final output is stored once in the private `render-artifacts` bucket and registered as a generated `project_assets` row that references that same bucket/object path. The normal Asset Library signed preview/download path serves it without duplicating the file into `project-assets`.
- The generated asset metadata records the render job ID, timeline hash and composition version. Asset deletion refuses to remove an output still referenced by a completed render job.
- This is implemented in source; no real render was run and no claim of MP4 runtime completion is made until worker output is actually produced and validated.
