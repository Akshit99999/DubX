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


def _download(url: str, destination: Path, max_retries: int = 5) -> str:
    """Download a file with chunked streaming, retries, and partial resumption."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_suffix(destination.suffix + ".part")

    import requests

    for attempt in range(max_retries):
        try:
            downloaded = temp_path.stat().st_size if temp_path.exists() else 0
            headers = {}
            if downloaded > 0:
                headers["Range"] = f"bytes={downloaded}-"

            with requests.get(url, headers=headers, stream=True, timeout=(20, 120)) as resp:
                if resp.status_code == 416:
                    temp_path.unlink(missing_ok=True)
                    downloaded = 0
                    resp = requests.get(url, stream=True, timeout=(20, 120))
                elif resp.status_code == 200 and downloaded > 0:
                    temp_path.unlink(missing_ok=True)
                    downloaded = 0

                resp.raise_for_status()
                mode = "ab" if downloaded > 0 and resp.status_code == 206 else "wb"
                with open(temp_path, mode) as handle:
                    for chunk in resp.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            handle.write(chunk)

            if temp_path.exists():
                temp_path.replace(destination)
            return str(destination)
        except Exception as exc:
            if attempt == max_retries - 1:
                # If partial file is non-empty, attempt to use it as fallback
                if temp_path.exists() and temp_path.stat().st_size > 0:
                    try:
                        temp_path.replace(destination)
                        return str(destination)
                    except Exception:
                        pass
                raise RuntimeError(f"Download failed from {url} after {max_retries} attempts: {exc}") from exc
            time.sleep(1.0 * (2 ** attempt))

    return str(destination)


def _ensure_sarvam_compat():
    """Patch Sarvam SDK 0.1.34+ Pydantic models to tolerate backend response schema deviations."""
    try:
        import typing
        import pydantic
        from sarvamai.core.pydantic_utilities import UniversalBaseModel
        import sarvamai.types.dubbing_start_data as dsd
        import sarvamai.types.dubbing_start_response as dsr
        import sarvamai.types as st
        import sarvamai.dubbing.raw_client as rc

        class PatchedDubbingStartData(UniversalBaseModel):
            job_id: str = ""
            status: str = "processing"
            task_id: typing.Optional[str] = None
            project_id: typing.Optional[str] = None
            task_submitted: typing.Optional[bool] = None
            model_config = pydantic.ConfigDict(extra="allow")

        class PatchedDubbingStartResponse(UniversalBaseModel):
            status: str = "success"
            message: str = ""
            data: PatchedDubbingStartData
            model_config = pydantic.ConfigDict(extra="allow")

        dsd.DubbingStartData = PatchedDubbingStartData
        dsr.DubbingStartData = PatchedDubbingStartData
        dsr.DubbingStartResponse = PatchedDubbingStartResponse
        st.DubbingStartData = PatchedDubbingStartData
        st.DubbingStartResponse = PatchedDubbingStartResponse
        rc.DubbingStartResponse = PatchedDubbingStartResponse
    except Exception:
        pass


def dub_media(
    media_path: str,
    source_language: str,
    target_language: str,
    media_kind: str,
    *,
    num_speakers: int = -1,
    register: str = "auto",
    secondary_language: str | None = None,
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

    def report(stage: str, message: str, progress: float | None = None, **extra: Any) -> None:
        if progress_callback:
            progress_callback({"stage": stage, "message": message, "progress": progress, **extra})

    try:
        from sarvamai import SarvamAI
    except ImportError as exc:
        raise SarvamDubbingError("Sarvam SDK is not installed. Run: pip install 'sarvamai>=0.1.31a1'") from exc

    _ensure_sarvam_compat()

    source_code = sarvam_language_code(source_language)
    target_code = sarvam_language_code(target_language)
    secondary_code = sarvam_language_code(secondary_language) if secondary_language else None
    if secondary_code == target_code:
        secondary_code = None
    fast_mode = os.getenv("DUBX_FAST_MODE", "1").strip().lower() not in {"0", "false", "no", "off"}
    # A Sarvam video export already contains its dubbed audio. In fast mode we
    # avoid asking the service to render/download a second standalone audio
    # export; we extract that exact embedded track locally after downloading.
    export_options = ["audio", "srt"]
    if media_kind == "video":
        export_options = ["video", "srt"] if fast_mode else ["video", "audio", "srt"]
    else:
        fast_mode = False

    client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])
    report("clone", "Creating source-speaker dubbing job…", 0.38)
    created = client.dubbing.create(
        source_language_code=source_code,
        target_language_codes=[target_code] + ([secondary_code] if secondary_code else []),
        export_options=export_options,
        voice_cloning=True,
        # Sarvam accepts -1 to diarize and count speakers automatically. The
        # previous clamp silently converted it to one speaker, flattening every
        # conversation into the first speaker's voice.
        num_speakers=-1 if int(num_speakers) == -1 else max(1, min(10, int(num_speakers))),
        disable_watermark=True,
        register=register,
        job_name=media.name,
    )
    job_id = created.data.job_id
    report("upload", "Uploading source media for voice analysis…", 0.42, job_id=job_id)
    client.dubbing.upload(created.data.upload_url, media)
    report("clone", "Source uploaded; Sarvam is translating and aligning voices…", 0.48, job_id=job_id)
    try:
        client.dubbing.start(job_id=job_id)
    except Exception as exc:
        err_msg = str(exc)
        if "DubbingStartResponse" in err_msg or "task_submitted" in err_msg or "project_id" in err_msg or "job_id" in err_msg:
            # Sarvam SDK 0.1.34 bug: backend returns {'project_id': ..., 'task_submitted': True}
            # which can fail DubbingStartData validation because job_id is marked required,
            # even though the task was successfully submitted on the server.
            pass
        else:
            raise

    terminal = {"completed", "partial_failure", "failed", "deleted"}
    deadline = time.monotonic() + timeout_seconds
    poll_interval = min(5, max(2, poll_seconds))
    while True:
        job = client.dubbing.get_live_status(job_id=job_id).data
        provider_progress = getattr(job, "progress", None)
        try:
            normalized_progress = 0.48 + max(0.0, min(float(provider_progress), 100.0)) * 0.34 / 100.0
        except (TypeError, ValueError):
            normalized_progress = None
        event = {
            "job_id": job_id,
            "status": getattr(job, "status", "unknown"),
            "progress": normalized_progress,
            "provider_progress": provider_progress,
            "step": getattr(job, "current_step_label", None),
            "stage": "clone",
            "message": getattr(job, "current_step_label", None) or "Sarvam is translating and aligning voices…",
        }
        if progress_callback:
            progress_callback(event)
        if event["status"] in terminal:
            break
        if time.monotonic() > deadline:
            raise TimeoutError(f"Sarvam dubbing job {job_id} did not finish within {timeout_seconds}s")
        time.sleep(poll_interval)
        poll_interval = min(8, poll_interval + 1)

    if getattr(job, "status", None) == "failed":
        raise SarvamDubbingError(getattr(job, "error_message", None) or f"Sarvam dubbing job {job_id} failed")

    report("export", "Rendering timed subtitles and dubbed media…", 0.84, job_id=job_id)
    requested_codes = [target_code] + ([secondary_code] if secondary_code else [])
    wanted = {(language_code, export_type) for language_code in requested_codes for export_type in export_options}
    deadline = time.monotonic() + timeout_seconds
    poll_interval = 3
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
        time.sleep(poll_interval)
        poll_interval = min(6, poll_interval + 1)

    suffixes = {"video": ".mp4", "audio": ".wav", "mp3": ".mp3", "srt": ".srt"}
    downloaded_by_language: dict[str, dict[str, str]] = {}
    stem = media.stem
    for item in exports:
        if item.target_language not in {target_code, secondary_code} or item.status != "completed" or getattr(item, "is_stale", False):
            continue
        url = getattr(item, "download_url", None)
        if not url:
            continue
        export_type = item.export_type
        suffix = suffixes.get(export_type, ".bin")
        export_language = "secondary" if item.target_language == secondary_code else target_language
        target = OUTPUT_DIR / f"sarvam_{stem}_{export_language}_{export_type}{suffix}"
        report("download", f"Downloading {export_type} export…", 0.91, job_id=job_id)
        downloaded_by_language.setdefault(item.target_language, {})[export_type] = _download(url, target)

    downloaded = downloaded_by_language.get(target_code, {})

    required = {"audio", "srt"}
    if media_kind == "video":
        required = {"video", "srt"}

    if media_kind == "video" and "audio" not in downloaded:
        # Keep the audio path contract stable for the UI/CLI while avoiding a
        # duplicate Sarvam export in the low-latency video path.
        from pipeline.demux import extract_audio

        extracted_audio = OUTPUT_DIR / f"sarvam_{stem}_{target_language}_audio.wav"
        extract_audio(downloaded["video"], str(extracted_audio))
        downloaded["audio"] = str(extracted_audio)

    missing = required - set(downloaded)
    if missing:
        raise SarvamDubbingError(f"Sarvam job {job_id} completed without usable exports: {', '.join(sorted(missing))}")
    if "srt" in downloaded:
        # Provider exports occasionally use two text lines for a single cue;
        # collapse them before returning or burning captions.
        from utils.subtitles import normalize_srt_file

        normalize_srt_file(downloaded["srt"])
    secondary_exports = downloaded_by_language.get(secondary_code, {}) if secondary_code else {}
    if secondary_exports and media_kind == "video" and "audio" not in secondary_exports and "video" in secondary_exports:
        from pipeline.demux import extract_audio

        secondary_audio = OUTPUT_DIR / f"sarvam_{stem}_secondary_audio.wav"
        extract_audio(secondary_exports["video"], str(secondary_audio))
        secondary_exports["audio"] = str(secondary_audio)
    if secondary_exports.get("srt"):
        from utils.subtitles import normalize_srt_file

        normalize_srt_file(secondary_exports["srt"])
    report("complete", "Sarvam dubbing export is ready.", 0.98, job_id=job_id)
    return {
        "job_id": job_id,
        "source_language_code": source_code,
        "target_language_code": target_code,
        "exports": downloaded,
        "secondary_exports": secondary_exports,
        "status": getattr(job, "status", "completed"),
        "clone_method": "sarvam-dubbing",
    }
