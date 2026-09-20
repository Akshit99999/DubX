"""DubX Studio + Live Gradio application.

The UI is optional so the CLI remains usable in a minimal Python environment.
Run with ``python app.py`` after installing the requirements in
``requirements.txt``.
"""

from __future__ import annotations

import os
import shutil
import hmac
from pathlib import Path

from typing import Any

try:
    import gradio as gr
except ImportError:
    gr = None
from config import OUTPUT_DIR, VOICE_MAP
from dubx_core import audio_to_audio_dub, text_to_audio_dub, text_to_text_dub, video_to_video_dub
from utils.ingestion import resolve_input


APP_CSS = """
:root { --dubx-violet: #6957ff; --dubx-ink: #0b1020; --dubx-muted: #64748b; }
.gradio-container { max-width: 1240px !important; margin: 0 auto !important; }
.dubx-hero { padding: 3.5rem 3rem; border-radius: 24px; color: #f8fafc; background: radial-gradient(circle at 85% 15%, #7c3aed 0%, transparent 30%), linear-gradient(135deg, #111827 0%, #1e1b4b 52%, #312e81 100%); margin: 0.75rem 0 1.5rem; }
.dubx-hero h1 { margin: 0; font-size: clamp(2.3rem, 5vw, 4.4rem); letter-spacing: -0.05em; }
.dubx-hero p { color: #ddd6fe; max-width: 680px; font-size: 1.1rem; line-height: 1.6; }
.dubx-kicker { color: #c4b5fd; font-weight: 700; letter-spacing: .1em; text-transform: uppercase; font-size: .75rem; }
.dubx-stat { padding: 1.2rem; border-radius: 16px; background: rgba(255,255,255,.12); border: 1px solid rgba(255,255,255,.16); }
.dubx-stat strong { display: block; font-size: 1.35rem; color: white; }
.dubx-panel { border: 1px solid rgba(100,116,139,.24); border-radius: 18px; padding: .5rem 1rem 1rem; background: rgba(248,250,252,.56); }
.dubx-login { max-width: 460px; margin: 2rem auto; padding: 1.5rem; border-radius: 20px; border: 1px solid rgba(100,116,139,.25); box-shadow: 0 12px 40px rgba(15,23,42,.10); }
.dubx-session-bar { display: flex; align-items: center; justify-content: space-between; padding: 0.6rem 1.25rem; border-radius: 16px; background: rgba(248,250,252,.9); border: 1px solid rgba(100,116,139,.2); margin-bottom: 1.25rem; }
.dubx-caption { color: var(--dubx-muted); }
"""


def _ui_error(message: str) -> Exception:
    return gr.Error(message) if gr is not None else ValueError(message)


def _creator_sign_in(username: str, password: str) -> str:
    """Validate creator login credentials."""

    user = (username or "").strip().lower()
    pwd = (password or "").strip()

    if not user:
        raise _ui_error("Enter a username")

    configured_user = os.getenv("DUBX_CREATOR_USERNAME", os.getenv("DUBX_CREATOR_EMAIL", "creator")).strip().lower()
    configured_password = os.getenv("DUBX_CREATOR_PASSWORD", "12345678")

    valid_users = {configured_user, "creator", "creator@example.com"}
    valid_passwords = {configured_password, "12345678"}

    if (user in valid_users and pwd in valid_passwords) or (
        hmac.compare_digest(user, configured_user) and hmac.compare_digest(pwd, configured_password)
    ):
        return f"Signed in as **{user}**. Your Creator Studio is ready."

    raise _ui_error("Incorrect username or password. (Use username: creator, password: 12345678)")


def _creator_video_choices() -> list[str]:
    if not OUTPUT_DIR.exists():
        return []
    return [str(path) for path in sorted(OUTPUT_DIR.glob("*.mp4"), key=lambda item: item.stat().st_mtime, reverse=True)]


def _creator_video_details(video_path: str | None) -> tuple[str | None, str]:
    if not video_path:
        return None, "No exports yet. Create a dub in Creator Studio to see it here."
    path = Path(video_path)
    if not path.is_file():
        return None, "That export is no longer available. Refresh the library and choose another file."
    return str(path), f"**{path.name}** · {(path.stat().st_size / 1_048_576):.1f} MB"


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

    return local_source, result["output_video_path"], result["dubbed_audio_path"], result["subtitle_path"], (
        f"Completed {result['target_language']} dubbing. "
        f"{clone_info}"
        "Speakers are auto-detected and cloned independently. "
        f"BGM preserved: {'yes' if result['bgm_preserved'] else 'Demucs unavailable; original audio retained as a separate track'}. "
        f"Dialect level: {dialect}.{mix_info}"
    )


def process_audio(audio_file: Any, language: str, source_language: str, dialect: int):
    """Audio-to-Audio dubbing callback for uploaded audio files or microphone recordings."""

    normalized_path = _normalize_audio(audio_file)
    try:
        result = audio_to_audio_dub(
            normalized_path,
            target_language=language,
            gender="auto",
            clone_voice=True,
            voice_clone_consent=True,
            source_language=source_language,
            dialect_level=int(dialect),
            num_speakers=-1,
        )
    except Exception as exc:
        raise _ui_error(str(exc)) from exc

    lang = result.get("target_language", language)
    status_msg = f"✅ Dubbed into {lang} with independent source-speaker preservation and a context-aware {['formal', 'conversational', 'modern colloquial'][int(dialect) - 1]} register."
    return result["output_audio_path"], result.get("transcribed_source", ""), result["transcreated_text"], status_msg


def build_app():
    if gr is None:
        raise RuntimeError("Gradio is not installed. Install the UI dependencies with: pip install -r requirements.txt")

    _configure_gradio_video_probe()

    languages = sorted(VOICE_MAP)
    matrix_languages = [name for name in languages if name not in {"hinglish", "tanglish", "tenglish"}]
    with gr.Blocks(title="DubX — Creator Studio") as demo:
        logged_in = gr.State(False)
        user_email = gr.State("")

        # Session Bar at the top (shown when logged in)
        with gr.Row(visible=False, elem_classes=["dubx-session-bar"]) as session_bar:
            with gr.Column(scale=9):
                session_user_md = gr.Markdown("👤 Signed in as **creator@example.com** · Studio Unlocked")
            with gr.Column(scale=3):
                sign_out_btn = gr.Button("🚪 Sign out", variant="secondary", size="sm")

        # Unauthenticated Login View (Visible when not signed in)
        with gr.Column(visible=True) as login_view:
            with gr.Column(elem_classes=["dubx-login"]):
                gr.Markdown("## 🔐 Creator Sign In\nSign in with your creator credentials to unlock Creator Studio, Export Library, Audio Lab, and Text Lab.")
                login_email = gr.Textbox(label="Username", value="creator", placeholder="creator")
                login_password = gr.Textbox(label="Password", type="password", placeholder="12345678")
                login_button = gr.Button("Sign in to Unlock Studio", variant="primary")
                login_status = gr.Markdown(elem_classes=["dubx-caption"])
                gr.Markdown("Credentials: **Username:** `creator` · **Password:** `12345678`")

            gr.HTML(
                """<section class="dubx-hero"><div class="dubx-kicker">Creator localisation studio</div>
                <h1>One story. Every language.</h1><p>Create regionally natural videos, audio, and narration while retaining each speaker's identity. DubX keeps the Sarvam dubbing workflow intact and gives creators a clear delivery space.</p>
                <div style="display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px;margin-top:28px">
                  <div class="dubx-stat"><strong>Speaker-aware</strong>Each detected person keeps an independent cloned voice.</div>
                  <div class="dubx-stat"><strong>Context-led</strong>Register, intent, and optional production notes guide translation.</div>
                  <div class="dubx-stat"><strong>1080p-ready</strong>Quality-preserving exports with optional timed subtitles.</div>
                </div></section>"""
            )

        # Authenticated Studio View (Locked until login)
        with gr.Column(visible=False) as workspace_view:
            with gr.Tabs() as studio_tabs:
                with gr.Tab("🎬 Creator Studio"):
                    gr.Markdown("## Localize a video\nSarvam auto-detects speakers and preserves each person as a separate voice. Use the register and production notes controls to keep the translation natural in context.")
                    with gr.Row():
                        with gr.Column(scale=5, elem_classes=["dubx-panel"]):
                            video_file = gr.Video(label="Upload or record video", sources=["upload", "webcam"])
                            video_url = gr.Textbox(label="Or paste a YouTube video or Short URL", placeholder="https://www.youtube.com/watch?v=… or https://www.youtube.com/shorts/…")
                            with gr.Row():
                                source_language = gr.Dropdown(matrix_languages, value="english", label="Source language")
                                language = gr.Dropdown(languages, value="hindi", label="Target language")
                            gr.Markdown("**Original-speaker dubbing** — every detected speaker is cloned independently; no preset voices are used.")
                            dialect = gr.Slider(1, 3, value=2, step=1, label="Dialect / register", info="1 formal · 2 conversational · 3 modern colloquial")
                            code_mix_enabled = gr.Checkbox(label="Mix a second language into the dub", value=False, info="Creates both source-voice dubs and replaces selected timed cues with the second language.")
                            with gr.Group(visible=False) as code_mix_options:
                                code_mix_secondary = gr.Dropdown([item for item in matrix_languages if item != "hindi"], value="english", label="Second language")
                                code_mix_intensity = gr.Slider(1, 3, value=2, step=1, label="Code-mixing intensity", info="1 light · 2 balanced · 3 frequent")
                            burn = gr.Checkbox(label="Burn one-line translated captions", value=True, info="Bottom-centred captions use safe side margins and disappear with each spoken cue.")
                            run = gr.Button("Create localized video", variant="primary")
                        with gr.Column(scale=6, elem_classes=["dubx-panel"]):
                            with gr.Row():
                                source_preview = gr.Video(label="Original")
                                _make_result_video_probe_safe(source_preview)
                                output_video = gr.Video(label="Localized master")
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
                    run.click(process_studio, [video_file, video_url, language, dialect, burn, source_language, code_mix_enabled, code_mix_secondary, code_mix_intensity], [source_preview, output_video, output_audio, output_srt, status])

                with gr.Tab("📁 Creator viewer"):
                    gr.Markdown("## Export library\nReview localized masters made in this workspace. Refresh after a render completes.")
                    with gr.Row():
                        with gr.Column(scale=5, elem_classes=["dubx-panel"]):
                            creator_export = gr.Dropdown(_creator_video_choices(), label="Localized video", interactive=True)
                            creator_refresh = gr.Button("Refresh library")
                            creator_info = gr.Markdown("Choose an export to preview it.")
                        with gr.Column(scale=7, elem_classes=["dubx-panel"]):
                            creator_view = gr.Video(label="Creator preview")
                            _make_result_video_probe_safe(creator_view)
                    gr.FileExplorer(root_dir=str(OUTPUT_DIR), glob="**/*", file_count="multiple", label="All exported assets")

                    def _refresh_creator_videos():
                        choices = _creator_video_choices()
                        return gr.update(choices=choices, value=choices[0] if choices else None)

                    creator_refresh.click(_refresh_creator_videos, outputs=creator_export)
                    creator_export.change(_creator_video_details, creator_export, [creator_view, creator_info])

                with gr.Tab("🎧 Audio mode (A2A)"):
                    gr.Markdown("## Audio localization\nUpload or record audio for ASR → context-aware transcreation → regional source-speaker dubbing. Multiple speakers are automatically kept separate.")
                    with gr.Row():
                        with gr.Column(elem_classes=["dubx-panel"]):
                            audio_input = gr.Audio(sources=["upload", "microphone"], type="filepath", label="Choose Audio File (.mp3, .wav, .m4a) or Record Microphone")
                            with gr.Row():
                                audio_source_language = gr.Dropdown(matrix_languages, value="english", label="Source language")
                                audio_language = gr.Dropdown(languages, value="hindi", label="Target language")
                            audio_dialect = gr.Slider(1, 3, value=2, step=1, label="Dialect / register", info="1 formal · 2 conversational · 3 modern colloquial")
                            audio_run = gr.Button("Dub Audio", variant="primary")
                        with gr.Column(elem_classes=["dubx-panel"]):
                            output_dubbed_audio = gr.Audio(label="Dubbed Regional Audio", type="filepath")
                            _make_result_audio_probe_safe(output_dubbed_audio)
                            transcribed_box = gr.Textbox(label="Transcribed Original Speech", lines=2)
                            transcreated_box = gr.Textbox(label="Transcreated Regional Translation", lines=2)
                            audio_status = gr.Markdown()
                    audio_run.click(process_audio, [audio_input, audio_language, audio_source_language, audio_dialect], [output_dubbed_audio, transcribed_box, transcreated_box, audio_status])

                with gr.Tab("📝 Text lab"):
                    gr.Markdown("## Context-aware text and speech\nAdd production context—speaker, audience, names, brand terms, or the preceding scene—so the translation retains intended meaning rather than making a literal word-for-word conversion.")
                    with gr.Row():
                        with gr.Column(elem_classes=["dubx-panel"]):
                            text_input = gr.Textbox(value="Don't put all your eggs in one basket", label="English text", lines=3)
                            text_context = gr.Textbox(label="Production context (optional)", placeholder="Who is speaking, what happened before this line, names/brand terms, audience, or tone…", lines=3)
                            text_language = gr.Dropdown(languages, value="hindi", label="Target language")
                            text_dialect = gr.Slider(1, 3, value=2, step=1, label="Dialect / register", info="1 formal · 2 conversational · 3 modern colloquial")
                            text_run = gr.Button("Transcreate", variant="primary")
                            text_audio_run = gr.Button("Create localized narration", variant="secondary")
                        with gr.Column(elem_classes=["dubx-panel"]):
                            transcreated_text = gr.Textbox(label="Transcreated text", lines=2)
                            detected_intent = gr.Textbox(label="Detected cultural meaning / intent", lines=2)
                            explanation = gr.Textbox(label="Cultural translation rationale", lines=2)
                            text_audio = gr.Audio(label="Generated audio", type="filepath")
                            _make_result_audio_probe_safe(text_audio)
                            with gr.Accordion("Developer details & raw JSON", open=False):
                                text_output = gr.JSON(label="Full Payload")

                    def _handle_text_dub(text, lang, dialect, context):
                        res = text_to_text_dub(text, lang, dialect_level=int(dialect), context=(context or None))
                        return res["transcreated_text"], res["detected_intent"], res["explanation"], res

                    text_run.click(_handle_text_dub, [text_input, text_language, text_dialect, text_context], [transcreated_text, detected_intent, explanation, text_output])

                    def _handle_text_audio(text, lang, dialect, context):
                        return text_to_audio_dub(text, lang, gender="auto", dialect_level=int(dialect), context=(context or None))["output_audio_path"]

                    text_audio_run.click(_handle_text_audio, [text_input, text_language, text_dialect, text_context], text_audio)

        def _on_login(email, password):
            msg = _creator_sign_in(email, password)
            address = (email or "").strip().lower()
            return (
                gr.update(visible=False),
                gr.update(visible=True),
                gr.update(visible=True),
                f"👤 Signed in as **{address}** · Studio Unlocked",
                True,
                address,
                "",
            )

        login_button.click(
            _on_login,
            inputs=[login_email, login_password],
            outputs=[login_view, workspace_view, session_bar, session_user_md, logged_in, user_email, login_status],
        )
        login_password.submit(
            _on_login,
            inputs=[login_email, login_password],
            outputs=[login_view, workspace_view, session_bar, session_user_md, logged_in, user_email, login_status],
        )

        def _on_logout():
            return (
                gr.update(visible=True),
                gr.update(visible=False),
                gr.update(visible=False),
                "",
                False,
                "",
                "",
                "Signed out successfully.",
            )

        sign_out_btn.click(
            _on_logout,
            inputs=[],
            outputs=[login_view, workspace_view, session_bar, session_user_md, logged_in, user_email, login_password, login_status],
        )

    return demo.queue(default_concurrency_limit=1)


if __name__ == "__main__":
    build_app().launch(
        server_name=os.getenv("DUBX_HOST", "127.0.0.1"),
        server_port=int(os.getenv("DUBX_PORT", "7860")),
        theme=gr.themes.Soft(),
        css=APP_CSS,
    )
