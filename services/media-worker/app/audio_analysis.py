from __future__ import annotations

import json
import subprocess
import tempfile
from array import array
from pathlib import Path
from typing import Any


def analyze_audio_bytes(content: bytes) -> tuple[dict[str, Any], bytes]:
    """Extract real media metadata and 50ms peak waveform bins using ffprobe/ffmpeg."""
    if not content:
        raise ValueError("AUDIO_ANALYSIS_EMPTY_INPUT")
    with tempfile.TemporaryDirectory(prefix="graphytion-audio-") as directory:
        source = Path(directory) / "source-audio"
        source.write_bytes(content)
        probe = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "format=duration,bit_rate:stream=codec_name,codec_type,sample_rate,channels,bit_rate",
                "-of", "json", str(source),
            ],
            check=True, capture_output=True, text=True, timeout=60,
        )
        parsed = json.loads(probe.stdout)
        audio_stream = next((item for item in parsed.get("streams", []) if item.get("codec_type") == "audio"), None)
        if not audio_stream:
            raise ValueError("AUDIO_ANALYSIS_NO_AUDIO_STREAM")
        duration = float(parsed.get("format", {}).get("duration") or 0)
        if duration <= 0 or duration > 1800:
            raise ValueError("AUDIO_ANALYSIS_UNSUPPORTED_DURATION")
        decoded = subprocess.run(
            ["ffmpeg", "-v", "error", "-i", str(source), "-vn", "-ac", "1", "-ar", "44100", "-f", "f32le", "pipe:1"],
            check=True, capture_output=True, timeout=180,
        )
        samples = array("f")
        samples.frombytes(decoded.stdout[: len(decoded.stdout) - (len(decoded.stdout) % samples.itemsize)])
        if not samples:
            raise ValueError("AUDIO_ANALYSIS_NO_DECODED_SAMPLES")
        samples_per_bin = 2205  # 50 ms at 44.1 kHz
        peaks = [
            round(max(abs(value) for value in samples[index:index + samples_per_bin]), 6)
            for index in range(0, len(samples), samples_per_bin)
        ]
        metadata = {
            "duration_ms": round(duration * 1000),
            "codec": audio_stream.get("codec_name"),
            "sample_rate_hz": int(audio_stream.get("sample_rate") or 0),
            "channels": int(audio_stream.get("channels") or 0),
            "bitrate_bps": int(audio_stream.get("bit_rate") or parsed.get("format", {}).get("bit_rate") or 0),
            "container_bitrate_bps": int(parsed.get("format", {}).get("bit_rate") or 0),
            "waveform": {"sample_rate_hz": 20, "bucket_ms": 50, "peaks": peaks},
        }
        waveform = json.dumps(metadata["waveform"], separators=(",", ":")).encode("utf-8")
        metadata.pop("waveform")
        return metadata, waveform
