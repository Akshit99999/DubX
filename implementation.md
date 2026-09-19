# DubX — Master Technical Implementation Specification

---

## 1. Executive Summary & Product Vision

### 1.1 The Mission
DubX is an industrial-grade AI media localization platform designed to democratize digital content for India's next 500 million internet users. While traditional dubbing costs **₹1,000–₹1,800/min ($12–$22/min)** and takes 7–14 days, DubX delivers broadcast-quality regional dubbing in **under 3 minutes at less than 1% of the cost (₹25–₹30/min)** with **88.5% gross margins**.

### 1.2 The iLovePDF Design Philosophy: 3-Input ➔ 3-Output Simplicity
Designed with the clean, minimalist, and tool-focused simplicity of **iLovePDF**, our platform turns video dubbing into Indian regional languages into an effortless, one-click experience:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                   THE 3-INPUT ➔ 3-OUTPUT SIMPLICITY MODEL                        │
│                                                                                  │
│  INPUT METHODS:                                                                  │
│    1. 📁 Local File Upload (MP4, MOV, MKV, MP3, WAV)                             │
│    2. 📹 Live Camera & Mic Record (Direct In-Browser HTML5 / WebRTC)             │
│    3. 🔗 Video URL (YouTube, Shorts, Instagram Reels, TikTok, X)                 │
│                                      ↓                                           │
│                 ⚡ DubX Regional AI Transcreation Engine                         │
│           (ASR ➔ Syllable Budgeting ➔ TTS ➔ Ducking ➔ Remux)                    │
│                                      ↓                                           │
│  OUTPUT CHOICES:                                                                 │
│    1. 🎬 Fully Dubbed Regional Video (Dubbed audio + Preserved BGM + Subtitles)  │
│    2. 🎧 Standalone Localized Audio Track (M4A / MP3 for podcasts & YouTube MLA) │
│    3. 📄 Complete Translated Text Transcript (SRT, VTT, TXT in regional script)  │
└──────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. The 5 Dubbing Pillars (`dubx_core.py`)

DubX unifies five distinct dubbing modalities to address the entire content ecosystem:

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                           THE DUBX DUBBING SUITE                                 │
│                                                                                  │
│  1. 📝 TEXT-TO-TEXT DUBBING (Transcreation Engine)                               │
│     English Text ➔ Intent Extraction ➔ Cultural Regional Text                    │
│                                                                                  │
│  2. 🔊 TEXT-TO-AUDIO DUBBING                                                     │
│     English Text ➔ Transcreation ➔ Regional Neural Voice Audio (MP3)             │
│                                                                                  │
│  3. 🎙️ AUDIO-TO-AUDIO DUBBING                                                     │
│     Source Audio ➔ Whisper ASR ➔ Transcreation ➔ Regional Dubbed Audio          │
│                                                                                  │
│  4. 🎬 VIDEO-TO-VIDEO DUBBING (Clean / Softsub)                                  │
│     Source Video ➔ Audio Extract ➔ ASR ➔ Voice Dub ➔ Lossless Remux + SRT File   │
│                                                                                  │
│  5. 📺 VIDEO-TO-VIDEO + CAPTIONS (Hardsub Burn-in for Reels/Shorts)              │
│     Source Video ➔ Voice Dub ➔ Styled Regional Captions Burned into Video        │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 2.1 Mode 1: Text-to-Text (T2T) Transcreation
- **Objective:** Converts English text into natural regional Indian languages while preserving metaphors, idioms, humor, and emotional energy (anti-literal).
- **Duration & Syllable Budgeting:**
  $$\text{Target Syllables} = \text{Duration (s)} \times 4.0\text{ syllables/sec}$$
  Enforces a syllable budget to prevent Indic syllable expansion from causing video drift.
- **Engines:** Gemini 1.5 Flash (Online) + `OFFLINE_IDIOMS` rule base (Offline zero-failure fallback).

### 2.2 Mode 2: Text-to-Audio (T2A) Dubbing
- **Objective:** Text input $\rightarrow$ transcreation $\rightarrow$ broadcast-grade regional voice synthesis.
- **Dual Engine Stack:**
  - *Primary:* **Sarvam Bulbul V3** (Native Indian accents, Hinglish/Tanglish cadence, speaker timbre cloning).
  - *Fallback / Zero-Cost:* **Microsoft Edge-TTS** (100% free, zero API key, sub-1s latency, 8 Indian languages).

### 2.3 Mode 3: Audio-to-Audio (A2A) Dubbing
- **Objective:** Speech-to-speech dubbing without video processing overhead (**45% faster turnaround, 70% lower compute cost**).
- **Workflow:** Input Audio (`.wav`, `.mp3`) $\rightarrow$ Whisper ASR (Groq / faster-whisper) $\rightarrow$ Transcreation $\rightarrow$ Regional Voice Synthesis (`a2a_{name}_{lang}.mp3`).

### 2.4 Mode 4: Video-to-Video (V2V Clean / Softsub)
- **Objective:** Video dubbing with background music preservation, dynamic ducking, and lossless video remuxing (`-c:v copy`).
- **Workflow:**
  1. Extract 44.1kHz audio: `ffmpeg -i video.mp4 -vn -acodec pcm_s16le audio.wav`
  2. Stem separation: `Demucs v4` separates `vocals.wav` and `bgm.wav`.
  3. Whisper ASR extracts timestamped segments.
  4. Transcreation generates duration-budgeted regional text.
  5. Regional TTS generates speech segments.
  6. `pyrubberband` phase-vocoder time-stretches audio (clamped between 0.85x and 1.18x).
  7. FFmpeg `sidechaincompress` ducks BGM by -10dB during speech and swells during pauses.
  8. Lossless remuxing: `ffmpeg -i video.mp4 -i mastered.wav -c:v copy -c:a aac -b:a 192k output.mp4` (finishes in $<0.5$s).
  9. Generates standalone `.srt` and `.vtt` files.

### 2.5 Mode 5: Video-to-Video + Captions (V2V Hardsub)
- **Objective:** Burns styled open captions directly into video frames for mobile feeds (Instagram Reels, YouTube Shorts, TikTok) where **85% of users scroll on mute**.
- **Implementation:**
  ```bash
  ffmpeg -y -i source_video.mp4 -i dubbed_audio.mp3 \
    -vf "subtitles='subs.srt':force_style='FontSize=20,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BorderStyle=3,MarginV=30'" \
    -c:v libx264 -preset veryfast -crf 22 -c:a aac -b:a 192k \
    -map 0:v:0 -map 1:a:0 v2v_with_captions.mp4
  ```

---

## 3. Dual-Track Audio Container Architecture

### 3.1 Seamless Language Switching in VLC & YouTube
To preserve the original English audio alongside the new regional dub in a single video container, DubX multiplexes both streams into an MP4/MKV container:

```bash
ffmpeg -y \
  -i source_video.mp4 \
  -i dubbed_mastered_audio.wav \
  -map 0:v:0 \
  -map 0:a:0 \
  -map 1:a:0 \
  -c:v copy \
  -c:a:0 copy \
  -c:a:1 aac -b:a:1 192k \
  -metadata:s:a:0 language=eng \
  -metadata:s:a:0 title="English (Original)" \
  -metadata:s:a:1 language=hin \
  -metadata:s:a:1 title="Hindi (Dubbed)" \
  -disposition:a:0 0 \
  -disposition:a:1 default \
  output_dual_track.mp4
```

### 3.2 Key Benefits:
- **Zero Video Re-encoding:** Video stream is passed through untouched (`-c:v copy`), taking under 0.5s.
- **Original Audio Preservation:** Track 0 retains the original English track bit-for-bit.
- **Default Dubbed Playback:** Track 1 (Hindi/Tamil) is marked as `default`, automatically playing in media players.
- **VLC Keyboard Toggle:** Pressing **`b`** in VLC switches between English and Hindi instantly without video pause or buffering!

---

## 4. Multi-Regional Transcreation Engine

### 4.1 Supported Regional Languages & Neural Voices

| Language | Code | Spoken Register | Casual Markers | Edge-TTS Voice (M / F) |
| :--- | :--- | :--- | :--- | :--- |
| **Hindi** | `hi` | Conversational Hinglish | *bhai, yaar, arre, boss* | `hi-IN-MadhurNeural` / `hi-IN-SwaraNeural` |
| **Tamil** | `ta` | Spoken Tamil / Tanglish | *da, di, pa, machan* | `ta-IN-ValluvarNeural` / `ta-IN-PallaviNeural` |
| **Telugu** | `te` | Hyderabadi / Tenglish | *bro, ra, ri, mama* | `te-IN-MohanNeural` / `te-IN-ShrutiNeural` |
| **Bengali** | `bn` | Kolkata Cholito / Banglish | *re, tui, dada, guru* | `bn-IN-BashkarNeural` / `bn-IN-TanishaaNeural` |
| **Marathi** | `mr` | Puneri & Mumbai Marathi | *re, ya, bhau, dada* | `mr-IN-ManoharNeural` / `mr-IN-AarohiNeural` |
| **Kannada** | `kn` | Bengaluru / Kanglish | *maga, guru, macha* | `kn-IN-GaganNeural` / `kn-IN-SapnaNeural` |
| **Gujarati** | `gu` | Amdavad / Surati | *bhai, yaar, laala* | `gu-IN-NiranjanNeural` / `gu-IN-DhwaniNeural` |
| **Malayalam** | `ml` | Kochi / Manglish | *aliya, macha, bro* | `ml-IN-MidhunNeural` / `ml-IN-SobhanaNeural` |

### 4.2 The 7 Cardinal Transcreation Directives (Gemini 1.5 Flash Prompt)
1. **Rule 1: Anti-Literal Primacy:** Never translate word-for-word. Translate intent, emotional energy, and rhetorical impact.
2. **Rule 2: Metaphor to Cultural Equivalent:** Replace Anglo idioms with native proverbs (*"Hit it out of the park"* $\rightarrow$ *"சூப்பரா பண்ணிட்டான்டா"*).
3. **Rule 3: Proverb-for-Proverb Mapping:** Match proverbs to cultural equivalents (*"Don't put all your eggs in one basket"* $\rightarrow$ *"सारा पैसा एक जगह मत लगाओ भाई"*).
4. **Rule 4: Humor & Sarcasm Invariance:** Preserve comic timing, irony, and dry humor.
5. **Rule 5: Pragmatic Code-Mixing:** Keep modern loan words (*portfolio, subscribe, app, market*) in native script rather than forcing archaic Sanskrit/classical words.
6. **Rule 6: Prosodic Marker Preservation:** Retain exclamations, rhetorical questions, and pauses at identical positions.
7. **Rule 7: Strict Syllable Budgeting:** Keep output within $\{T \times 4.0\}$ syllables to prevent video desync.

---

## 5. Acoustic Emotion & Energy Transfer Architecture

Standard TTS produces flat, robotic speech. DubX transfers the original speaker's performance dynamics onto the regional voice:

```mermaid
flowchart LR
    VOCALS["Isolated Source Vocals\n(vocals.wav via Demucs)"]
    
    subgraph Extraction["Acoustic Feature Extraction"]
        PITCH["F0 Pitch Extraction\n(pYIN / CREPE Algorithm)\n10ms frame rate"]
        ENERGY["RMS Energy Envelope\n(25ms window, 10ms hop)"]
        VELOCITY["Speaking Velocity\n(Phonemes / sec)"]
    end
    
    subgraph Mapping["Dynamics Normalization"]
        NORM_P["Semitone Pitch Deviation:\nΔF0(t) = 12 * log2(F0(t) / μ_F0_src)"]
        NORM_E["Relative RMS Energy:\nΔE(t) = 20 * log10(RMS(t) / RMS_ref)"]
    end
    
    subgraph Synthesis["Prosody Transfer"]
        SSML["Dynamic SSML Modulation\n<prosody pitch='+18%' volume='+6dB'>"]
        PSOLA["Waveform Prosody Warping (PSOLA)"]
    end
    
    VOCALS --> Extraction
    PITCH --> NORM_P
    ENERGY --> NORM_E
    NORM_P --> Synthesis
    NORM_E --> Synthesis
    VELOCITY --> Synthesis
    Synthesis --> OUT["Emotion-Matched Regional Speech\n(Excitement, Whispers & Punchlines Preserved)"]
```

---

## 6. Dual-Mode Gradio Architecture: Studio vs. Live

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                      DUBX DUAL-MODE ARCHITECTURE                                 │
│                                                                                  │
│   🎬 STUDIO MODE (Batch Video)            🎙️ LIVE MODE (Real-Time Mic)            │
│   ───────────────────────────             ─────────────────────────────          │
│   • Input: MP4 / YouTube URL              • Input: Live Microphone / WebRTC      │
│   • Processing: 8-Stage Batch             • Processing: 500ms Streaming Chunks   │
│   • Latency: 10–25s (for 60s video)       • Latency: < 2.0s End-to-End           │
│   • BGM: Demucs v4 Stem Separation        • BGM: Clean Mic / OBS Track Bypass    │
│   • Human Review: Editable Dataframe      • Human Review: Automated Live Stream  │
│   • Output: Dubbed MP4 + Dual Player      • Output: Live Audio + Karaoke Overlay │
└──────────────────────────────────────────────────────────────────────────────────┘
```

### 6.1 Studio Mode: The 4-Tab Workflow
- **Tab 1: Input & Config:** File upload, URL ingestion, language selector, and **Dialect Slider** (Level 1: Formal, Level 2: Conversational, Level 3: Street Slang).
- **Tab 2: Pipeline Monitor:** Visual progress stepper and real-time latency telemetry.
- **Tab 3: HITL Review:** Interactive `gr.Dataframe` with syllable budget indicators (🟢 Fit, 🟡 Tight, 🔴 Overflow) and 1-click **AI Auto-Trim**.
- **Tab 4: Output & Export:** Synchronized side-by-side video player, mid-playback **A/B audio switcher**, and 3-output download hub.

### 6.2 Live Mode: Sub-2s Streaming Cascade
$$\text{Capture (500ms)} \rightarrow \text{Silero-VAD (20ms)} \rightarrow \text{Groq Whisper (150ms)} \rightarrow \text{Groq Llama (200ms)} \rightarrow \text{Streaming TTS (150ms)} \rightarrow \text{Audio Out}$$
**Total latency: ~1.5 to 1.8 seconds**, fully demonstrated live during hackathon judging.

---

## 7. Universal Ingestion Engine

Beyond standard MP4 file uploads, DubX provides 7 universal ingestion modalities:

1. **Social URLs (`yt-dlp`):** Ingests YouTube, Shorts, Reels, TikTok, and X. Extracts **only audio** (`-f ba -x`), saving 90% bandwidth and remuxing losslessly in 0.4s.
2. **Podcast RSS Feeds (`feedparser`):** Ingests Apple Podcasts/Spotify RSS feeds, bypassing video processing for 45% faster turnaround.
3. **1-Click Audiogram Generator:** Converts dubbed podcasts into **1080x1920 vertical video reels** with animated waveforms (`showwaves`) and Hormozi-style karaoke subtitles in a single 3-second FFmpeg pass.
4. **EdTech Slide-to-Video:** Ingests PPTX/PDF slides + speaker notes, rasterizes 1080p images (`PyMuPDF`), transcreates teaching scripts, and outputs complete slide-timed video lectures.
5. **Article-to-Reel:** Ingests blog/news URLs (`trafilatura`), writes a 4-scene script (Gemini Flash), and applies Ken Burns pan/zoom to create 45-second viral video reels.
6. **RTMP/SRT Live Broadcast:** Ingests live streams from OBS Studio/vMix via **MediaMTX**, buffers video by 2.5s for sync, and restreams multi-language feeds.
7. **Browser Screen Share:** Ingests system audio via `navigator.mediaDevices.getDisplayMedia` with zero file saves.

---

## 8. Vernacular YouTube SEO & Multi-Language Audio (MLA) Package

DubX generates the complete directory structure expected by **YouTube Multi-Language Audio**:

```
dubx_mla_package_<VIDEO_ID>/
├── manifest.json                           # Master orchestration manifest
├── video/
│   └── source_master.mp4                   # Original video stream
├── audio/                                  # 48kHz 24-bit mastered tracks (-14 LUFS)
│   ├── en_US_original.wav
│   ├── hi_IN_hindi_master.wav
│   └── ta_IN_tamil_master.wav
├── subtitles/                              # HarfBuzz-shaped SRT/VTT
│   ├── en_US.srt / en_US.vtt
│   ├── hi_IN.srt / hi_IN.vtt
│   └── ta_IN.srt / ta_IN.vtt
└── metadata/                               # YouTube Data API v3 JSON payloads
    ├── metadata_hi_IN.json                 # High-CTR title, description, chapters, tags
    └── metadata_ta_IN.json
```

---

## 9. Codebase File Structure

```
regionaldubbing/
├── app.py                          # Main Gradio application
├── dubx_core.py                    # Unified 5-mode CLI & engine
├── text_to_dub.py                  # Standalone T2T & T2A transcreation engine
├── config.py                       # Voice maps, API keys, language profiles
├── state.py                        # Dataclasses for Gradio session state
│
├── studio/                         # 🎬 Studio Mode (Batch Video)
│   ├── tab_input.py                #   Tab 1: 3-in-1 Ingestion & settings
│   ├── tab_pipeline.py             #   Tab 2: Progress stepper & telemetry
│   ├── tab_review.py               #   Tab 3: HITL dataframe editor
│   └── tab_output.py               #   Tab 4: Dual player & A/B switcher
│
├── live/                           # 🎙️ Live Mode (Real-Time)
│   ├── tab_live.py                 #   Live mic capture & karaoke subtitles
│   ├── vad.py                      #   Silero-VAD clause detector
│   └── stream_orchestrator.py      #   Async streaming pipeline (Groq + Edge)
│
├── pipeline/                       # Core AI Pipeline
│   ├── asr.py                      #   Groq Whisper / Sarvam Saaras / faster-whisper
│   ├── transcreation.py            #   Gemini 1.5 Flash transcreation engine
│   ├── tts.py                      #   Sarvam Bulbul & Edge-TTS dual engine
│   ├── demux.py                    #   Demucs v4 neural stem separation
│   ├── realignment.py              #   pyrubberband phase-vocoder time-stretching
│   └── remux.py                    #   FFmpeg dual-track remux & ducking
│
├── utils/
│   ├── syllable_budget.py          #   Indic Akshara & syllable counter
│   ├── audio_utils.py              #   LUFS normalization & resampling
│   ├── subtitles.py                #   HarfBuzz-shaped Noto Sans subtitle generator
│   └── sync_player.js              #   Bi-directional video sync JavaScript
│
├── output_dubbed/                  # Rendered videos, audios, and subtitles
├── README.md                       # Master project overview
├── ARCHITECTURE.md                 # Complete system architecture
└── implementation.md               # This master implementation plan
```

---

## 10. Verification & Quality Assurance Plan

1. **Text-to-Text Verification:**
   - Test idiom: *"Don't put all your eggs in one basket"* $\rightarrow$ Verify Hindi output contains *"सारा पैसा एक जगह मत लगाओ भाई"* and **NOT** literal eggs/baskets.
2. **Text-to-Audio Verification:**
   - Verify generated MP3 plays cleanly with native regional pronunciation via `hi-IN-MadhurNeural` and `ta-IN-ValluvarNeural`.
3. **Audio-to-Audio Verification:**
   - Verify speech transcribed from audio clip is correctly transcreated and synthesized into target regional MP3.
4. **Video-to-Video Clean Verification:**
   - Verify output MP4 remuxes in $<0.5$s via `-c:v copy` with zero video re-encoding.
   - Verify background music is preserved and ducked by -10dB during dialogue.
5. **Video-to-Video Captions Verification:**
   - Verify regional subtitles are burned into video frames with high-contrast styling and proper Indic ligature shaping.
6. **Dual-Track Container Verification:**
   - Open output video in VLC; press **`b`** to verify instant switching between English and Hindi audio tracks.
