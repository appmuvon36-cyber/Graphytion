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
