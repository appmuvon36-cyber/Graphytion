# Graphytion Media Worker

Provider-backed asynchronous image, video and voice-over generation. PostgreSQL is the durable job queue. The worker polls authenticated FastAPI claim endpoints, acquires transactional leases, generates images with Gemini 3.1 Flash Image and short videos with Gemini Omni Flash through the Interactions API, synthesizes MP3 through Gemini/OpenAI TTS adapters, and uploads validated artifacts through FastAPI to private Supabase Storage. Heartbeats extend active leases and a recovery scan reclaims expired leases. No external queue broker is required. No audio is fabricated when provider credentials are absent.

Build from repository root: `docker build -f services/media-worker/Dockerfile -t graphytion-media-worker .`

Required runtime values are listed in `.env.example`; supply them only in the deployment secret manager during the deployment phase.


Image generation uses `GEMINI_IMAGE_MODEL` (default `gemini-3.1-flash-image`). Video generation uses `GEMINI_VIDEO_MODEL` (default `gemini-omni-1.2-flash`) through the `v1beta/interactions` API. Provider output is validated by MIME and file signature before it is accepted. Provider cost is explicitly recorded as unpriced unless the provider returns token usage that can be reconciled against a configured model price book; the worker never invents a cost.

The Media Worker also claims the durable `media_generation_jobs` queue and continues to service existing voice-over jobs. It does not create a separate image/video worker.
