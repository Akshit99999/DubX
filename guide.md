# DubX agent guide

## Purpose

DubX turns a local video, audio file, YouTube video, or YouTube Short into a regional-language dub. Media dubbing uses Sarvam's source-speaker workflow so source voices, speaker separation, and source timing are preserved.

Start the Gradio UI with:

```powershell
python app.py
```

It runs locally at `http://127.0.0.1:7860` by default. The Home tab introduces the workflow; Creator Studio produces a dub, Creator viewer previews saved MP4 masters, and the optional local Sign in tab verifies `DUBX_CREATOR_EMAIL` / `DUBX_CREATOR_PASSWORD` when configured. Configuration comes from `.env`; use `.env.example` as a template. Media dubbing needs `SARVAM_API_KEY`. URL downloads need `yt-dlp`; local ASR can use `faster-whisper` or `GROQ_API_KEY`.

## Main flow

```text
Studio UI
  -> utils/ingestion.resolve_input (local file or YouTube/Short download)
  -> dubx_core.video_to_video_dub
  -> pipeline/sarvam_dubbing.dub_media
  -> Sarvam create -> upload -> start -> poll -> download exports
  -> optional timed two-language audio mix
  -> pipeline/remux (caption burn or audio remux)
  -> video, WAV, SRT/VTT returned to Gradio
```

Audio mode follows the same Sarvam path without video remuxing. Text Lab is separate text-to-text and text-to-audio processing; its optional production-context note is forwarded to transcreation so names, scene details, and intended tone remain available to the translator.

## Source files

| File | Responsibility |
| --- | --- |
| `app.py` | Gradio interface, progress updates, input validation, output widgets. |
| `dubx_core.py` | Public APIs and orchestration for text, audio, and video. |
| `pipeline/sarvam_dubbing.py` | Sarvam job lifecycle, speaker detection, export download. |
| `pipeline/transcreation.py` | Context-aware batch translation with timing budgets. |
| `pipeline/code_mixing.py` | Primary/secondary-language text generation. |
| `pipeline/asr.py` | Timestamped Groq or faster-whisper ASR fallback. |
| `pipeline/remux.py` | FFmpeg audio mixing, remuxing, caption burn-in. |
| `utils/subtitles.py` | SRT/VTT formatting, SRT normalization, and parsing. |
| `utils/ingestion.py` | URL and YouTube/Short ingestion with progress events. |
| `config.py` | Output location, language map, environment loading, FFmpeg setup. |

## Speaker preservation

Media UI calls use `clone_voice=True`, `num_speakers=-1`, and source-speaker dubbing. `-1` asks Sarvam to detect each distinct source voice. Do not change it to `1`: that would flatten a conversation into one cloned voice.

The backend retains `voice_clone_consent` for library and CLI callers. Studio supplies it because original-speaker dubbing is the only Studio media mode.

## Code-mixed Studio dubs

With “Mix a second language into the dub” enabled, the pipeline requests two source-speaker dubs: the selected target language and the secondary language. `_mix_subtitle_tracks` selects evenly distributed timestamped cues based on intensity (15%, 30%, or 50%).

`mix_timed_audio_tracks` replaces those windows with the secondary source-voice track. Generated SRT/VTT uses the corresponding primary or secondary subtitle text. This ensures the secondary selection changes the delivered video, audio, and captions.

## Captions

SRT timestamps control when captions appear and disappear. The burn-in style in `pipeline/remux.py:burn_captions` uses:

- bottom-center alignment;
- white text with black outline and shadow;
- no opaque caption panel;
- 90px left/right safe margins and 34px bottom margin;
- normalized one-cue subtitles, wrapping only if a long sentence cannot fit in the safe frame.

Captioned MP4s encode with H.264 High Profile at CRF 18 and the `medium` preset by default, with `+faststart` for web playback. Override those values with `DUBX_CAPTION_CRF` (16–28) and `DUBX_CAPTION_PRESET` when an export needs a different quality/speed balance. YouTube downloads default to a maximum height of 1080p.

Provider SRT exports are normalized by `normalize_srt_file` before they are returned or burned into the final video.

## Outputs

All output files are under `output_dubbed/`: dubbed MP4 video, dubbed WAV audio, translated SRT/VTT, temporary source downloads, and Sarvam exports. Do not delete it while a job is running.

## Tests

Run tests before committing:

```powershell
python -m unittest discover -s tests -v
```

Tests are mocked/offline and cover UI-safe helpers, subtitle timing, speaker-cloning parameters, code-mix inputs, and fallback flows.

## Common issues

- **Gradio errors after export:** some Windows installs have `ffmpeg` without `ffprobe`. `app.py` guards the finished MP4 and WAV result components from optional Gradio probing.
- **YouTube URL seems stalled:** ingestion streams `yt-dlp` progress. Watch URLs, `youtu.be`, and `/shorts/` URLs are supported.
- **Speakers sound identical:** confirm `num_speakers=-1` is passed. Overlapping/noisy speech can still reduce diarization quality.
- **Text-to-audio has no source identity:** text has no source audio to clone, so it uses Sarvam Bulbul preset TTS and requires `SARVAM_API_KEY`.
