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

Redis Streams are wake-up signals only. PostgreSQL render/audio job rows and leases are authoritative. Render workers claim with FOR UPDATE SKIP LOCKED, heartbeat leases, report progress, validate output with ffprobe and upload artifacts through authenticated FastAPI endpoints. Voice-over generation runs in the separate media worker; FastAPI writes generated MP3 files into private project storage and creates project-asset metadata. Both workers support retry/recovery without client-side database access.

## Deployment-only configuration

The following values are intentionally not configured in this phase:
- FastAPI INTERNAL_WORKER_TOKEN, Supabase service credentials and Redis TLS URL.
- Render worker GRAPHYTION_API_BASE_URL, INTERNAL_WORKER_TOKEN, REDIS_URL, optional REMOTION_BROWSER_EXECUTABLE.
- Media worker GRAPHYTION_API_BASE_URL, INTERNAL_WORKER_TOKEN, REDIS_URL, OPENAI_API_KEY, optional OPENAI_TTS_MODEL.

Apply the new migration only during the separately authorized deployment/database rollout. No migration, secret update, Railway change or deployment was performed as part of this implementation.
