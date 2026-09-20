"""FFmpeg remuxing, dual-track packaging, ducking, and caption burn-in."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Iterable

from pipeline.demux import require_ffmpeg


def _run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "FFmpeg failed").strip()
        raise RuntimeError(detail[-2000:]) from exc


def _caption_encode_options() -> list[str]:
    """Return safe H.264 quality settings for the caption-rendered export."""

    try:
        crf = min(28, max(16, int(os.getenv("DUBX_CAPTION_CRF", "18"))))
    except ValueError:
        crf = 18
    preset = os.getenv("DUBX_CAPTION_PRESET", "medium").strip().lower()
    if preset not in {"ultrafast", "superfast", "veryfast", "faster", "fast", "medium", "slow", "slower"}:
        preset = "medium"
    return [
        "-c:v", "libx264", "-preset", preset, "-crf", str(crf),
        "-profile:v", "high", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
    ]


def remux_video(source_video: str, dubbed_audio: str, output_video: str, original_audio: str | None = None, language_code: str = "hi") -> str:
    """Create a video with the dub as default and original English audio retained."""

    require_ffmpeg()
    Path(output_video).parent.mkdir(parents=True, exist_ok=True)
    command = ["ffmpeg", "-y", "-i", source_video]

    if original_audio:
        command += [
            "-i", original_audio,
            "-i", dubbed_audio,
            "-map", "0:v:0", "-map", "1:a:0", "-map", "2:a:0",
            "-c:v", "copy",
            "-c:a:0", "aac", "-b:a:0", "192k",
            "-c:a:1", "aac", "-b:a:1", "192k",
            "-metadata:s:a:0", "language=eng", "-metadata:s:a:0", "title=English (Original)",
            "-metadata:s:a:1", f"language={language_code}", "-metadata:s:a:1", "title=Dubbed",
            "-disposition:a:0", "0", "-disposition:a:1", "default",
            output_video,
        ]
    else:
        command += [
            "-i", dubbed_audio,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "copy",
            "-c:a:0", "aac", "-b:a:0", "192k",
            "-metadata:s:a:0", f"language={language_code}", "-metadata:s:a:0", "title=Dubbed",
            "-disposition:a:0", "default",
            output_video,
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
    clean_sub = subtitle_path.replace("\\", "/")
    clean_sub = re.sub(r"^([a-zA-Z]):/", r"\1\\:/", clean_sub)
    clean_sub = clean_sub.replace("'", "\\'")
    # Conventional bottom-center subtitles: one timestamped cue at a time,
    # white glyphs with a black outline/shadow and no opaque background.
    # The safe side margins keep long sentences inside the frame; normal
    # wrapping is used only when a single line cannot fit.
    vf = (
        f"subtitles='{clean_sub}':"
        "force_style='Alignment=2,FontSize=15,PrimaryColour=&H00FFFFFF,"
        "OutlineColour=&H00000000,BackColour=&H80000000,BorderStyle=1,"
        "Outline=2,Shadow=1,MarginV=34,MarginL=90,MarginR=90,WrapStyle=0'"
    )
    _run([
        "ffmpeg", "-y", "-i", source_video, "-i", dubbed_audio, "-vf", vf,
        *_caption_encode_options(), "-c:a", "aac", "-b:a", "192k",
        "-map", "0:v:0", "-map", "1:a:0", output_video,
    ])
    return output_video


def mix_timed_audio_tracks(primary_audio: str, secondary_audio: str, secondary_cues: Iterable[tuple[float, float]], output_audio: str) -> str:
    """Replace selected, timestamped cues with the secondary dubbed track."""

    require_ffmpeg()
    cues = [(max(0.0, float(start)), max(float(start), float(end))) for start, end in secondary_cues]
    if not cues:
        return primary_audio
    Path(output_audio).parent.mkdir(parents=True, exist_ok=True)
    windows = "+".join(f"between(t,{start:.3f},{end:.3f})" for start, end in cues)
    # Keep the primary track everywhere except the selected windows, and keep
    # the secondary track only inside those windows. The previous chained
    # `volume=0,volume=1:enable=...` left the secondary track at zero globally.
    outside = f"not({windows})"
    filter_graph = (
        f"[0:a]volume=0:enable='{windows}'[primary];"
        f"[1:a]volume=0:enable='{outside}'[secondary];"
        "[primary][secondary]amix=inputs=2:duration=first:normalize=0[a]"
    )
    _run([
        "ffmpeg", "-y", "-i", primary_audio, "-i", secondary_audio,
        "-filter_complex", filter_graph, "-map", "[a]", "-c:a", "pcm_s16le", output_audio,
    ])
    return output_audio
