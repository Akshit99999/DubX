"""Audio duration fitting helpers."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def _atempo_chain(factor: float) -> str:
    factor = max(0.85, min(1.18, factor))
    filters: list[str] = []
    while factor < 0.5:
        filters.append("atempo=0.5")
        factor /= 0.5
    while factor > 2.0:
        filters.append("atempo=2.0")
        factor /= 2.0
    filters.append(f"atempo={factor:.5f}")
    return ",".join(filters)


def fit_audio_to_duration(audio_path: str, target_seconds: float, output_path: str) -> str:
    """Time-stretch audio with FFmpeg, clamped to the spec's 0.85–1.18 range."""

    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg is required for audio realignment but was not found on PATH")
    if target_seconds <= 0:
        return audio_path
    # Probe duration using ffprobe when available; otherwise leave the input unchanged.
    if not shutil.which("ffprobe"):
        return audio_path
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
        check=True, capture_output=True, text=True,
    )
    source_seconds = float(probe.stdout.strip())
    if source_seconds <= 0:
        return audio_path
    factor = source_seconds / target_seconds
    subprocess.run(["ffmpeg", "-y", "-i", audio_path, "-filter:a", _atempo_chain(factor), output_path], check=True, capture_output=True)
    return output_path
