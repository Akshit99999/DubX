"""FFmpeg remuxing, dual-track packaging, ducking, and caption burn-in."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from pipeline.demux import require_ffmpeg


def _run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "FFmpeg failed").strip()
        raise RuntimeError(detail[-2000:]) from exc


def remux_video(source_video: str, dubbed_audio: str, output_video: str, original_audio: str | None = None, language_code: str = "hi") -> str:
    """Create a video with the dub as default and original English audio retained."""

    require_ffmpeg()
    Path(output_video).parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-i", source_video]
    if original_audio:
        command += ["-i", original_audio]
        map_original = "1:a:0"
    else:
        map_original = "0:a:0?"
    command += [
        "-i", dubbed_audio,
        "-map", "0:v:0", "-map", map_original, "-map", f"{2 if original_audio else 1}:a:0",
        "-c:v", "copy", "-c:a:0", "aac", "-b:a:0", "192k", "-c:a:1", "aac", "-b:a:1", "192k",
        "-metadata:s:a:0", "language=eng", "-metadata:s:a:0", "title=English (Original)",
        "-metadata:s:a:1", f"language={language_code}", "-metadata:s:a:1", "title=Dubbed",
        "-disposition:a:0", "0", "-disposition:a:1", "default", output_video,
    ]
    _run(command)
    return output_video


def remux_dub_only(source_video: str, dubbed_audio: str, output_video: str) -> str:
    require_ffmpeg()
    Path(output_video).parent.mkdir(parents=True, exist_ok=True)
    _run(["ffmpeg", "-y", "-i", source_video, "-i", dubbed_audio, "-map", "0:v:0", "-map", "1:a:0", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", output_video])
    return output_video


def burn_captions(source_video: str, dubbed_audio: str, subtitle_path: str, output_video: str) -> str:
    require_ffmpeg()
    Path(output_video).parent.mkdir(parents=True, exist_ok=True)
    if not shutil.which("ffmpeg"):
        raise RuntimeError("FFmpeg is required to burn captions")
    subtitle_filter = subtitle_path.replace("\\", "/").replace(":", "\\:").replace("'", "\\'")
    vf = f"subtitles='{subtitle_filter}':force_style='FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,MarginV=30'"
    _run(["ffmpeg", "-y", "-i", source_video, "-i", dubbed_audio, "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "22", "-c:a", "aac", "-b:a", "192k", "-map", "0:v:0", "-map", "1:a:0", output_video])
    return output_video
