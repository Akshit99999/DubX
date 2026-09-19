"""DubX Studio + Live Gradio application.

The UI is optional so the CLI remains usable in a minimal Python environment.
Run with ``python app.py`` after installing the requirements in
``requirements.txt``.
"""

from __future__ import annotations

import os
from pathlib import Path

from typing import Any

import gradio as gr
from config import OUTPUT_DIR, VOICE_MAP
from dubx_core import audio_to_audio_dub, dual_language_code_mix, text_to_text_dub, video_to_video_dub
from utils.ingestion import resolve_input


def _normalize_audio(audio_file: Any) -> str:
    """Normalize any Gradio audio input (filepath, tuple, or dict) to a local wav file path."""
    if audio_file is None:
        raise gr.Error("Record or upload an audio clip first")
    if isinstance(audio_file, dict):
        path = audio_file.get("path") or audio_file.get("name")
        if not path:
            raise gr.Error("Invalid audio data received")
        return str(path)
    if isinstance(audio_file, tuple) and len(audio_file) == 2:
        sr, data = audio_file
        import tempfile
        import wave
        import numpy as np

        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        temp_file = tempfile.NamedTemporaryFile(suffix=".wav", dir=OUTPUT_DIR, delete=False)
        temp_path = temp_file.name
        temp_file.close()

        if isinstance(data, np.ndarray):
            if np.issubdtype(data.dtype, np.floating):
                data = np.clip(data, -1.0, 1.0)
                data = (data * 32767).astype(np.int16)
            elif data.dtype == np.int32:
                data = (data / 65536).astype(np.int16)
            elif data.dtype != np.int16:
                data = data.astype(np.int16)
            channels = 1 if data.ndim == 1 else data.shape[1]
            with wave.open(temp_path, "wb") as wf:
                wf.setnchannels(channels)
                wf.setsampwidth(2)
                wf.setframerate(int(sr))
                wf.writeframes(data.tobytes())
            return temp_path
        raise gr.Error("Unsupported audio array format")
    if isinstance(audio_file, (str, Path)):
        s = str(audio_file).strip()
        if not s:
            raise gr.Error("Audio path cannot be empty")
        return s
    raise gr.Error(f"Unsupported audio input type: {type(audio_file)}")


def process_studio(video_file: Any, video_url: str, language: str, gender: str, dialect: int, burn_captions: bool):
    """Gradio callback for local upload, browser recording, or URL ingestion."""

    if isinstance(video_file, dict):
        v = video_file.get("video")
        video_file = v.get("path") if isinstance(v, dict) else (video_file.get("path") or video_file.get("name"))

    url = video_url.strip() if isinstance(video_url, str) else ""
    source = video_file or url
    if not source:
        raise gr.Error("Upload a video/recording or paste a video URL")
    try:
        local_source = resolve_input(source, OUTPUT_DIR)
        result = video_to_video_dub(local_source, target_language=language, gender=gender, burn_subtitles=burn_captions)
    except Exception as exc:
        raise gr.Error(str(exc)) from exc

    return result["output_video_path"], result["dubbed_audio_path"], result["subtitle_path"], (
        f"Completed {result['target_language']} dubbing. "
        f"BGM preserved: {'yes' if result['bgm_preserved'] else 'Demucs unavailable; original audio retained as a separate track'}. "
        f"Dialect level: {dialect}."
    )


def process_live(audio_file: Any, language: str, gender: str):
    """Batch fallback for the Live tab; it uses the same engine on a mic clip."""

    normalized_path = _normalize_audio(audio_file)
    try:
        result = audio_to_audio_dub(normalized_path, target_language=language, gender=gender)
    except Exception as exc:
        raise gr.Error(str(exc)) from exc
    return result["output_audio_path"], result["transcreated_text"]


def build_app():
    try:
        import gradio as gr
    except ImportError as exc:
        raise RuntimeError("Gradio is not installed. Install the UI dependencies with: pip install -r requirements.txt") from exc

    languages = sorted(VOICE_MAP)
    matrix_languages = [name for name in languages if name not in {"hinglish", "tanglish", "tenglish"}]
    with gr.Blocks(title="DubX Regional Dubbing Studio") as demo:
        gr.Markdown("# DubX\nRegional AI dubbing with a simple 3-input → 3-output workflow.")
        with gr.Tab("🎬 Studio mode"):
            with gr.Row():
                with gr.Column():
                    video_file = gr.Video(label="Upload or record video", sources=["upload", "webcam"])
                    video_url = gr.Textbox(label="Or paste a video URL", placeholder="https://...")
                    language = gr.Dropdown(languages, value="hindi", label="Target language")
                    gender = gr.Radio(["male", "female"], value="male", label="Voice")
                    dialect = gr.Slider(1, 3, value=2, step=1, label="Dialect / register", info="1 formal · 2 conversational · 3 street slang")
                    burn = gr.Checkbox(label="Burn regional captions into the video", value=False)
                    run = gr.Button("Dub video", variant="primary")
                with gr.Column():
                    output_video = gr.Video(label="Dubbed video")
                    output_audio = gr.Audio(label="Localized audio", type="filepath")
                    output_srt = gr.File(label="Translated subtitles (.srt)")
                    status = gr.Markdown()
            run.click(process_studio, [video_file, video_url, language, gender, dialect, burn], [output_video, output_audio, output_srt, status])

        with gr.Tab("🎙️ Live mode"):
            gr.Markdown("Record a short microphone clip for the shared ASR → transcreation → TTS cascade.")
            live_input = gr.Audio(sources=["microphone", "upload"], type="filepath", label="Microphone")
            with gr.Row():
                live_language = gr.Dropdown(languages, value="hindi", label="Target language")
                live_gender = gr.Radio(["male", "female"], value="male", label="Voice")
            live_run = gr.Button("Dub clip", variant="primary")
            live_output = gr.Audio(label="Localized audio", type="filepath")
            live_text = gr.Textbox(label="Transcreated text")
            live_run.click(process_live, [live_input, live_language, live_gender], [live_output, live_text])

        with gr.Tab("📝 Text demo"):
            text_input = gr.Textbox(value="Don't put all your eggs in one basket", label="English text")
            text_language = gr.Dropdown(languages, value="hindi", label="Target language")
            text_run = gr.Button("Transcreate")
            text_output = gr.JSON(label="Result")
            text_run.click(lambda text, language: text_to_text_dub(text, language), [text_input, text_language], text_output)

        with gr.Tab("🌐 Code-mix matrix"):
            gr.Markdown("Blend any two languages with a controllable vernacular intensity and native/romanized output.")
            mix_input = gr.Textbox(value="Don't put all your eggs in one basket", label="English source text")
            with gr.Row():
                mix_primary = gr.Dropdown(matrix_languages, value="hindi", label="Primary language (A)")
                mix_secondary = gr.Dropdown(matrix_languages, value="punjabi", label="Secondary language (B)")
                mix_intensity = gr.Slider(1, 3, value=2, step=1, label="Code-mixing intensity", info="1: 15% · 2: 30% · 3: 50% secondary language")
                mix_script = gr.Dropdown(["native", "romanized", "dual"], value="native", label="Script output")
            mix_run = gr.Button("Generate blended dubbing text", variant="primary")
            mix_output = gr.JSON(label="Dual-language result")
            mix_run.click(dual_language_code_mix, [mix_input, mix_primary, mix_secondary, mix_intensity, mix_script], mix_output)
    return demo


if __name__ == "__main__":
    build_app().launch(
        server_name=os.getenv("DUBX_HOST", "127.0.0.1"),
        server_port=int(os.getenv("DUBX_PORT", "7860")),
        theme=gr.themes.Soft()
    )
