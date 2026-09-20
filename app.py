"""DubX Studio + Live Gradio application.

The UI is optional so the CLI remains usable in a minimal Python environment.
Run with ``python app.py`` after installing the requirements in
``requirements.txt``.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path

from typing import Any

try:
    import gradio as gr
except ImportError:
    gr = None
from config import OUTPUT_DIR, VOICE_MAP
from dubx_core import audio_to_audio_dub, text_to_audio_dub, text_to_text_dub, video_to_video_dub
from utils.ingestion import resolve_input


def _ui_error(message: str) -> Exception:
    return gr.Error(message) if gr is not None else ValueError(message)


def _configure_gradio_video_probe() -> None:
    """Keep an MP4 result displayable when Gradio's optional ffprobe is absent.

    Gradio invokes ``ffprobe`` just to decide whether an output needs converting.
    The project supplies an MP4 result already, but ``ffprobe`` is not included
    with imageio-ffmpeg on some Windows installs; Gradio otherwise turns this
    optional inspection failure into a failed request after dubbing completed.
    """

    if gr is None or shutil.which("ffprobe"):
        return
    from gradio import processing_utils

    original = processing_utils.video_is_playable
    if getattr(original, "_dubx_safe_probe", False):
        return

    def safe_video_is_playable(path: str) -> bool:
        try:
            return original(path)
        except Exception:
            # Output is an MP4.  Let the browser attempt playback rather than
            # failing the successful dubbing job because a probe is missing.
            return Path(path).suffix.lower() == ".mp4"

    safe_video_is_playable._dubx_safe_probe = True  # type: ignore[attr-defined]
    processing_utils.video_is_playable = safe_video_is_playable


def _make_result_video_probe_safe(component: Any) -> None:
    """Avoid Gradio's ffprobe-only post-processing for our MP4 output.

    This per-component guard is intentionally separate from the global safety
    wrapper above. It protects the completed result even on Gradio releases
    that retain a direct reference to the original probe helper.
    """

    if shutil.which("ffprobe"):
        return
    from gradio.data_classes import FileData

    original = component._format_video

    def format_result_video(video: str | Path | None):
        if video is not None and Path(str(video)).suffix.lower() == ".mp4":
            return FileData(path=str(video), orig_name=Path(str(video)).name)
        return original(video)

    component._format_video = format_result_video


def _make_result_audio_probe_safe(component: Any) -> None:
    """Return the generated WAV without Gradio's optional ffprobe inspection."""

    if shutil.which("ffprobe"):
        return
    from gradio.data_classes import FileData

    original = component.postprocess

    def postprocess_result_audio(value: Any):
        if isinstance(value, (str, Path)) and Path(str(value)).suffix.lower() == ".wav":
            return FileData(path=str(value), orig_name=Path(str(value)).name)
        return original(value)

    component.postprocess = postprocess_result_audio


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
    dialect: int,
    burn_captions: bool,
    source_language: str,
    code_mix_enabled: bool,
    code_mix_secondary: str,
    code_mix_intensity: int,
    progress: Any = gr.Progress(track_tqdm=True) if gr is not None else None,
):
    """Gradio callback for local upload, browser recording, or URL ingestion."""

    def show_progress(event: dict[str, Any]) -> None:
        if progress is None:
            return
        value = event.get("progress")
        description = event.get("message") or "Processing video…"
        if value is None:
            progress(None, desc=description)
        else:
            progress(min(1.0, max(0.0, float(value))), desc=description)

    if isinstance(video_file, dict):
        v = video_file.get("video")
        video_file = v.get("path") if isinstance(v, dict) else (video_file.get("path") or video_file.get("name"))

    url = video_url.strip() if isinstance(video_url, str) else ""
    source = video_file or url
    if not source:
        raise _ui_error("Upload a video/recording or paste a video URL")
    try:
        show_progress({"message": "Checking video source…", "progress": 0.01})
        local_source = resolve_input(source, OUTPUT_DIR, progress_callback=show_progress)
        result = video_to_video_dub(
            local_source,
            target_language=language,
            gender="auto",
            burn_subtitles=burn_captions,
            clone_voice=True,
            voice_clone_consent=True,
            source_language=source_language,
            dialect_level=int(dialect),
            num_speakers=-1,
            code_mix_enabled=bool(code_mix_enabled),
            code_mix_secondary=code_mix_secondary,
            code_mix_intensity=int(code_mix_intensity),
            progress_callback=show_progress,
        )
    except Exception as exc:
        raise _ui_error(str(exc)) from exc

    clone_info = f"Speaker identity: preserved independently by Sarvam ({result.get('clone_method', 'source-speaker clone')}). "
    mix_info = " Code-mixed conversational register enabled." if code_mix_enabled else ""

    return result["output_video_path"], result["dubbed_audio_path"], result["subtitle_path"], (
        f"Completed {result['target_language']} dubbing. "
        f"{clone_info}"
        "Speakers are auto-detected and cloned independently. "
        f"BGM preserved: {'yes' if result['bgm_preserved'] else 'Demucs unavailable; original audio retained as a separate track'}. "
        f"Dialect level: {dialect}.{mix_info}"
    )


def process_audio(audio_file: Any, language: str, source_language: str):
    """Audio-to-Audio dubbing callback for uploaded audio files or microphone recordings."""

    normalized_path = _normalize_audio(audio_file)
    try:
        result = audio_to_audio_dub(normalized_path, target_language=language, gender="auto", clone_voice=True, voice_clone_consent=True, source_language=source_language, num_speakers=-1)
    except Exception as exc:
        raise _ui_error(str(exc)) from exc

    lang = result.get("target_language", language)
    status_msg = f"✅ Dubbed into {lang} with independent source-speaker preservation."
    return result["output_audio_path"], result.get("transcribed_source", ""), result["transcreated_text"], status_msg


def build_app():
    if gr is None:
        raise RuntimeError("Gradio is not installed. Install the UI dependencies with: pip install -r requirements.txt")

    _configure_gradio_video_probe()

    languages = sorted(VOICE_MAP)
    matrix_languages = [name for name in languages if name not in {"hinglish", "tanglish", "tenglish"}]
    with gr.Blocks(title="DubX Regional Dubbing Studio") as demo:
        gr.Markdown("# DubX\nRegional AI dubbing with a simple 3-input → 3-output workflow.")
        with gr.Tab("🎬 Studio mode"):
            with gr.Row():
                with gr.Column():
                    video_file = gr.Video(label="Upload or record video", sources=["upload", "webcam"])
                    video_url = gr.Textbox(label="Or paste a YouTube video or Short URL", placeholder="https://www.youtube.com/watch?v=… or https://www.youtube.com/shorts/…")
                    language = gr.Dropdown(languages, value="hindi", label="Target language")
                    source_language = gr.Dropdown(matrix_languages, value="english", label="Source language")
                    gr.Markdown("**Original-speaker dubbing** — every detected speaker is cloned independently; no preset voices are used.")
                    dialect = gr.Slider(1, 3, value=2, step=1, label="Dialect / register", info="1 formal · 2 conversational · 3 street slang")
                    code_mix_enabled = gr.Checkbox(label="Mix a second language into the dub", value=False, info="Creates both source-voice dubs and replaces selected timed cues with the second language.")
                    with gr.Group(visible=False) as code_mix_options:
                        code_mix_secondary = gr.Dropdown([item for item in matrix_languages if item != "hindi"], value="english", label="Second language")
                        code_mix_intensity = gr.Slider(1, 3, value=2, step=1, label="Code-mixing intensity", info="1 light · 2 balanced · 3 frequent")
                    burn = gr.Checkbox(label="Burn translated captions aligned to the dubbed audio", value=True)
                    run = gr.Button("Dub video", variant="primary")
                with gr.Column():
                    output_video = gr.Video(label="Dubbed video")
                    _make_result_video_probe_safe(output_video)
                    output_audio = gr.Audio(label="Localized audio", type="filepath")
                    _make_result_audio_probe_safe(output_audio)
                    output_srt = gr.File(label="Translated subtitles (.srt)")
                    status = gr.Markdown()
            code_mix_enabled.change(lambda enabled: gr.update(visible=enabled), code_mix_enabled, code_mix_options)
            language.change(
                lambda primary: gr.update(
                    choices=[item for item in matrix_languages if item != primary],
                    value="english" if primary != "english" else "hindi",
                ),
                language,
                code_mix_secondary,
            )
            run.click(process_studio, [video_file, video_url, language, dialect, burn, source_language, code_mix_enabled, code_mix_secondary, code_mix_intensity], [output_video, output_audio, output_srt, status])

        with gr.Tab("🎧 Audio mode (A2A)"):
            gr.Markdown("Upload an audio file (`.mp3`, `.wav`, `.m4a`, `.aac`, `.flac`) or record speech from your microphone for complete ASR → Transcreation → Regional Voice Dubbing.")
            with gr.Row():
                with gr.Column():
                    audio_input = gr.Audio(sources=["upload", "microphone"], type="filepath", label="Choose Audio File (.mp3, .wav, .m4a) or Record Microphone")
                    with gr.Row():
                        audio_source_language = gr.Dropdown(matrix_languages, value="english", label="Source language")
                        audio_language = gr.Dropdown(languages, value="hindi", label="Target language")
                    audio_run = gr.Button("Dub Audio", variant="primary")
                with gr.Column():
                    output_dubbed_audio = gr.Audio(label="Dubbed Regional Audio", type="filepath")
                    transcribed_box = gr.Textbox(label="Transcribed Original Speech", lines=2)
                    transcreated_box = gr.Textbox(label="Transcreated Regional Translation", lines=2)
                    audio_status = gr.Markdown()
            audio_run.click(process_audio, [audio_input, audio_language, audio_source_language], [output_dubbed_audio, transcribed_box, transcreated_box, audio_status])

        with gr.Tab("📝 Text demo"):
            with gr.Row():
                with gr.Column():
                    text_input = gr.Textbox(value="Don't put all your eggs in one basket", label="English text", lines=3)
                    text_language = gr.Dropdown(languages, value="hindi", label="Target language")
                    text_dialect = gr.Slider(1, 3, value=2, step=1, label="Dialect / register", info="1 formal · 2 conversational · 3 street slang")
                    text_run = gr.Button("Transcreate", variant="primary")
                    text_audio_run = gr.Button("Generate audio", variant="secondary")
                with gr.Column():
                    transcreated_text = gr.Textbox(label="Transcreated text", lines=2)
                    detected_intent = gr.Textbox(label="Detected cultural meaning / intent", lines=2)
                    explanation = gr.Textbox(label="Cultural translation rationale", lines=2)
                    text_audio = gr.Audio(label="Generated audio", type="filepath")
                    _make_result_audio_probe_safe(text_audio)
                    with gr.Accordion("Developer details & raw JSON", open=False):
                        text_output = gr.JSON(label="Full Payload")

            def _handle_text_dub(text, lang, dialect):
                res = text_to_text_dub(text, lang, dialect_level=int(dialect))
                return res["transcreated_text"], res["detected_intent"], res["explanation"], res

            text_run.click(_handle_text_dub, [text_input, text_language, text_dialect], [transcreated_text, detected_intent, explanation, text_output])

            def _handle_text_audio(text, lang, dialect):
                return text_to_audio_dub(text, lang, gender="auto", dialect_level=int(dialect))["output_audio_path"]

            text_audio_run.click(_handle_text_audio, [text_input, text_language, text_dialect], text_audio)

    return demo.queue(default_concurrency_limit=1)


if __name__ == "__main__":
    build_app().launch(
        server_name=os.getenv("DUBX_HOST", "127.0.0.1"),
        server_port=int(os.getenv("DUBX_PORT", "7860")),
        theme=gr.themes.Soft(),
    )
