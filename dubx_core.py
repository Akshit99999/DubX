"""DubX unified five-mode dubbing engine.

The public functions are usable without the web app so the demo can be run
from a terminal. Cloud AI, speech, ASR, Demucs, and FFmpeg integrations are
optional and are loaded only when a mode needs them. API keys belong in
environment variables; see ``.env.example``.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import re
import sys
import tempfile
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Coroutine, TypeVar

from config import OUTPUT_DIR, VOICE_MAP, language_config
from pipeline.asr import transcribe
from pipeline.code_mixing import code_mix_text
from pipeline.demux import extract_audio, separate_stems
from pipeline.remux import burn_captions, remux_video
from pipeline.transcreation import OFFLINE_IDIOMS, transcreate
from pipeline.tts import synthesize
from utils.subtitles import SubtitleSegment, write_subtitles


T = TypeVar("T")


def _safe_stem(value: str, fallback: str = "dubx") -> str:
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", value).strip("_")
    return stem[:60] or fallback


def text_to_text_dub(text: str, target_language: str = "hindi", api_key: str | None = None, duration_seconds: float | None = None) -> dict[str, Any]:
    """Mode 1: translate English text into colloquial regional speech."""

    if not text or not text.strip():
        raise ValueError("Text input cannot be empty")
    config = language_config(target_language)
    result = transcreate(text, target_language, api_key=api_key, duration_seconds=duration_seconds)
    budget_obj = result.get("budget")
    budget_dict = asdict(budget_obj) if is_dataclass(budget_obj) else budget_obj
    return {
        "pillar": "Text-to-Text",
        "original_text": text,
        "target_language": config["name"],
        "detected_intent": result["detected_intent"],
        "transcreated_text": result["transcreated_text"],
        "explanation": result["explanation"],
        "budget": budget_dict,
        "engine": result.get("engine"),
    }


def dual_language_code_mix(
    text: str,
    primary_language: str = "hindi",
    secondary_language: str = "english",
    intensity: int = 2,
    script: str = "native",
    api_key: str | None = None,
    duration_seconds: float | None = None,
) -> dict[str, Any]:
    """Generate a culturally natural blend of any two configured languages."""

    if not text or not text.strip():
        raise ValueError("Text input cannot be empty")
    res = code_mix_text(
        text,
        primary_language=primary_language,
        secondary_language=secondary_language,
        intensity=int(intensity),
        script=script,
        api_key=api_key,
        duration_seconds=duration_seconds,
    )
    if is_dataclass(res.get("budget")):
        res["budget"] = asdict(res["budget"])
    return res


def text_to_audio_dub(text: str, target_language: str = "hindi", gender: str = "male", output_path: str | None = None, api_key: str | None = None, rate: str = "+0%") -> dict[str, Any]:
    """Mode 2: transcreate text and synthesize a regional MP3."""

    config = language_config(target_language)
    result = text_to_text_dub(text, target_language, api_key=api_key)
    if not output_path:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = str(OUTPUT_DIR / f"t2a_{_safe_stem(text[:30])}_{target_language.lower()}.mp3")
    gender_resolved = gender if gender in {"male", "female"} else "male"
    synth_res = synthesize(result["transcreated_text"], target_language, gender_resolved, output_path, rate=rate)
    voice = synth_res.get("voice_used") if isinstance(synth_res, dict) else config.get(gender_resolved, config.get("default", config["male"]))
    return {
        **result,
        "pillar": "Text-to-Audio",
        "voice_used": voice,
        "audio_path": output_path,
        "output_audio_path": output_path,
    }


def _translated_segments(segments: list[SubtitleSegment], target_language: str, api_key: str | None) -> tuple[list[SubtitleSegment], str]:
    translated: list[SubtitleSegment] = []
    for segment in segments:
        result = transcreate(segment.text, target_language, api_key=api_key, duration_seconds=max(0.1, segment.end - segment.start))
        translated.append(SubtitleSegment(segment.start, segment.end, segment.text, result["transcreated_text"]))
    return translated, " ".join(item.translated_text for item in translated).strip()


def _resolve_audio_file(audio_path: Any) -> Path:
    if isinstance(audio_path, dict):
        audio_path = audio_path.get("path") or audio_path.get("name")
    elif isinstance(audio_path, tuple) and len(audio_path) == 2:
        from app import _normalize_audio
        audio_path = _normalize_audio(audio_path)
    if not audio_path or not str(audio_path).strip():
        raise ValueError("Input audio path cannot be empty")
    source = Path(str(audio_path).strip())
    if not source.is_file():
        raise FileNotFoundError(f"Input audio file not found: {audio_path}")
    return source


def _resolve_video_file(video_path: Any) -> Path:
    if isinstance(video_path, dict):
        v = video_path.get("video")
        video_path = v.get("path") if isinstance(v, dict) else (video_path.get("path") or video_path.get("name"))
    if not video_path or not str(video_path).strip():
        raise ValueError("Input video path cannot be empty")
    source = Path(str(video_path).strip())
    if not source.is_file():
        raise FileNotFoundError(f"Input video file not found: {video_path}")
    return source


def audio_to_audio_dub(
    audio_path: str | Any,
    target_language: str = "hindi",
    gender: str = "auto",
    output_path: str | None = None,
    api_key: str | None = None,
    rate: str = "+0%",
    clone_voice: bool = True,
) -> dict[str, Any]:
    """Mode 3: timestamped ASR, transcreation, and regional speech synthesis."""

    source = _resolve_audio_file(audio_path)
    config = language_config(target_language)

    segments = transcribe(str(source), api_key=api_key)
    if not segments:
        raise ValueError("No speech detected in input audio")
    localized_segments, localized_text = _translated_segments(segments, target_language, api_key)
    if not localized_text.strip():
        raise ValueError("Transcreation resulted in empty text")
    if not output_path:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        output_path = str(OUTPUT_DIR / f"a2a_{_safe_stem(source.stem)}_{target_language.lower()}.mp3")

    synth_res = synthesize(
        localized_text,
        target_language,
        gender=gender,
        output_path=output_path,
        rate=rate,
        reference_audio=str(source),
        clone_voice=clone_voice,
    )
    if isinstance(synth_res, dict):
        output_path = synth_res.get("output_path", output_path)
        voice = synth_res.get("voice_used") or config.get(gender.lower(), config.get("default", config["male"]))
        cloned = synth_res.get("cloned_voice", clone_voice)
        speaker_f0 = synth_res.get("f0_hz")
        pitch_offset = synth_res.get("pitch_offset", "+0Hz")
        detected_gender = synth_res.get("detected_gender")
        gender_used = synth_res.get("gender_used", gender)
    else:
        voice = config.get(gender.lower(), config.get("default", config["male"]))
        cloned = clone_voice
        speaker_f0 = None
        pitch_offset = "+0Hz"
        detected_gender = None
        gender_used = gender

    return {
        "pillar": "Audio-to-Audio",
        "input_audio_path": str(source),
        "transcribed_source": " ".join(segment.text for segment in segments),
        "target_language": config["name"],
        "voice_used": voice,
        "transcreated_text": localized_text,
        "segments": localized_segments,
        "output_audio_path": output_path,
        "audio_path": output_path,
        "cloned_voice": cloned,
        "voice_cloned": cloned,
        "speaker_f0_hz": speaker_f0,
        "f0_hz": speaker_f0,
        "pitch_offset": pitch_offset,
        "detected_gender": detected_gender,
        "gender_used": gender_used,
    }


def _mix_bgm(bgm_path: str, voice_path: str, output_path: str) -> str:
    """Duck BGM during speech and normalize the mastered mix."""

    import shutil
    import subprocess

    if not shutil.which("ffmpeg"):
        return voice_path
    filter_graph = (
        "[0:a][1:a]sidechaincompress=threshold=0.03:ratio=8:attack=20:release=300:makeup=0[ducked];"
        "[ducked][1:a]amix=inputs=2:duration=longest:normalize=0,loudnorm=I=-14:TP=-1.5:LRA=11[a]"
    )
    subprocess.run(["ffmpeg", "-y", "-i", bgm_path, "-i", voice_path, "-filter_complex", filter_graph, "-map", "[a]", "-ar", "48000", output_path], check=True, capture_output=True)
    return output_path


def video_to_video_dub(
    video_path: str | Any,
    target_language: str = "hindi",
    gender: str = "auto",
    output_path: str | None = None,
    burn_subtitles: bool = False,
    api_key: str | None = None,
    rate: str = "+0%",
    clone_voice: bool = True,
) -> dict[str, Any]:
    """Mode 4/5: preserve video frames, create a dual-track dub, and optionally burn captions."""

    source = _resolve_video_file(video_path)
    config = language_config(target_language)
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    base = _safe_stem(source.stem)

    with tempfile.TemporaryDirectory(prefix="dubx_", dir=OUTPUT_DIR) as temp_dir:
        temp = Path(temp_dir)
        extracted_audio = extract_audio(str(source), str(temp / "source.wav"))
        vocals, bgm = separate_stems(extracted_audio, str(temp / "stems"))

        reference_audio = vocals or extracted_audio
        segments = transcribe(reference_audio, api_key=api_key)
        if not segments:
            raise ValueError("No speech detected in video audio track")
        localized_segments, localized_text = _translated_segments(segments, target_language, api_key)
        if not localized_text.strip():
            raise ValueError("Transcreation resulted in empty text")

        dubbed_audio = str(OUTPUT_DIR / f"dubbed_{base}_{target_language.lower()}.mp3")
        synth_res = synthesize(
            localized_text,
            target_language,
            gender=gender,
            output_path=dubbed_audio,
            rate=rate,
            reference_audio=reference_audio,
            clone_voice=clone_voice,
        )
        if isinstance(synth_res, dict):
            dubbed_audio = synth_res.get("output_path", dubbed_audio)
            voice = synth_res.get("voice_used") or config.get(gender.lower(), config.get("default", config["male"]))
            cloned = synth_res.get("cloned_voice", clone_voice)
            speaker_f0 = synth_res.get("f0_hz")
            pitch_offset = synth_res.get("pitch_offset", "+0Hz")
            detected_gender = synth_res.get("detected_gender")
            gender_used = synth_res.get("gender_used", gender)
        else:
            voice = config.get(gender.lower(), config.get("default", config["male"]))
            cloned = clone_voice
            speaker_f0 = None
            pitch_offset = "+0Hz"
            detected_gender = None
            gender_used = gender

        mastered_audio = dubbed_audio
        if bgm:
            mastered_audio = _mix_bgm(bgm, dubbed_audio, str(OUTPUT_DIR / f"mastered_{base}_{target_language.lower()}.wav"))

        srt_path = str(OUTPUT_DIR / f"{base}_{target_language.lower()}.srt")
        vtt_path = str(OUTPUT_DIR / f"{base}_{target_language.lower()}.vtt")
        write_subtitles(localized_segments, srt_path, vtt_path, bilingual=False)

        if not output_path:
            suffix = "with_captions" if burn_subtitles else "clean"
            output_path = str(OUTPUT_DIR / f"v2v_{base}_{target_language.lower()}_{suffix}.mp4")
        if burn_subtitles:
            final_video = burn_captions(str(source), mastered_audio, srt_path, output_path)
        else:
            final_video = remux_video(str(source), mastered_audio, output_path, original_audio=extracted_audio, language_code=config["code"])

    return {
        "pillar": "Video-to-Video + Captions" if burn_subtitles else "Video-to-Video",
        "input_video_path": str(source),
        "transcribed_source": " ".join(segment.text for segment in segments),
        "target_language": config["name"],
        "voice_used": voice,
        "transcreated_text": localized_text,
        "segments": localized_segments,
        "dubbed_audio_path": dubbed_audio,
        "subtitle_path": srt_path,
        "vtt_path": vtt_path,
        "burned_captions": burn_subtitles,
        "output_video_path": final_video,
        "bgm_preserved": bool(bgm),
        "audio_tracks": ["English (Original)", f"{config['name']} (Dubbed)"],
        "cloned_voice": cloned,
        "voice_cloned": cloned,
        "speaker_f0_hz": speaker_f0,
        "f0_hz": speaker_f0,
        "pitch_offset": pitch_offset,
        "detected_gender": detected_gender,
        "gender_used": gender_used,
    }


def _print_result(result: dict[str, Any]) -> None:
    print(f"Mode:              {result.get('pillar')}")
    for key in (
        "original_text",
        "target_language",
        "detected_intent",
        "transcreated_text",
        "voice_used",
        "cloned_voice",
        "speaker_f0_hz",
        "pitch_offset",
        "audio_path",
        "output_audio_path",
        "subtitle_path",
        "output_video_path",
    ):
        if result.get(key) is not None:
            print(f"{key.replace('_', ' ').title()+':':20} {result[key]}")


def main() -> None:
    # Windows terminals commonly default to cp1252 while Indic output is part
    # of the product demo. Keep the CLI readable without requiring a shell
    # reconfiguration from the user.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description="DubX: regional AI dubbing suite")
    parser.add_argument("--mode", required=True, choices=["t2t", "mix", "t2a", "a2a", "v2v", "v2v_caption"])
    parser.add_argument("--input", required=True, help="Text, audio/video path, or URL resolved by the app layer")
    parser.add_argument("--lang", default="hindi", choices=sorted(VOICE_MAP))
    parser.add_argument("--gender", default="auto", choices=["auto", "male", "female"])
    parser.add_argument("--no-clone", action="store_true", help="Disable voice cloning")
    parser.add_argument("--output", default=None)
    parser.add_argument("--caption", action="store_true", help="Burn captions for v2v")
    parser.add_argument("--rate", default="+0%")
    parser.add_argument("--primary", default="hindi", choices=sorted(VOICE_MAP), help="Primary language for --mode mix")
    parser.add_argument("--secondary", default="english", choices=sorted(VOICE_MAP), help="Secondary language for --mode mix")
    parser.add_argument("--intensity", type=int, default=2, choices=[1, 2, 3], help="Code-mixing intensity: 1=15%%, 2=30%%, 3=50%%")
    parser.add_argument("--script", default="native", choices=["native", "romanized", "dual"], help="Code-mix output script")
    args = parser.parse_args()

    if args.mode == "t2t":
        result = text_to_text_dub(args.input, args.lang)
    elif args.mode == "mix":
        result = dual_language_code_mix(args.input, args.primary, args.secondary, args.intensity, args.script)
    elif args.mode == "t2a":
        result = text_to_audio_dub(args.input, args.lang, args.gender, args.output, rate=args.rate)
    elif args.mode == "a2a":
        result = audio_to_audio_dub(args.input, args.lang, args.gender, args.output, rate=args.rate, clone_voice=not args.no_clone)
    else:
        result = video_to_video_dub(args.input, args.lang, args.gender, args.output, burn_subtitles=args.mode == "v2v_caption" or args.caption, rate=args.rate, clone_voice=not args.no_clone)
    print("\n" + "=" * 72)
    print("DUBX ENGINE COMPLETE")
    _print_result(result)
    print("=" * 72)


if __name__ == "__main__":
    main()
