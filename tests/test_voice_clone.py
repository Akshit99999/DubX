import os
import tempfile
import unittest
import wave
from unittest.mock import patch

import numpy as np

from dubx_core import audio_to_audio_dub
from pipeline.tts import synthesize
from pipeline.voice_clone import analyze_speaker_voice, estimate_speaker_pitch
from utils.subtitles import SubtitleSegment


def _create_sine_wave(frequency: float, duration: float = 1.5, sample_rate: int = 16000) -> str:
    """Generate a clean synthetic sine wave WAV file for testing pitch estimation."""
    t = np.linspace(0, duration, int(sample_rate * duration), endpoint=False)
    signal = (np.sin(2 * np.pi * frequency * t) * 10000).astype(np.int16)
    temp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_path = temp.name
    temp.close()
    with wave.open(temp_path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(signal.tobytes())
    return temp_path


class TestVoiceClone(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # 130 Hz corresponds to typical male speech (center ~125 Hz)
        cls.male_audio = _create_sine_wave(130.0)
        # 220 Hz corresponds to typical female speech (center ~210 Hz)
        cls.female_audio = _create_sine_wave(220.0)

    @classmethod
    def tearDownClass(cls):
        for path in (cls.male_audio, cls.female_audio):
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass

    def test_estimate_speaker_pitch_male_and_female(self):
        # 130 Hz male audio
        male_pitch = estimate_speaker_pitch(self.male_audio)
        self.assertIsNotNone(male_pitch)
        self.assertAlmostEqual(male_pitch, 130.0, delta=5.0)

        # 220 Hz female audio
        female_pitch = estimate_speaker_pitch(self.female_audio)
        self.assertIsNotNone(female_pitch)
        self.assertAlmostEqual(female_pitch, 220.0, delta=5.0)

        # Non-existent or invalid files should return None
        self.assertIsNone(estimate_speaker_pitch("non_existent_file.wav"))

    def test_analyze_speaker_voice_auto_gender_and_pitch_offset(self):
        # Male 130 Hz analysis
        male_analysis = analyze_speaker_voice(self.male_audio, requested_gender="auto")
        self.assertEqual(male_analysis["detected_gender"], "male")
        self.assertEqual(male_analysis["gender_used"], "male")
        self.assertIsNotNone(male_analysis["f0_hz"])
        self.assertAlmostEqual(male_analysis["f0_hz"], 130.0, delta=5.0)
        # Male base pitch is 125 Hz, expected offset ~ +5 Hz
        self.assertEqual(male_analysis["pitch_offset_hz"], round(male_analysis["f0_hz"] - 125.0))
        self.assertEqual(male_analysis["pitch_str"], f"{male_analysis['pitch_offset_hz']:+d}Hz")

        # Female 220 Hz analysis
        female_analysis = analyze_speaker_voice(self.female_audio, requested_gender="auto")
        self.assertEqual(female_analysis["detected_gender"], "female")
        self.assertEqual(female_analysis["gender_used"], "female")
        self.assertIsNotNone(female_analysis["f0_hz"])
        self.assertAlmostEqual(female_analysis["f0_hz"], 220.0, delta=5.0)
        # Female base pitch is 210 Hz, expected offset ~ +10 Hz
        self.assertEqual(female_analysis["pitch_offset_hz"], round(female_analysis["f0_hz"] - 210.0))
        self.assertEqual(female_analysis["pitch_str"], f"{female_analysis['pitch_offset_hz']:+d}Hz")

        # Fallback when audio is missing
        missing_analysis = analyze_speaker_voice("missing.wav", requested_gender="auto")
        self.assertIsNone(missing_analysis["f0_hz"])
        self.assertEqual(missing_analysis["detected_gender"], "male")
        self.assertEqual(missing_analysis["pitch_offset_hz"], 0)
        self.assertEqual(missing_analysis["pitch_str"], "+0Hz")

    def test_synthesize_with_reference_audio(self):
        with patch("pipeline.tts._edge_tts") as mock_edge:
            async def fake_edge_tts(text, voice, output_path, rate="+0%", pitch="+0Hz"):
                return output_path

            mock_edge.side_effect = fake_edge_tts

            # Female reference audio: auto gender detection and pitch extraction
            res_female = synthesize(
                text="नमस्ते",
                language="hindi",
                gender="auto",
                output_path="test_out_female.mp3",
                reference_audio=self.female_audio,
            )
            mock_edge.assert_called_once()
            call_args = mock_edge.call_args
            # Voice should be Hindi female voice (SwaraNeural)
            voice_passed = call_args[0][1]
            self.assertEqual(voice_passed, "hi-IN-SwaraNeural")
            # Pitch parameter should match female pitch offset (~+10Hz)
            pitch_passed = call_args.kwargs.get("pitch") or (call_args[0][4] if len(call_args[0]) > 4 else None)
            self.assertIsNotNone(pitch_passed)
            self.assertTrue(pitch_passed.startswith("+") and pitch_passed.endswith("Hz"))
            self.assertNotEqual(pitch_passed, "+0Hz")
            self.assertEqual(res_female["gender_used"], "female")
            self.assertEqual(res_female["detected_gender"], "female")
            self.assertEqual(res_female["pitch_offset"], pitch_passed)

        with patch("pipeline.tts._edge_tts") as mock_edge_male:
            async def fake_edge_tts(text, voice, output_path, rate="+0%", pitch="+0Hz"):
                return output_path

            mock_edge_male.side_effect = fake_edge_tts

            # Male reference audio
            res_male = synthesize(
                text="नमस्ते",
                language="hindi",
                gender="auto",
                output_path="test_out_male.mp3",
                reference_audio=self.male_audio,
            )
            mock_edge_male.assert_called_once()
            call_args_male = mock_edge_male.call_args
            # Voice should be Hindi male voice (MadhurNeural)
            voice_passed_male = call_args_male[0][1]
            self.assertEqual(voice_passed_male, "hi-IN-MadhurNeural")
            pitch_passed_male = call_args_male.kwargs.get("pitch") or (call_args_male[0][4] if len(call_args_male[0]) > 4 else None)
            self.assertIsNotNone(pitch_passed_male)
            self.assertTrue(pitch_passed_male.startswith("+") and pitch_passed_male.endswith("Hz"))
            self.assertEqual(res_male["gender_used"], "male")
            self.assertEqual(res_male["detected_gender"], "male")
            self.assertEqual(res_male["pitch_offset"], pitch_passed_male)

    def test_audio_to_audio_dub_clone_voice_and_auto_gender(self):
        with patch("dubx_core.transcribe") as mock_transcribe, \
             patch("dubx_core._translated_segments") as mock_trans, \
             patch("pipeline.tts._edge_tts") as mock_edge:

            async def fake_edge_tts(text, voice, output_path, rate="+0%", pitch="+0Hz"):
                return output_path

            mock_edge.side_effect = fake_edge_tts
            mock_transcribe.return_value = [SubtitleSegment(0.0, 1.5, "Synthetic test voice")]
            mock_trans.return_value = (
                [SubtitleSegment(0.0, 1.5, "Synthetic test voice", "सिंथेटिक टेस्ट आवाज़")],
                "सिंथेटिक टेस्ट आवाज़",
            )

            # Female audio signal with clone_voice=True and gender="auto"
            res_female = audio_to_audio_dub(
                self.female_audio,
                target_language="hindi",
                gender="auto",
                clone_voice=True,
            )

            self.assertTrue(res_female["voice_cloned"])
            self.assertEqual(res_female["detected_gender"], "female")
            self.assertEqual(res_female["gender_used"], "female")
            self.assertEqual(res_female["voice_used"], "hi-IN-SwaraNeural")
            self.assertAlmostEqual(res_female["f0_hz"], 220.0, delta=5.0)
            self.assertTrue(res_female["pitch_offset"].startswith("+") and res_female["pitch_offset"].endswith("Hz"))

            # Verify edge_tts was invoked with computed pitch offset and female voice
            mock_edge.assert_called_once()
            call_args = mock_edge.call_args
            voice_passed = call_args[0][1]
            self.assertEqual(voice_passed, "hi-IN-SwaraNeural")
            pitch_passed = call_args.kwargs.get("pitch") or (call_args[0][4] if len(call_args[0]) > 4 else None)
            self.assertEqual(pitch_passed, res_female["pitch_offset"])

        with patch("dubx_core.transcribe") as mock_transcribe, \
             patch("dubx_core._translated_segments") as mock_trans, \
             patch("pipeline.tts._edge_tts") as mock_edge_male:

            async def fake_edge_tts(text, voice, output_path, rate="+0%", pitch="+0Hz"):
                return output_path

            mock_edge_male.side_effect = fake_edge_tts
            mock_transcribe.return_value = [SubtitleSegment(0.0, 1.5, "Synthetic test voice")]
            mock_trans.return_value = (
                [SubtitleSegment(0.0, 1.5, "Synthetic test voice", "सिंथेटिक टेस्ट आवाज़")],
                "सिंथेटिक टेस्ट आवाज़",
            )

            # Male audio signal with clone_voice=True and gender="auto"
            res_male = audio_to_audio_dub(
                self.male_audio,
                target_language="hindi",
                gender="auto",
                clone_voice=True,
            )

            self.assertTrue(res_male["voice_cloned"])
            self.assertEqual(res_male["detected_gender"], "male")
            self.assertEqual(res_male["gender_used"], "male")
            self.assertEqual(res_male["voice_used"], "hi-IN-MadhurNeural")
            self.assertAlmostEqual(res_male["f0_hz"], 130.0, delta=5.0)
            self.assertTrue(res_male["pitch_offset"].startswith("+") and res_male["pitch_offset"].endswith("Hz"))

            mock_edge_male.assert_called_once()
            call_args_male = mock_edge_male.call_args
            voice_passed_male = call_args_male[0][1]
            self.assertEqual(voice_passed_male, "hi-IN-MadhurNeural")
            pitch_passed_male = call_args_male.kwargs.get("pitch") or (call_args_male[0][4] if len(call_args_male[0]) > 4 else None)
            self.assertEqual(pitch_passed_male, res_male["pitch_offset"])


if __name__ == "__main__":
    unittest.main()
