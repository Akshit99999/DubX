"""FFmpeg extraction and optional Demucs stem separation."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path


def ensure_ffmpeg() -> str | None:
    """Ensure ffmpeg is discoverable on PATH. Check system PATH, Scripts, or imageio-ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found

    # 1. Check Python Scripts directory
    scripts_dir = os.path.join(sys.prefix, "Scripts")
    candidate = os.path.join(scripts_dir, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if os.path.isfile(candidate):
        os.environ["PATH"] = scripts_dir + os.pathsep + os.environ.get("PATH", "")
        return candidate

    # 2. Try imageio_ffmpeg
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            exe_dir = os.path.dirname(exe)
            alias = os.path.join(exe_dir, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
            if not os.path.isfile(alias):
                try:
                    shutil.copyfile(exe, alias)
                except OSError:
                    pass
            chosen = alias if os.path.isfile(alias) else exe
            chosen_dir = os.path.dirname(chosen)
            if chosen_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = chosen_dir + os.pathsep + os.environ.get("PATH", "")
            return shutil.which("ffmpeg") or chosen
    except ImportError:
        pass

    return None


def require_ffmpeg() -> None:
    if not ensure_ffmpeg():
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
