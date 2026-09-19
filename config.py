"""Shared DubX configuration.

The project deliberately keeps third-party integrations optional.  This module
contains the stable language/voice configuration used by the CLI, the Gradio
app, and the pipeline modules.
"""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
OUTPUT_DIR = PROJECT_ROOT / "output_dubbed"

try:
    from dotenv import load_dotenv

    load_dotenv(PROJECT_ROOT / ".env")
except ImportError:
    pass

import os
import shutil
import sys


def _setup_ffmpeg() -> None:
    """Ensure ffmpeg is discoverable on PATH across all environments."""
    if shutil.which("ffmpeg"):
        return
    scripts_dir = os.path.join(sys.prefix, "Scripts")
    candidate = os.path.join(scripts_dir, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
    if os.path.isfile(candidate):
        os.environ["PATH"] = scripts_dir + os.pathsep + os.environ.get("PATH", "")
        return
    try:
        import imageio_ffmpeg

        exe = imageio_ffmpeg.get_ffmpeg_exe()
        if exe and os.path.isfile(exe):
            exe_dir = os.path.dirname(exe)
            alias = os.path.join(exe_dir, "ffmpeg.exe" if os.name == "nt" else "ffmpeg")
            if not os.path.isfile(alias):
                try:
                    shutil.copyfile(exe, alias)
                except OSError:
                    pass
            chosen = alias if os.path.isfile(alias) else exe
            chosen_dir = os.path.dirname(chosen)
            if chosen_dir not in os.environ.get("PATH", ""):
                os.environ["PATH"] = chosen_dir + os.pathsep + os.environ.get("PATH", "")
    except ImportError:
        pass


_setup_ffmpeg()


VOICE_MAP = {
    "english": {
        "code": "en",
        "name": "English",
        "male": "en-IN-PrabhatNeural",
        "female": "en-IN-NeerjaNeural",
        "default": "en-IN-PrabhatNeural",
    },
    "punjabi": {
        "code": "pa",
        "name": "Punjabi",
        "male": "pa-IN-OjasNeural",
        "female": "pa-IN-VaaniNeural",
        "default": "pa-IN-OjasNeural",
    },
    "hindi": {
        "code": "hi",
        "name": "Hindi",
        "male": "hi-IN-MadhurNeural",
        "female": "hi-IN-SwaraNeural",
        "default": "hi-IN-MadhurNeural",
    },
    "tamil": {
        "code": "ta",
        "name": "Tamil",
        "male": "ta-IN-ValluvarNeural",
        "female": "ta-IN-PallaviNeural",
        "default": "ta-IN-ValluvarNeural",
    },
    "telugu": {
        "code": "te",
        "name": "Telugu",
        "male": "te-IN-MohanNeural",
        "female": "te-IN-ShrutiNeural",
        "default": "te-IN-MohanNeural",
    },
    "bengali": {
        "code": "bn",
        "name": "Bengali",
        "male": "bn-IN-BashkarNeural",
        "female": "bn-IN-TanishaaNeural",
        "default": "bn-IN-BashkarNeural",
    },
    "marathi": {
        "code": "mr",
        "name": "Marathi",
        "male": "mr-IN-ManoharNeural",
        "female": "mr-IN-AarohiNeural",
        "default": "mr-IN-ManoharNeural",
    },
    "kannada": {
        "code": "kn",
        "name": "Kannada",
        "male": "kn-IN-GaganNeural",
        "female": "kn-IN-SapnaNeural",
        "default": "kn-IN-GaganNeural",
    },
    "gujarati": {
        "code": "gu",
        "name": "Gujarati",
        "male": "gu-IN-NiranjanNeural",
        "female": "gu-IN-DhwaniNeural",
        "default": "gu-IN-NiranjanNeural",
    },
    "malayalam": {
        "code": "ml",
        "name": "Malayalam",
        "male": "ml-IN-MidhunNeural",
        "female": "ml-IN-SobhanaNeural",
        "default": "ml-IN-MidhunNeural",
    },
    # Convenient aliases from the implementation spec.  The matrix API also
    # accepts any two base languages directly (for example Hindi + Punjabi).
    "hinglish": {
        "code": "hi-en",
        "name": "Hinglish (Hindi + English)",
        "male": "hi-IN-MadhurNeural",
        "female": "en-IN-NeerjaNeural",
        "default": "hi-IN-MadhurNeural",
    },
    "tanglish": {
        "code": "ta-en",
        "name": "Tanglish (Tamil + English)",
        "male": "ta-IN-ValluvarNeural",
        "female": "en-IN-NeerjaNeural",
        "default": "ta-IN-ValluvarNeural",
    },
    "tenglish": {
        "code": "te-en",
        "name": "Tenglish (Telugu + English)",
        "male": "te-IN-MohanNeural",
        "female": "en-IN-NeerjaNeural",
        "default": "te-IN-MohanNeural",
    },
}


def language_config(language: str) -> dict:
    """Return a language configuration or raise a useful validation error."""

    key = language.strip().lower()
    if key not in VOICE_MAP:
        choices = ", ".join(sorted(VOICE_MAP))
        raise ValueError(f"Unsupported language '{language}'. Choose one of: {choices}")
    return VOICE_MAP[key]


def voice_for(language: str, gender: str = "male") -> str:
    """Resolve a legacy per-language voice label for compatibility callers."""

    config = language_config(language)
    gender_key = gender.strip().lower()
    if gender_key == "auto":
        return config.get("default", config["male"])
    if gender_key not in {"male", "female"}:
        raise ValueError("gender must be 'male' or 'female'")
    return config[gender_key]


def sarvam_language_code(language: str) -> str:
    """Return the language tag required by Sarvam's dubbing API."""

    key = language.strip().lower()
    aliases = {"hinglish": "hindi", "tanglish": "tamil", "tenglish": "telugu"}
    key = aliases.get(key, key)
    return f"{language_config(key)['code']}-IN"
