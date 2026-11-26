# Graphytion Remotion Runtime

## Runtime topology
- Customer Studio preview uses the shared `GraphytionTimelinePlayer` component.
- FastAPI authorizes workspace access, compiles/validates and hashes immutable timeline snapshots, persists render jobs, and emits Redis Stream notifications.
- Supabase PostgreSQL is the durable job source of truth; Redis is transport/coordination only.
- The dedicated Node.js worker claims jobs through authenticated FastAPI endpoints, renders the same `GraphytionTimeline` composition, validates MP4 metadata with ffprobe, and uploads through FastAPI to private Supabase Storage.
- Admin operations remain in the platform control plane. Worker credentials and Supabase service credentials never enter browser code.

## Pinned engine
The workspace pins `remotion`, `@remotion/player`, `@remotion/renderer`, and `@remotion/cli` to `4.0.409`. Keep all Remotion packages on the same exact version and commit the pnpm lockfile with every version change.

## Build and runtime
Build the render-worker image from repository root using `services/render-worker/Dockerfile`. It installs the render-worker and Remotion Studio dependency graphs with the committed lockfile, then bundles `apps/remotion-studio/src/index.ts` at image build time. The worker uses the immutable local bundle at `/workspace/apps/remotion-studio/build`; a separately deployed Remotion Studio URL is not required.

Required runtime environment: `GRAPHYTION_API_BASE_URL` (FastAPI base including `/api/v1`), `INTERNAL_WORKER_TOKEN` (high-entropy secret shared with FastAPI), `REDIS_URL` (TLS `rediss://` in production), and `REMOTION_SERVE_URL` (normally `/workspace/apps/remotion-studio/build`). Optional `REMOTION_RENDER_CONCURRENCY` (1–8, default 2), `REMOTION_RENDER_CRF` (0–51, default 18), `REMOTION_X264_PRESET` (ultrafast through veryslow, default medium), `REMOTION_BROWSER_EXECUTABLE`, and `RENDER_TIMEOUT_MS` (60 seconds–24 hours, default 2 hours).

Keep credentials in the worker runtime secret manager, not this file or the image. Scale concurrency and worker replicas only after memory/CPU and Remotion licensing have been assessed.

## Timeline and output contract
Browser preview and MP4 rendering consume the same versioned snapshot with integer frame positions, FPS, dimensions, duration, allowlisted component keys and validated props. Model/user output must never select arbitrary imports, JSX, JavaScript, or executable code. Worker completion requires ffprobe to confirm MP4, H.264, expected dimensions, and duration within one frame. FastAPI independently checks the MP4 signature, size limit, worker lease, SHA-256, ownership, and private storage upload before marking a job completed.

## Operational boundary
This code change does not apply Supabase migrations, modify Railway/Vercel secrets, deploy services, or start production workers. Existing render-job/storage migrations must be applied under the production database change procedure before these endpoints can operate.
