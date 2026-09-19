"""Backward-compatible text dubbing CLI backed by Sarvam Bulbul v3."""

from __future__ import annotations

import argparse

from config import VOICE_MAP
from dubx_core import text_to_audio_dub, text_to_text_dub


def transcreate_text(text: str, target_language: str = "hindi", api_key: str | None = None, dialect_level: int = 2) -> dict:
    """Return a culturally adapted line without generating audio."""

    return text_to_text_dub(text, target_language, api_key=api_key, dialect_level=dialect_level)


def text_to_dubbed_audio(
    text: str,
    target_language: str = "hindi",
    gender: str = "auto",
    output_path: str | None = None,
    api_key: str | None = None,
    rate: str = "+0%",
    dialect_level: int = 2,
) -> dict:
    """Transcreate text and synthesize it with Sarvam Bulbul v3.

    Text has no original speaker reference, so this function intentionally
    uses a preset Sarvam voice and never represents the output as a clone.
    """

    return text_to_audio_dub(
        text,
        target_language=target_language,
        gender=gender,
        output_path=output_path,
        api_key=api_key,
        rate=rate,
        dialect_level=dialect_level,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="DubX text-to-audio dubbing with Sarvam Bulbul v3")
    parser.add_argument("text", nargs="?", default="Don't put all your eggs in one basket")
    parser.add_argument("--lang", default="hindi", choices=sorted(VOICE_MAP))
    parser.add_argument("--gender", default="auto", choices=["auto", "male", "female"])
    parser.add_argument("--output", default=None, help="Output WAV path")
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--dialect", type=int, default=2, choices=[1, 2, 3])
    args = parser.parse_args()
    result = text_to_dubbed_audio(args.text, args.lang, args.gender, args.output, rate=args.rate, dialect_level=args.dialect)
    print(result["audio_path"])


if __name__ == "__main__":
    main()
