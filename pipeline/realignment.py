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
    if target_seconds <= 0 or not shutil.which("ffprobe"):
        return audio_path

    try:
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
            check=True, capture_output=True, text=True,
        )
        duration_str = probe.stdout.strip()
        if not duration_str or duration_str == "N/A":
            return audio_path
        source_seconds = float(duration_str)
    except Exception:
        return audio_path

    if source_seconds <= 0:
        return audio_path
    factor = source_seconds / target_seconds
    if 0.98 <= factor <= 1.02:
        return audio_path

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-i", audio_path, "-filter:a", _atempo_chain(factor), output_path], check=True, capture_output=True)
    return output_path
