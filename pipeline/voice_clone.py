"""Speaker voice analysis and adaptive cross-lingual voice matching."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import wave
from pathlib import Path
from typing import Any

import numpy as np


def estimate_speaker_pitch(audio_path: str) -> float | None:
    """Estimate median fundamental frequency (F0 in Hz) using autocorrelation."""
    try:
        path = Path(audio_path)
        if not path.is_file():
            return None

        temp_wav = None
        if path.suffix.lower() != ".wav":
            if not shutil.which("ffmpeg"):
                return None
            temp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            temp_wav = temp.name
            temp.close()
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(path), "-t", "10", "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1", temp_wav],
                check=True, capture_output=True,
            )
            wav_to_read = temp_wav
        else:
            wav_to_read = str(path)

        try:
            with wave.open(wav_to_read, "rb") as wf:
                sample_rate = wf.getframerate()
                n_frames = min(sample_rate * 12, wf.getnframes())
                frames = wf.readframes(n_frames)
                data = np.frombuffer(frames, dtype=np.int16).astype(np.float32)
                if wf.getnchannels() > 1:
                    data = data.reshape(-1, wf.getnchannels()).mean(axis=1)
        finally:
            if temp_wav and os.path.exists(temp_wav):
                try:
                    os.remove(temp_wav)
                except OSError:
                    pass

        if len(data) < sample_rate:
            return None

        frame_size = int(0.05 * sample_rate)
        hop_size = int(0.025 * sample_rate)
        min_lag = int(sample_rate / 400)  # max pitch 400 Hz
        max_lag = int(sample_rate / 75)   # min pitch 75 Hz

        pitches = []
        for start in range(0, len(data) - frame_size, hop_size):
            frame = data[start:start + frame_size]
            if np.std(frame) < 300:
                continue
            corr = np.correlate(frame, frame, mode="full")
            corr = corr[len(corr) // 2 :]
            if len(corr) > max_lag:
                peak_lag = min_lag + int(np.argmax(corr[min_lag:max_lag]))
                if corr[peak_lag] > 0.3 * corr[0]:
                    pitches.append(sample_rate / peak_lag)

        return float(np.median(pitches)) if pitches else None
    except Exception as exc:
        print(f"[DubX] Voice pitch analysis note: {exc}")
        return None


def analyze_speaker_voice(audio_path: str, requested_gender: str = "auto") -> dict[str, Any]:
    """Extract pitch F0, detected gender, and adaptive pitch offset for voice cloning."""
    f0 = estimate_speaker_pitch(audio_path)
    if f0 is None:
        gender = requested_gender if requested_gender in {"male", "female"} else "male"
        return {
            "f0_hz": None,
            "detected_gender": gender,
            "gender_used": gender,
            "pitch_offset_hz": 0,
            "pitch_str": "+0Hz",
        }

    # Human voice pitch ranges:
    # Male: ~85-165 Hz (center ~125 Hz)
    # Female: ~165-280 Hz (center ~210 Hz)
    detected_gender = "female" if f0 >= 165.0 else "male"
    gender_used = requested_gender if requested_gender in {"male", "female"} else detected_gender

    base_f0 = 210.0 if gender_used == "female" else 125.0
    delta = int(round(f0 - base_f0))
    # Clamp to safe pitch shift range [-50Hz, +50Hz] to preserve natural vocal formants
    delta = max(-50, min(50, delta))
    pitch_str = f"{delta:+d}Hz"

    return {
        "f0_hz": round(f0, 1),
        "detected_gender": detected_gender,
        "gender_used": gender_used,
        "pitch_offset_hz": delta,
        "pitch_str": pitch_str,
    }
