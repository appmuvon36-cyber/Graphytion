# Graphytion Media Worker

Provider-backed asynchronous voice-over generation. PostgreSQL is the durable job queue; Redis Streams are wake-up signals. The worker claims leased jobs through FastAPI, synthesizes MP3 through the provider adapter, and uploads artifacts through FastAPI to private Supabase Storage. A recovery scan requeues expired leases. No audio is fabricated when provider credentials are absent.

Build from repository root: `docker build -f services/media-worker/Dockerfile -t graphytion-media-worker .`

Required runtime values are listed in `.env.example`; supply them only in the deployment secret manager during the deployment phase.
