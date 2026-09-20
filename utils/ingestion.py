"""Universal input helpers for local files and social URLs."""

from __future__ import annotations

import shutil
import subprocess
import sys
import os
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


def is_youtube_url(source: str) -> bool:
    """Return whether *source* is a normal YouTube watch, short, or share URL."""

    host = (urlparse(source).hostname or "").lower().removeprefix("www.")
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


ProgressCallback = Callable[[dict[str, Any]], None]


def _report(callback: ProgressCallback | None, **event: Any) -> None:
    if callback:
        callback(event)


def resolve_input(
    source: str | dict | Path,
    output_dir: str | Path,
    progress_callback: ProgressCallback | None = None,
) -> str:
    """Return a local input path, downloading a URL with yt-dlp when available.

    The downloader is streamed rather than run with captured output. Browser
    clients can show activity while a YouTube video or Short is being fetched.
    """

    if isinstance(source, dict):
        source = source.get("path") or source.get("video", {}).get("path") or source.get("name", "")
    if not source:
        raise ValueError("Input source cannot be empty")

    source_str = str(source).strip()
    if source_str.startswith(("http://", "https://")):
        # Calling the installed module is reliable on Windows virtualenvs, where
        # the yt-dlp console script is often not on PATH.
        try:
            import yt_dlp  # noqa: F401
            yt_dlp_command = [sys.executable, "-m", "yt_dlp"]
        except ImportError:
            executable = shutil.which("yt-dlp")
            if not executable:
                raise RuntimeError("A YouTube/video URL was supplied, but yt-dlp is not installed. Run: pip install yt-dlp")
            yt_dlp_command = [executable]
        destination = Path(output_dir)
        destination.mkdir(parents=True, exist_ok=True)
        # Prevent a previous download with the same YouTube id from being
        # mistaken for this request's result.
        request_id = str(time.time_ns())
        template = str(destination / f"source_{request_id}_%(id)s.%(ext)s")
        try:
            max_height = max(144, int(os.getenv("DUBX_YOUTUBE_MAX_HEIGHT", "1080")))
        except ValueError:
            max_height = 1080
        format_selector = f"bv*[height<={max_height}]+ba/b[height<={max_height}]/b"
        command = yt_dlp_command + [
            "--no-playlist",
            "--newline",
            "--windows-filenames",
            "--concurrent-fragments", "4",
            "--retries", "3",
            "--fragment-retries", "3",
            "-f", format_selector,
            "--merge-output-format", "mp4",
            "-o", template,
            source_str,
        ]
        _report(progress_callback, stage="download", message="Downloading source video…", progress=0.02)
        output_lines: list[str] = []
        try:
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if process.stdout is not None:
                for line in process.stdout:
                    output_lines.append(line)
                    match = re.search(r"\[download\]\s+(\d+(?:\.\d+)?)%", line)
                    if match:
                        percent = float(match.group(1))
                        _report(
                            progress_callback,
                            stage="download",
                            message=f"Downloading source video ({percent:.0f}%)…",
                            progress=0.02 + min(percent, 100.0) * 0.23 / 100.0,
                        )
                    elif "Merging formats" in line:
                        _report(progress_callback, stage="download", message="Merging video and audio…", progress=0.26)
            return_code = process.wait()
            if return_code:
                raise subprocess.CalledProcessError(return_code, command, output="".join(output_lines))
        except subprocess.CalledProcessError as exc:
            label = "YouTube" if is_youtube_url(source_str) else "video"
            detail = (exc.stderr or exc.stdout or exc.output or "yt-dlp failed").strip()
            raise RuntimeError(f"Could not download the {label} URL: {detail[-800:]}") from exc
        matches = sorted(destination.glob(f"source_{request_id}_*"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not matches:
            raise RuntimeError("yt-dlp completed but did not produce an input file")
        _report(progress_callback, stage="download", message="Source video ready.", progress=0.28)
        return str(matches[0].resolve())

    candidate = Path(source_str)
    if candidate.exists():
        return str(candidate.resolve())

    raise FileNotFoundError(f"Input file not found: {source_str}")
