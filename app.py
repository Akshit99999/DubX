"""DubX Studio + Live Gradio application.

The UI is optional so the CLI remains usable in a minimal Python environment.
Run with ``python app.py`` after installing the requirements in
``requirements.txt``.
"""

from __future__ import annotations

import os
from pathlib import Path

from typing import Any

try:
    import gradio as gr
except ImportError:
    gr = None
from config import OUTPUT_DIR, VOICE_MAP
from dubx_core import audio_to_audio_dub, dual_language_code_mix, text_to_text_dub, video_to_video_dub
from utils.ingestion import resolve_input


def _ui_error(message: str) -> Exception:
    return gr.Error(message) if gr is not None else ValueError(message)


def _normalize_audio(audio_file: Any) -> str:
    """Normalize any Gradio audio input (filepath, tuple, or dict) to a local wav file path."""
    if audio_file is None:
        raise _ui_error("Record or upload an audio clip first")
    if isinstance(audio_file, dict):
        path = audio_file.get("path") or audio_file.get("name")
        if not path:
            raise _ui_error("Invalid audio data received")
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
        raise _ui_error("Unsupported audio array format")
    if isinstance(audio_file, (str, Path)):
        s = str(audio_file).strip()
        if not s:
            raise _ui_error("Audio path cannot be empty")
        return s
    raise _ui_error(f"Unsupported audio input type: {type(audio_file)}")


def process_studio(
    video_file: Any,
    video_url: str,
    language: str,
    gender: str,
    dialect: int,
    burn_captions: bool,
    voice_mode: str,
    voice_clone_consent: bool,
    source_language: str,
):
    """Gradio callback for local upload, browser recording, or URL ingestion."""

    if isinstance(video_file, dict):
        v = video_file.get("video")
        video_file = v.get("path") if isinstance(v, dict) else (video_file.get("path") or video_file.get("name"))

    url = video_url.strip() if isinstance(video_url, str) else ""
    source = video_file or url
    if not source:
        raise _ui_error("Upload a video/recording or paste a video URL")
    clone_voice = voice_mode == "Clone original speaker with Sarvam"
    if clone_voice and not voice_clone_consent:
        raise _ui_error("Confirm that you have the right to clone this speaker before continuing.")
    try:
        local_source = resolve_input(source, OUTPUT_DIR)
        result = video_to_video_dub(
            local_source,
            target_language=language,
            gender=gender,
            burn_subtitles=burn_captions,
            clone_voice=clone_voice,
            voice_clone_consent=voice_clone_consent,
            source_language=source_language,
            dialect_level=int(dialect),
        )
    except Exception as exc:
        raise _ui_error(str(exc)) from exc

    if result.get("voice_cloned"):
        clone_info = f"Speaker identity: preserved by Sarvam ({result.get('clone_method', 'source-speaker clone')}). "
    else:
        clone_info = f"Speaker identity: preset voice only ({result.get('voice_used', 'N/A')}). "

    return result["output_video_path"], result["dubbed_audio_path"], result["subtitle_path"], (
        f"Completed {result['target_language']} dubbing. "
        f"{clone_info}"
        f"BGM preserved: {'yes' if result['bgm_preserved'] else 'Demucs unavailable; original audio retained as a separate track'}. "
        f"Dialect level: {dialect}."
    )


def process_audio(audio_file: Any, language: str, gender: str, voice_mode: str, voice_clone_consent: bool, source_language: str):
    """Audio-to-Audio dubbing callback for uploaded audio files or microphone recordings."""

    normalized_path = _normalize_audio(audio_file)
    clone_voice = voice_mode == "Clone original speaker with Sarvam"
    if clone_voice and not voice_clone_consent:
        raise _ui_error("Confirm that you have the right to clone this speaker before continuing.")
    try:
        result = audio_to_audio_dub(normalized_path, target_language=language, gender=gender, clone_voice=clone_voice, voice_clone_consent=voice_clone_consent, source_language=source_language)
    except Exception as exc:
        raise _ui_error(str(exc)) from exc

    lang = result.get("target_language", language)
    if clone_voice:
        status_msg = f"✅ Dubbed into {lang} with Sarvam source-speaker preservation."
    else:
        status_msg = f"✅ Dubbed into {lang} using {result.get('voice_used', 'Sarvam preset voice')}."
    return result["output_audio_path"], result.get("transcribed_source", ""), result["transcreated_text"], status_msg


def build_app():
    if gr is None:
        raise RuntimeError("Gradio is not installed. Install the UI dependencies with: pip install -r requirements.txt")

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
                    source_language = gr.Dropdown(matrix_languages, value="english", label="Source language")
                    voice_mode = gr.Radio(["Sarvam preset voice", "Clone original speaker with Sarvam"], value="Sarvam preset voice", label="Voice mode")
                    voice_clone_consent = gr.Checkbox(label="I have permission to clone and use this speaker's voice", value=False)
                    gender = gr.Radio(["auto", "male", "female"], value="auto", label="Voice / Gender", info="auto detects speaker gender")
                    dialect = gr.Slider(1, 3, value=2, step=1, label="Dialect / register", info="1 formal · 2 conversational · 3 street slang")
                    burn = gr.Checkbox(label="Burn regional captions into the video", value=False)
                    run = gr.Button("Dub video", variant="primary")
                with gr.Column():
                    output_video = gr.Video(label="Dubbed video")
                    output_audio = gr.Audio(label="Localized audio", type="filepath")
                    output_srt = gr.File(label="Translated subtitles (.srt)")
                    status = gr.Markdown()
            run.click(process_studio, [video_file, video_url, language, gender, dialect, burn, voice_mode, voice_clone_consent, source_language], [output_video, output_audio, output_srt, status])

        with gr.Tab("🎧 Audio mode (A2A)"):
            gr.Markdown("Upload an audio file (`.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`) or record speech from your microphone for complete ASR → Transcreation → Regional Voice Dubbing.")
            with gr.Row():
                with gr.Column():
                    audio_input = gr.Audio(sources=["upload", "microphone"], type="filepath", label="Choose Audio File (.mp3, .wav, .m4a) or Record Microphone")
                    with gr.Row():
                        audio_source_language = gr.Dropdown(matrix_languages, value="english", label="Source language")
                        audio_language = gr.Dropdown(languages, value="hindi", label="Target language")
                        audio_gender = gr.Radio(["auto", "male", "female"], value="auto", label="Voice / Gender", info="auto detects speaker gender")
                    audio_voice_mode = gr.Radio(["Sarvam preset voice", "Clone original speaker with Sarvam"], value="Sarvam preset voice", label="Voice mode")
                    audio_voice_clone_consent = gr.Checkbox(label="I have permission to clone and use this speaker's voice", value=False)
                    audio_run = gr.Button("Dub Audio", variant="primary")
                with gr.Column():
                    output_dubbed_audio = gr.Audio(label="Dubbed Regional Audio", type="filepath")
                    transcribed_box = gr.Textbox(label="Transcribed Original Speech", lines=2)
                    transcreated_box = gr.Textbox(label="Transcreated Regional Translation", lines=2)
                    audio_status = gr.Markdown()
            audio_run.click(process_audio, [audio_input, audio_language, audio_gender, audio_voice_mode, audio_voice_clone_consent, audio_source_language], [output_dubbed_audio, transcribed_box, transcreated_box, audio_status])

        with gr.Tab("📝 Text demo"):
            with gr.Row():
                with gr.Column():
                    text_input = gr.Textbox(value="Don't put all your eggs in one basket", label="English text", lines=3)
                    text_language = gr.Dropdown(languages, value="hindi", label="Target language")
                    text_dialect = gr.Slider(1, 3, value=2, step=1, label="Dialect / register", info="1 formal · 2 conversational · 3 street slang")
                    text_run = gr.Button("Transcreate", variant="primary")
                with gr.Column():
                    transcreated_text = gr.Textbox(label="Transcreated text", lines=2)
                    detected_intent = gr.Textbox(label="Detected cultural meaning / intent", lines=2)
                    explanation = gr.Textbox(label="Cultural translation rationale", lines=2)
                    with gr.Accordion("Developer details & raw JSON", open=False):
                        text_output = gr.JSON(label="Full Payload")

            def _handle_text_dub(text, lang, dialect):
                res = text_to_text_dub(text, lang, dialect_level=int(dialect))
                return res["transcreated_text"], res["detected_intent"], res["explanation"], res

            text_run.click(_handle_text_dub, [text_input, text_language, text_dialect], [transcreated_text, detected_intent, explanation, text_output])

        with gr.Tab("🌐 Code-mix matrix"):
            gr.Markdown("Blend any two languages with a controllable vernacular intensity and native/romanized output.")
            with gr.Row():
                with gr.Column():
                    mix_input = gr.Textbox(value="Don't put all your eggs in one basket", label="English source text", lines=3)
                    with gr.Row():
                        mix_primary = gr.Dropdown(matrix_languages, value="hindi", label="Primary language (A)")
                        mix_secondary = gr.Dropdown(matrix_languages, value="punjabi", label="Secondary language (B)")
                    with gr.Row():
                        mix_intensity = gr.Slider(1, 3, value=2, step=1, label="Code-mixing intensity", info="1: 15% · 2: 30% · 3: 50% secondary language")
                        mix_script = gr.Dropdown(["native", "romanized", "dual"], value="native", label="Script output")
                    mix_run = gr.Button("Generate blended dubbing text", variant="primary")
                with gr.Column():
                    blended_output = gr.Textbox(label="Blended dubbing text", lines=2)
                    blended_style = gr.Textbox(label="Style & dialect pair", lines=1)
                    with gr.Accordion("Developer details & raw JSON", open=False):
                        mix_output = gr.JSON(label="Full Payload")

            def _handle_mix(text, prim, sec, intensity, script):
                res = dual_language_code_mix(text, prim, sec, intensity, script)
                return res["transcreated_text"], res.get("style", f"{prim} + {sec}"), res

            mix_run.click(_handle_mix, [mix_input, mix_primary, mix_secondary, mix_intensity, mix_script], [blended_output, blended_style, mix_output])
    return demo


if __name__ == "__main__":
    build_app().launch(
        server_name=os.getenv("DUBX_HOST", "127.0.0.1"),
        server_port=int(os.getenv("DUBX_PORT", "7860")),
        theme=gr.themes.Soft(),
    )
