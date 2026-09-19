"""Universal input helpers for local files and social URLs."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path


def resolve_input(source: str, output_dir: str | Path) -> str:
    """Return a local input path, downloading a URL with yt-dlp when available."""

    candidate = Path(source)
    if candidate.exists():
        return str(candidate.resolve())
    if not source.startswith(("http://", "https://")):
        raise FileNotFoundError(f"Input file not found: {source}")
    if not shutil.which("yt-dlp"):
        raise RuntimeError("A URL was supplied, but yt-dlp is not installed. Install it with: pip install yt-dlp")
    destination = Path(output_dir)
    destination.mkdir(parents=True, exist_ok=True)
    template = str(destination / "source_%(id)s.%(ext)s")
    subprocess.run(["yt-dlp", "-f", "bv*+ba/b", "--merge-output-format", "mp4", "-o", template, source], check=True)
    matches = sorted(destination.glob("source_*"), key=lambda path: path.stat().st_mtime, reverse=True)
    if not matches:
        raise RuntimeError("yt-dlp completed but did not produce an input file")
    return str(matches[0].resolve())
