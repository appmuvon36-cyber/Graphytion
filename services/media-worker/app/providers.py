from __future__ import annotations

import base64
import re
import subprocess
from typing import Any, Protocol

import httpx


class TTSProvider(Protocol):
    def configured(self) -> bool: ...

    async def synthesize(
        self, *, text: str, voice: str, model: str, language: str = "id-ID"
    ) -> tuple[bytes, str]: ...

    async def align_words(
        self, *, audio: bytes, filename: str = "voiceover.mp3"
    ) -> dict[str, Any]: ...


class OpenAITTSProvider:
    key = "openai"
    VOICES = {"alloy", "ash", "coral", "echo", "fable", "onyx", "nova", "sage", "shimmer", "verse"}

    def __init__(self, api_key: str):
        self.api_key = api_key

    def configured(self) -> bool:
        return bool(self.api_key)

    async def synthesize(
        self, *, text: str, voice: str, model: str, language: str = "id-ID"
    ) -> tuple[bytes, str]:
        if voice not in self.VOICES:
            raise ValueError("TTS_VOICE_UNSUPPORTED")
        if not self.api_key:
            raise RuntimeError("TTS_PROVIDER_NOT_CONFIGURED")
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/speech",
                headers={"Authorization": "Bearer " + self.api_key},
                json={"model": model, "voice": voice, "input": text, "response_format": "mp3"},
            )
            response.raise_for_status()
            audio = response.content
        if not (audio.startswith(b"ID3") or (len(audio) > 1 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0)):
            raise RuntimeError("TTS_OUTPUT_INVALID")
        return audio, "audio/mpeg"

    async def align_words(self, *, audio: bytes, filename: str = "voiceover.mp3") -> dict[str, Any]:
        if not self.api_key:
            return {"status": "unavailable", "provider": self.key, "reason": "provider_not_configured", "words": []}
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client:
            response = await client.post(
                "https://api.openai.com/v1/audio/transcriptions",
                headers={"Authorization": "Bearer " + self.api_key},
                data={"model": "whisper-1", "response_format": "verbose_json", "timestamp_granularities[]": "word"},
                files={"file": (filename, audio, "audio/mpeg")},
            )
            if response.status_code >= 400:
                return {"status": "unavailable", "provider": self.key, "reason": "word_timestamp_provider_unavailable", "http_status": response.status_code, "words": []}
            payload = response.json()
        words = []
        for item in payload.get("words", []):
            start, end, word = item.get("start"), item.get("end"), item.get("word")
            if isinstance(start, (int, float)) and isinstance(end, (int, float)) and 0 <= start < end and isinstance(word, str) and word.strip():
                words.append({"text": word, "start_ms": round(start * 1000), "end_ms": round(end * 1000), "provider": "openai/whisper-1"})
        if not words:
            return {"status": "unavailable", "provider": self.key, "reason": "provider_returned_no_word_timestamps", "words": []}
        return {"status": "available", "provider": self.key, "model": "whisper-1", "words": words}


class GeminiTTSProvider:
    key = "gemini"
    VOICES = {
        "Kore", "Puck", "Charon", "Fenrir", "Aoede", "Leda", "Orus", "Zephyr",
        "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
        "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
        "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
        "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
    }

    def __init__(self, api_key: str):
        self.api_key = api_key

    def configured(self) -> bool:
        return bool(self.api_key)

    async def synthesize(
        self, *, text: str, voice: str, model: str, language: str = "id-ID"
    ) -> tuple[bytes, str]:
        if voice not in self.VOICES:
            raise ValueError("GEMINI_TTS_VOICE_UNSUPPORTED")
        if not self.api_key:
            raise RuntimeError("TTS_PROVIDER_NOT_CONFIGURED")
        if not re.fullmatch(r"[a-zA-Z0-9._-]{3,100}", model):
            raise ValueError("GEMINI_TTS_MODEL_INVALID")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
        payload = {
            "contents": [{"parts": [{"text": text}]}],
            "generationConfig": {
                "responseModalities": ["AUDIO"],
                "speechConfig": {
                    "languageCode": language,
                    "voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice}},
                },
            },
        }
        async with httpx.AsyncClient(timeout=httpx.Timeout(180, connect=15)) as client:
            response = await client.post(url, headers={"x-goog-api-key": self.api_key}, json=payload)
            response.raise_for_status()
            body = response.json()
        parts = body.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        audio_part = next(
            (part for part in parts if isinstance(part.get("inlineData", {}).get("data"), str)),
            None,
        )
        if audio_part is None:
            raise RuntimeError("GEMINI_TTS_AUDIO_MISSING")
        inline = audio_part["inlineData"]
        pcm = base64.b64decode(inline["data"], validate=True)
        mime = inline.get("mimeType", "audio/L16;codec=pcm;rate=24000")
        rate_match = re.search(r"rate=(\\d+)", mime)
        channel_match = re.search(r"channels=(\\d+)", mime)
        sample_rate = int(rate_match.group(1)) if rate_match else 24000
        channels = int(channel_match.group(1)) if channel_match else 1
        if not pcm or sample_rate < 8000 or sample_rate > 96000 or channels not in (1, 2):
            raise RuntimeError("GEMINI_TTS_PCM_INVALID")
        result = subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-f", "s16le",
                "-ar", str(sample_rate), "-ac", str(channels), "-i", "pipe:0",
                "-codec:a", "libmp3lame", "-b:a", "192k", "-f", "mp3", "pipe:1",
            ],
            input=pcm, capture_output=True, check=True, timeout=120,
        )
        audio = result.stdout
        if not (audio.startswith(b"ID3") or (len(audio) > 1 and audio[0] == 0xFF and audio[1] & 0xE0 == 0xE0)):
            raise RuntimeError("GEMINI_TTS_MP3_CONVERSION_INVALID")
        return audio, "audio/mpeg"

    async def align_words(self, *, audio: bytes, filename: str = "voiceover.mp3") -> dict[str, Any]:
        # Gemini TTS returns audio, not word timestamps. Never fabricate alignment.
        return {
            "status": "unavailable",
            "provider": self.key,
            "reason": "gemini_tts_does_not_return_word_level_timestamps",
            "words": [],
        }
