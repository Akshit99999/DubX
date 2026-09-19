"""FFmpeg extraction and optional Demucs stem separation."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def require_ffmpeg() -> None:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg was not found on PATH. Install FFmpeg before processing audio/video.")


def extract_audio(video_path: str, output_path: str) -> str:
    require_ffmpeg()
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-y", "-i", video_path, "-vn", "-acodec", "pcm_s16le", "-ar", "44100", "-ac", "2", output_path], check=True, capture_output=True)
    return output_path


def separate_stems(audio_path: str, output_dir: str) -> tuple[str | None, str | None]:
    """Run Demucs when installed; return (vocals, accompaniment)."""

    demucs = shutil.which("demucs")
    if not demucs:
        return None, None
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run([demucs, "--two-stems=vocals", "-o", str(output), audio_path], check=True, capture_output=True)
        stem_root = output / "htdemucs" / Path(audio_path).stem
        vocals = stem_root / "vocals.wav"
        no_vocals = stem_root / "no_vocals.wav"
        return (str(vocals) if vocals.exists() else None, str(no_vocals) if no_vocals.exists() else None)
    except Exception as exc:
        print(f"[DubX] Demucs stem separation failed: {exc}; proceeding without BGM separation")
        return None, None
