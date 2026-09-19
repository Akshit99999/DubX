"""Sarvam Bulbul text-to-speech backend.

True source-speaker cloning is intentionally handled by ``sarvam_dubbing``
for audio/video inputs.  A text-only request has no source speaker, so it
uses a clearly labelled Sarvam preset voice instead of claiming a clone.
"""

from __future__ import annotations

import base64
import os
import re
from pathlib import Path
from typing import Any

from config import sarvam_language_code


def _pace_from_rate(rate: str) -> float:
    """Convert a familiar ``+10%`` rate string to Bulbul's pace range."""

    match = re.fullmatch(r"([+-]?)(\d+(?:\.\d+)?)%", str(rate).strip())
    if not match:
        return 1.0
    value = float(match.group(2)) / 100.0
    pace = 1.0 + value if match.group(1) != "-" else 1.0 - value
    return max(0.5, min(2.0, pace))


def _response_value(response: Any, name: str, default: Any = None) -> Any:
    if isinstance(response, dict):
        return response.get(name, default)
    return getattr(response, name, default)


def synthesize(
    text: str,
    language: str,
    gender: str = "auto",
    output_path: str = "",
    rate: str = "+0%",
    reference_audio: str | None = None,
    pitch: str = "+0Hz",
    clone_voice: bool = False,
) -> dict[str, Any]:
    """Synthesize with Sarvam Bulbul v3; never emulate voice cloning.

    ``reference_audio`` and ``clone_voice`` are accepted to keep the existing
    Python API stable. A cloning request is rejected here because the caller
    must use the Sarvam Dubbing path, which preserves the source speaker on
    the original media timeline.
    """

    if clone_voice or reference_audio:
        raise RuntimeError(
            "Source-speaker cloning requires the Sarvam Dubbing workflow. "
            "Select 'Clone original speaker with Sarvam' and confirm consent."
        )
    if not text or not text.strip():
        raise ValueError("Text-to-speech input cannot be empty")
    if len(text) > 2500:
        raise ValueError("Sarvam Bulbul v3 accepts up to 2500 characters per synthesis request")
    api_key = os.getenv("SARVAM_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError("SARVAM_API_KEY is required. Add it to .env before synthesizing audio.")
    try:
        from sarvamai import SarvamAI
    except ImportError as exc:
        raise RuntimeError("Sarvam SDK is not installed. Run: pip install 'sarvamai>=0.1.31a1'") from exc

    speaker = os.getenv("DUBX_SARVAM_SPEAKER", "").strip() or None
    request: dict[str, Any] = {
        "text": text,
        "language_code": sarvam_language_code(language),
        "model": "bulbul:v3",
        "pace": _pace_from_rate(rate),
        "speech_sample_rate": 24000,
        "output_audio_codec": "wav",
        "temperature": 0.45,
    }
    if speaker:
        request["speaker"] = speaker

    response = SarvamAI(api_subscription_key=api_key).text_to_speech.convert(**request)
    audios = _response_value(response, "audios")
    if not audios:
        raise RuntimeError("Sarvam Bulbul returned no audio")
    audio_payload = audios[0]
    if isinstance(audio_payload, bytes):
        audio_bytes = audio_payload
    else:
        audio_bytes = base64.b64decode(audio_payload)
    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(audio_bytes)
    return {
        "output_path": str(destination),
        "voice_used": f"sarvam:{speaker or 'default'}",
        "cloned_voice": False,
        "clone_method": "none",
        "backend": "sarvam-bulbul:v3",
        "gender_used": gender,
        "detected_gender": None,
        "f0_hz": None,
        "speaker_f0_hz": None,
        "pitch_offset": None,
    }
