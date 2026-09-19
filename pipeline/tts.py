"""Optional speech synthesis backends."""

from __future__ import annotations

import asyncio
import concurrent.futures
import os
from pathlib import Path

from typing import Any

from config import voice_for
from pipeline.voice_clone import analyze_speaker_voice


def _elevenlabs_clone_and_tts(text: str, reference_audio: str, output_path: str, api_key: str) -> str | None:
    """Clone speaker voice using ElevenLabs Instant Voice Cloning API and generate speech."""
    ref_path = Path(reference_audio)
    if not ref_path.is_file():
        return None

    import requests

    headers = {"xi-api-key": api_key}
    voice_name = f"dubx_{ref_path.stem[:20]}"
    suffix = ref_path.suffix.lower()
    mime_type = "audio/wav" if suffix == ".wav" else ("audio/mpeg" if suffix in {".mp3", ".mpeg"} else "audio/octet-stream")

    voice_id = None
    try:
        with open(ref_path, "rb") as audio_file:
            files = {"files": (ref_path.name, audio_file, mime_type)}
            data = {"name": voice_name, "description": "DubX reference voice clone"}
            resp = requests.post("https://api.elevenlabs.io/v1/voices/add", headers=headers, data=data, files=files, timeout=30)

        if resp.status_code != 200:
            print(f"[DubX] ElevenLabs voice clone add failed ({resp.status_code}): {resp.text}")
            return None

        voice_id = resp.json().get("voice_id")
        if not voice_id:
            return None

        tts_url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        tts_headers = {"xi-api-key": api_key, "Content-Type": "application/json"}
        tts_payload = {
            "text": text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        tts_resp = requests.post(tts_url, headers=tts_headers, json=tts_payload, timeout=60)
        if tts_resp.status_code != 200:
            print(f"[DubX] ElevenLabs TTS synthesis failed ({tts_resp.status_code}): {tts_resp.text}")
            return None

        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "wb") as out_f:
            out_f.write(tts_resp.content)

        return f"elevenlabs:{voice_id}"
    finally:
        if voice_id and os.getenv("ELEVENLABS_DELETE_AFTER_CLONE", "1") == "1":
            try:
                requests.delete(f"https://api.elevenlabs.io/v1/voices/{voice_id}", headers=headers, timeout=10)
            except Exception:
                pass


async def _edge_tts(text: str, voice: str, output_path: str, rate: str = "+0%", pitch: str = "+0Hz") -> str:
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("Edge-TTS is not installed. Install it with: pip install edge-tts") from exc
    await edge_tts.Communicate(text=text, voice=voice, rate=rate, pitch=pitch).save(output_path)
    return output_path


def _run_async(coro):
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            return pool.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def synthesize(
    text: str,
    language: str,
    gender: str = "auto",
    output_path: str = "",
    rate: str = "+0%",
    reference_audio: str | None = None,
    pitch: str = "+0Hz",
    clone_voice: bool = True,
) -> dict[str, Any]:
    """Synthesize a regional MP3 using Edge-TTS or ElevenLabs voice cloning."""

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    f0_hz: float | None = None
    pitch_offset: str = pitch
    gender_used: str = gender if gender in {"male", "female"} else "male"
    detected_gender: str = gender_used
    cloned_voice: bool = False
    voice_used: str = ""

    if reference_audio and clone_voice:
        voice_meta = analyze_speaker_voice(reference_audio, gender)
        f0_hz = voice_meta.get("f0_hz")
        detected_gender = voice_meta.get("detected_gender", "male")
        # a) Determine gender (if gender == 'auto', use detected_gender).
        gender_used = detected_gender if gender == "auto" else voice_meta.get("gender_used", "male")
        if gender_used not in {"male", "female"}:
            gender_used = "male"

        # b) Determine pitch offset (e.g. '+15Hz', '-20Hz').
        pitch_offset = voice_meta.get("pitch_str", "+0Hz")

        # c) If ELEVENLABS_API_KEY is present in os.environ, attempt ElevenLabs voice cloning;
        #    otherwise use the adaptive Edge-TTS neural pitch/timbre matcher.
        elevenlabs_key = os.getenv("ELEVENLABS_API_KEY")
        if elevenlabs_key and elevenlabs_key.strip():
            try:
                voice_id = _elevenlabs_clone_and_tts(
                    text=text,
                    reference_audio=reference_audio,
                    output_path=output_path,
                    api_key=elevenlabs_key.strip(),
                )
                if voice_id:
                    voice_used = voice_id
                    cloned_voice = True
            except Exception as exc:
                print(f"[DubX] ElevenLabs voice cloning attempt failed: {exc}")
                cloned_voice = False

        if not cloned_voice:
            # Adaptive Edge-TTS neural pitch/timbre matcher
            backend = os.getenv("DUBX_TTS_BACKEND", "edge").lower()
            if backend != "edge":
                raise RuntimeError(f"Unsupported TTS backend '{backend}'. Set DUBX_TTS_BACKEND=edge.")
            voice_used = voice_for(language, gender_used)
            _run_async(_edge_tts(text, voice_used, output_path, rate=rate, pitch=pitch_offset))
            cloned_voice = True
    else:
        backend = os.getenv("DUBX_TTS_BACKEND", "edge").lower()
        if backend != "edge":
            raise RuntimeError(f"Unsupported TTS backend '{backend}'. Set DUBX_TTS_BACKEND=edge.")
        voice_used = voice_for(language, gender_used)
        _run_async(_edge_tts(text, voice_used, output_path, rate=rate, pitch=pitch))
        cloned_voice = False

    return {
        "output_path": output_path,
        "f0_hz": f0_hz,
        "speaker_f0_hz": f0_hz,
        "pitch_offset": pitch_offset,
        "gender_used": gender_used,
        "detected_gender": detected_gender,
        "voice_used": voice_used,
        "cloned_voice": cloned_voice,
    }
