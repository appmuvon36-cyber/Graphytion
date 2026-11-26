# Graphytion Media Worker

Provider-backed asynchronous voice-over generation. PostgreSQL is the durable job queue. The worker polls the authenticated FastAPI claim endpoint, acquires a transactional lease, synthesizes MP3 through the provider adapter, and uploads artifacts through FastAPI to private Supabase Storage. Heartbeats extend active leases and a recovery scan reclaims expired leases. No external queue broker is required. No audio is fabricated when provider credentials are absent.

Build from repository root: `docker build -f services/media-worker/Dockerfile -t graphytion-media-worker .`

Required runtime values are listed in `.env.example`; supply them only in the deployment secret manager during the deployment phase.
