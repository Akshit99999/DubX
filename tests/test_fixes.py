import json
import os
import tempfile
import unittest
from pathlib import Path

import numpy as np

from app import _normalize_audio
from dubx_core import text_to_text_dub
from utils.ingestion import resolve_input
from utils.subtitles import SubtitleSegment
from utils.syllable_budget import count_syllables


class TestDubXFixes(unittest.TestCase):
    def test_normalize_audio_with_tuple(self):
        # Simulate Gradio microphone audio: (sample_rate, numpy_array)
        sr = 16000
        data = np.zeros(16000, dtype=np.int16)
        path = _normalize_audio((sr, data))
        self.assertTrue(os.path.exists(path))
        self.assertTrue(path.endswith(".wav"))
        if os.path.exists(path):
            os.remove(path)

    def test_normalize_audio_with_dict(self):
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(b"RIFFdummywav")
            temp_path = f.name
        try:
            res = _normalize_audio({"path": temp_path})
            self.assertEqual(res, temp_path)
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_resolve_input_with_dict(self):
        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
            f.write(b"dummy")
            temp_path = f.name
        try:
            res = resolve_input({"video": {"path": temp_path}}, output_dir=".")
            self.assertEqual(Path(res).resolve(), Path(temp_path).resolve())
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

    def test_count_syllables_indic(self):
        # Devanagari Hindi
        hindi_count = count_syllables("नमस्ते भारत")
        self.assertGreaterEqual(hindi_count, 3)
        # Punjabi
        punjabi_count = count_syllables("ਸਤਿ ਸ੍ਰੀ ਅਕਾਲ")
        self.assertGreaterEqual(punjabi_count, 3)
        # Tamil
        tamil_count = count_syllables("வணக்கம்")
        self.assertGreaterEqual(tamil_count, 2)

    def test_subtitle_segment_min_duration(self):
        seg = SubtitleSegment(start=1.0, end=1.0, text="hi")
        self.assertGreater(seg.end, seg.start)
        self.assertAlmostEqual(seg.end - seg.start, 0.1, places=2)

    def test_budget_json_serializable(self):
        res = text_to_text_dub("Don't put all your eggs in one basket", "hindi", duration_seconds=3.0)
        # Verify JSON serializability for Gradio gr.JSON
        serialized = json.dumps(res)
        self.assertIn("budget", serialized)
        self.assertIn("target_syllables", serialized)


if __name__ == "__main__":
    unittest.main()
