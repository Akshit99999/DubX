"""Sarvam Dubbing API integration for consent-based speaker-preserving dubs."""

from __future__ import annotations

import os
import time
import urllib.request
from pathlib import Path
from typing import Any, Callable

from config import OUTPUT_DIR, sarvam_language_code


class SarvamDubbingError(RuntimeError):
    """Raised when a Sarvam dubbing job cannot produce a usable export."""


def available() -> bool:
    return bool(os.getenv("SARVAM_API_KEY", "").strip())


def _download(url: str, destination: Path) -> str:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url, timeout=120) as response, destination.open("wb") as handle:
        handle.write(response.read())
    return str(destination)


def dub_media(
    media_path: str,
    source_language: str,
    target_language: str,
    media_kind: str,
    *,
    num_speakers: int = 1,
    timeout_seconds: int = 3600,
    poll_seconds: int = 15,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Create, wait for, and download a Sarvam speaker-cloned dubbing job.

    The caller is responsible for collecting affirmative authorization before
    invoking this function.  It intentionally uses Sarvam's source-media
    dubbing endpoint rather than trying to approximate timbre with a generic
    TTS voice and a pitch shift.
    """

    if not available():
        raise SarvamDubbingError("SARVAM_API_KEY is required for Sarvam speaker-preserving dubbing")
    media = Path(media_path)
    if not media.is_file():
        raise FileNotFoundError(f"Input media file not found: {media_path}")
    if media_kind not in {"audio", "video"}:
        raise ValueError("media_kind must be 'audio' or 'video'")

    try:
        from sarvamai import SarvamAI
    except ImportError as exc:
        raise SarvamDubbingError("Sarvam SDK is not installed. Run: pip install 'sarvamai>=0.1.31a1'") from exc

    source_code = sarvam_language_code(source_language)
    target_code = sarvam_language_code(target_language)
    export_options = ["audio", "srt"]
    if media_kind == "video":
        export_options.insert(0, "video")

    client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])
    created = client.dubbing.create(
        source_language_code=source_code,
        target_language_codes=[target_code],
        export_options=export_options,
        voice_cloning=True,
        num_speakers=max(1, int(num_speakers)),
        disable_watermark=True,
        job_name=media.name,
    )
    job_id = created.data.job_id
    client.dubbing.upload(created.data.upload_url, media)
    client.dubbing.start(job_id=job_id)

    terminal = {"completed", "partial_failure", "failed", "deleted"}
    deadline = time.monotonic() + timeout_seconds
    while True:
        job = client.dubbing.get_live_status(job_id=job_id).data
        event = {
            "job_id": job_id,
            "status": getattr(job, "status", "unknown"),
            "progress": getattr(job, "progress", None),
            "step": getattr(job, "current_step_label", None),
        }
        if progress_callback:
            progress_callback(event)
        if event["status"] in terminal:
            break
        if time.monotonic() > deadline:
            raise TimeoutError(f"Sarvam dubbing job {job_id} did not finish within {timeout_seconds}s")
        time.sleep(poll_seconds)

    if getattr(job, "status", None) == "failed":
        raise SarvamDubbingError(getattr(job, "error_message", None) or f"Sarvam dubbing job {job_id} failed")

    wanted = {(target_code, export_type) for export_type in export_options}
    deadline = time.monotonic() + timeout_seconds
    while True:
        exports = client.dubbing.get_export_status(job_id=job_id, limit=100).data.exports or []
        settled = {
            (item.target_language, item.export_type)
            for item in exports
            if item.status in {"completed", "failed"}
        }
        if wanted <= settled:
            break
        if time.monotonic() > deadline:
            raise TimeoutError(f"Sarvam exports for job {job_id} did not settle within {timeout_seconds}s")
        time.sleep(poll_seconds)

    suffixes = {"video": ".mp4", "audio": ".wav", "mp3": ".mp3", "srt": ".srt"}
    downloaded: dict[str, str] = {}
    stem = media.stem
    for item in exports:
        if item.target_language != target_code or item.status != "completed" or getattr(item, "is_stale", False):
            continue
        url = getattr(item, "download_url", None)
        if not url:
            continue
        export_type = item.export_type
        suffix = suffixes.get(export_type, ".bin")
        target = OUTPUT_DIR / f"sarvam_{stem}_{target_language}_{export_type}{suffix}"
        downloaded[export_type] = _download(url, target)

    required = {"audio", "srt"}
    if media_kind == "video":
        required.add("video")
    missing = required - set(downloaded)
    if missing:
        raise SarvamDubbingError(f"Sarvam job {job_id} completed without usable exports: {', '.join(sorted(missing))}")
    return {
        "job_id": job_id,
        "source_language_code": source_code,
        "target_language_code": target_code,
        "exports": downloaded,
        "status": getattr(job, "status", "completed"),
        "clone_method": "sarvam-dubbing",
    }
