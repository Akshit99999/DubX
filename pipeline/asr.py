"""Timestamped speech recognition with Groq and faster-whisper fallbacks."""

from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

from utils.subtitles import SubtitleSegment


_groq_client: Any = None


def _get_groq_client(api_key: str):
    global _groq_client
    if _groq_client is None:
        from groq import Groq

        _groq_client = Groq(api_key=api_key)
    return _groq_client


def _groq(audio_path: str, api_key: str | None) -> list[SubtitleSegment] | None:
    key = api_key or os.getenv("GROQ_API_KEY")
    if not key:
        return None
    try:
        client = _get_groq_client(key)
        with open(audio_path, "rb") as handle:
            response = client.audio.transcriptions.create(
                file=(os.path.basename(audio_path), handle.read()),
                model=os.getenv("GROQ_WHISPER_MODEL", "whisper-large-v3"),
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )
        segments_data = getattr(response, "segments", None)
        if segments_data is None and isinstance(response, dict):
            segments_data = response.get("segments")
        if not segments_data:
            text = getattr(response, "text", None) or (response.get("text") if isinstance(response, dict) else "")
            if text and str(text).strip():
                return [SubtitleSegment(0.0, 10.0, str(text).strip())]
            return None
        segments = []
        for item in segments_data:
            start = getattr(item, "start", None) if not isinstance(item, dict) else item.get("start")
            end = getattr(item, "end", None) if not isinstance(item, dict) else item.get("end")
            text = getattr(item, "text", None) if not isinstance(item, dict) else item.get("text")
            if start is not None and end is not None and text is not None:
                segments.append(SubtitleSegment(float(start), float(end), str(text)))
        return segments or None
    except Exception as exc:
        print(f"[DubX] Groq ASR unavailable; trying local Whisper: {exc}")
        return None


def _faster_whisper(audio_path: str, model_name: str) -> list[SubtitleSegment] | None:
    try:
        from faster_whisper import WhisperModel

        model = WhisperModel(model_name, device="cpu", compute_type="int8")
        segments, _ = model.transcribe(audio_path, vad_filter=True)
        return [SubtitleSegment(segment.start, segment.end, segment.text) for segment in segments]
    except Exception as exc:
        print(f"[DubX] Local Whisper unavailable: {exc}")
        return None


def transcribe(audio_path: str, api_key: str | None = None, model_name: str = "base") -> list[SubtitleSegment]:
    """Return timestamped segments or an actionable error when no ASR is configured."""

    segments = _groq(audio_path, api_key) or _faster_whisper(audio_path, model_name)
    if not segments:
        raise RuntimeError(
            "No speech recognizer is available. Install faster-whisper or set GROQ_API_KEY. "
            "For a text demo, use --mode t2t or --mode t2a."
        )
    return segments


def segments_to_dicts(segments: list[SubtitleSegment]) -> list[dict[str, Any]]:
    return [asdict(segment) for segment in segments]
