# Graphytion Media Worker

Provider-backed image, video and voice-over generation on the existing Media Worker. PostgreSQL is the durable job queue; workers claim jobs through authenticated FastAPI endpoints, use transactional leases and heartbeats, and upload validated artifacts through FastAPI to private Supabase Storage. No additional worker, queue, or provider runtime is introduced.

Build from repository root: `docker build -f services/media-worker/Dockerfile -t graphytion-media-worker .`

## Image and video generation

Both image and video generation use the **Gemini Developer API** and the same server-side `GEMINI_API_KEY` secret. The worker sends the key only in the `x-goog-api-key` request header; it is never returned to the browser or logged.

- Image: `gemini-3.1-flash-image` through `POST https://generativelanguage.googleapis.com/v1beta/models/gemini-3.1-flash-image:generateContent`, using `generationConfig.imageConfig` for aspect ratio and image size.
- Video: `gemini-omni-1.2-flash` through `POST https://generativelanguage.googleapis.com/v1beta/interactions`. Video jobs use background execution, persist the returned interaction ID, poll `GET /v1beta/interactions/{id}`, and request cancellation through `POST /v1beta/interactions/{id}/cancel` when cancellation is requested.
- Video output is accepted only when the provider returns inline base64 MP4 data. Google Cloud Storage URIs are not fetched by this worker.

Provider output is validated by MIME type and file signature before FastAPI stores it as a private project asset. Provider usage and cost remain explicitly unpriced unless verifiable usage and a matching active price-book entry are available. The worker never invents usage or cost.

## Runtime configuration

Required for worker startup: `GRAPHYTION_API_BASE_URL`, `INTERNAL_WORKER_TOKEN`, and `GEMINI_API_KEY`. Optional variables for the existing voice-over pipeline are documented in `.env.example`. No Google Cloud Project, Service Account, ADC, Vertex AI, or Agent Platform credentials are required.

The worker continues to service existing TTS jobs and media generation jobs from the same durable PostgreSQL queue.
