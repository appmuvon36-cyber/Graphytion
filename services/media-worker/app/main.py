from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import socket
import uuid

import httpx
from redis.asyncio import Redis

from app.audio_analysis import analyze_audio_bytes
from app.providers import GeminiTTSProvider, OpenAITTSProvider

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("graphytion.media-worker")
API_BASE = os.environ.get("GRAPHYTION_API_BASE_URL", "").rstrip("/")
TOKEN = os.environ.get("INTERNAL_WORKER_TOKEN", "")
WORKER_ID = f"{socket.gethostname()}-{uuid.uuid4().hex[:10]}"
POLL_INTERVAL_SECONDS = max(1, int(os.environ.get("WORKER_POLL_INTERVAL_SECONDS", "3")))


class Worker:
    def __init__(self) -> None:
        if not API_BASE or not TOKEN:
            raise RuntimeError("GRAPHYTION_API_BASE_URL and INTERNAL_WORKER_TOKEN are required")
        self.http = httpx.AsyncClient(
            base_url=API_BASE,
            headers={"Authorization": "Bearer " + TOKEN},
            timeout=httpx.Timeout(180, connect=15),
        )
        redis_url = os.environ.get("REDIS_URL")
        self.redis = Redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=1, socket_timeout=POLL_INTERVAL_SECONDS + 1) if redis_url else None
        self.stop = asyncio.Event()

    async def api(self, path: str, **kwargs):
        response = await self.http.request(kwargs.pop("method", "GET"), path.lstrip("/"), **kwargs)
        response.raise_for_status()
        body = response.json()
        return body.get("data", body)

    async def heartbeat(self, generation_id: str) -> None:
        while True:
            await asyncio.sleep(60)
            await self.api(
                f"/internal/media-jobs/{generation_id}/heartbeat",
                method="POST",
                params={"worker_id": WORKER_ID},
            )

    async def fail(self, generation_id: str, code: str, retryable: bool) -> None:
        try:
            await self.api(
                f"/internal/media-jobs/{generation_id}/failed",
                method="POST",
                params={"worker_id": WORKER_ID},
                json={"error_code": code, "retryable": retryable},
            )
        except Exception:
            log.exception("media_job_failure_callback_failed", extra={"generation_id": generation_id})

    async def process(self) -> bool:
        try:
            job = await self.api(
                "/internal/media-jobs/claim",
                method="POST",
                params={"worker_id": WORKER_ID},
            )
        except Exception:
            log.exception("media_job_claim_failed")
            return False
        if not job:
            return False

        job_id = job["id"]
        provider_key = job.get("provider_key", "openai")
        if provider_key == "gemini":
            provider = GeminiTTSProvider(os.environ.get("GEMINI_API_KEY", ""))
            model_default = os.environ.get("GEMINI_TTS_MODEL", "gemini-3.8-flash-lite-tts")
        elif provider_key == "openai":
            provider = OpenAITTSProvider(os.environ.get("OPENAI_API_KEY", ""))
            model_default = os.environ.get("OPENAI_TTS_MODEL", "tts-1")
        else:
            await self.fail(job_id, "TTS_PROVIDER_UNSUPPORTED", False)
            return True
        if not provider.configured():
            await self.fail(job_id, "TTS_PROVIDER_NOT_CONFIGURED", False)
            return True

        heartbeat_task = asyncio.create_task(self.heartbeat(job_id))
        try:
            audio, mime = await provider.synthesize(
                text=job["input_text"],
                voice=job["voice_key"],
                model=job.get("model_key") or model_default,
                language=job.get("language") or "id-ID",
                style=(job.get("generation_config") or {}).get("style"),
            )
            try:
                alignment = await provider.align_words(audio=audio)
            except Exception:
                log.exception("word_alignment_unavailable", extra={"generation_id": job_id})
                alignment = {
                    "status": "unavailable",
                    "provider": provider_key,
                    "reason": "alignment_adapter_failed",
                    "words": [],
                }
            metadata, waveform = await asyncio.to_thread(analyze_audio_bytes, audio)
            await self.api(
                f"/internal/media-jobs/{job_id}/artifact",
                method="POST",
                params={"worker_id": WORKER_ID},
                data={
                    "alignment_json": json.dumps(alignment),
                    "media_metadata": json.dumps(metadata),
                },
                files={
                    "file": ("voiceover.mp3", audio, mime),
                    "waveform_file": ("waveform.json", waveform, "application/json"),
                },
                timeout=httpx.Timeout(240, connect=15),
            )
            log.info("voiceover_completed", extra={"generation_id": job_id, "bytes": len(audio)})
        except httpx.HTTPStatusError as exc:
            status_code = exc.response.status_code
            retryable = status_code in {408, 425, 429} or status_code >= 500
            if retryable:
                retry_after = exc.response.headers.get("retry-after")
                try:
                    delay = float(retry_after) if retry_after else 2 ** min(max(int(job.get("attempt_count", 1)) - 1, 0), 5)
                except (TypeError, ValueError):
                    delay = 2 ** min(max(int(job.get("attempt_count", 1)) - 1, 0), 5)
                await asyncio.sleep(max(1, min(delay, 60)))
            await self.fail(
                job_id, f"TTS_PROVIDER_HTTP_{status_code}", retryable
            )
        except (httpx.TimeoutException, httpx.TransportError):
            await self.fail(job_id, "TTS_PROVIDER_NETWORK_ERROR", True)
        except ValueError as exc:
            await self.fail(job_id, str(exc) or "TTS_INVALID_REQUEST", False)
        except Exception:
            log.exception("voiceover_generation_failed", extra={"generation_id": job_id})
            await self.fail(job_id, "TTS_GENERATION_FAILED", True)
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            except Exception:
                log.exception("media_heartbeat_stopped")
        return True

    async def presence_heartbeat(self) -> None:
        while not self.stop.is_set():
            try:
                await self.api(
                    "/internal/workers/heartbeat",
                    method="POST",
                    json={
                        "worker_id": WORKER_ID,
                        "worker_type": "media",
                        "hostname": socket.gethostname(),
                        "version": os.environ.get("RAILWAY_DEPLOYMENT_ID", "unknown"),
                        "metadata": {"providers": ["gemini", "openai"]},
                    },
                )
            except Exception:
                log.warning("media_worker_heartbeat_unavailable", exc_info=True)
            try:
                await asyncio.wait_for(self.stop.wait(), timeout=30)
            except TimeoutError:
                pass

    async def run(self) -> None:
        log.info("media_worker_started", extra={"worker_id": WORKER_ID, "queue": "postgresql+redis-wakeup"})
        presence_task = asyncio.create_task(self.presence_heartbeat())
        last_recovery = 0.0
        try:
            while not self.stop.is_set():
                processed = await self.process()
                now = asyncio.get_running_loop().time()
                if now - last_recovery >= 30:
                    last_recovery = now
                    try:
                        await self.api("/internal/media-jobs/recover", method="POST")
                    except Exception:
                        log.exception("media_job_recovery_failed")
                if not processed:
                    await self.wait_for_work()
        finally:
            self.stop.set()
            presence_task.cancel()
            try:
                await presence_task
            except asyncio.CancelledError:
                pass

    async def wait_for_work(self) -> None:
        if self.redis is not None:
            try:
                await self.redis.blpop("graphytion:media:jobs", timeout=POLL_INTERVAL_SECONDS)
                return
            except Exception:
                log.warning("redis_media_queue_unavailable_falling_back_to_postgres_poll")
        try:
            await asyncio.wait_for(self.stop.wait(), timeout=POLL_INTERVAL_SECONDS)
        except TimeoutError:
            pass

    async def close(self) -> None:
        await self.http.aclose()
        if self.redis is not None:
            await self.redis.aclose()


async def main() -> None:
    worker = Worker()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, worker.stop.set)
    try:
        await worker.run()
    finally:
        await worker.close()


if __name__ == "__main__":
    asyncio.run(main())
