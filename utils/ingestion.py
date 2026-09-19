"""Universal input helpers for local files and social URLs."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse


def is_youtube_url(source: str) -> bool:
    """Return whether *source* is a normal YouTube watch, short, or share URL."""

    host = (urlparse(source).hostname or "").lower().removeprefix("www.")
    return host == "youtu.be" or host == "youtube.com" or host.endswith(".youtube.com")


def resolve_input(source: str | dict | Path, output_dir: str | Path) -> str:
    """Return a local input path, downloading a URL with yt-dlp when available."""

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
        template = str(destination / "source_%(id)s.%(ext)s")
        command = yt_dlp_command + [
            "--no-playlist",
            "--no-progress",
            "--windows-filenames",
            "-f", "bv*+ba/b",
            "--merge-output-format", "mp4",
            "-o", template,
            source_str,
        ]
        try:
            subprocess.run(command, check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            label = "YouTube" if is_youtube_url(source_str) else "video"
            detail = (exc.stderr or exc.stdout or "yt-dlp failed").strip()
            raise RuntimeError(f"Could not download the {label} URL: {detail[-800:]}") from exc
        matches = sorted(destination.glob("source_*"), key=lambda path: path.stat().st_mtime, reverse=True)
        if not matches:
            raise RuntimeError("yt-dlp completed but did not produce an input file")
        return str(matches[0].resolve())

    candidate = Path(source_str)
    if candidate.exists():
        return str(candidate.resolve())

    raise FileNotFoundError(f"Input file not found: {source_str}")
