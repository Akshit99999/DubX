"""Optional speech synthesis backends."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

from config import voice_for


async def _edge_tts(text: str, voice: str, output_path: str, rate: str) -> str:
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("Edge-TTS is not installed. Install it with: pip install edge-tts") from exc
    await edge_tts.Communicate(text=text, voice=voice, rate=rate).save(output_path)
    return output_path


def synthesize(text: str, language: str, gender: str, output_path: str, rate: str = "+0%") -> str:
    """Synthesize a regional MP3 using the configured optional backend."""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    backend = os.getenv("DUBX_TTS_BACKEND", "edge").lower()
    if backend != "edge":
        raise RuntimeError(f"Unsupported TTS backend '{backend}'. Set DUBX_TTS_BACKEND=edge.")
    return asyncio.run(_edge_tts(text, voice_for(language, gender), output_path, rate))
