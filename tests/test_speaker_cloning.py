import os
import unittest
from unittest.mock import MagicMock, patch

from dubx_core import audio_to_audio_dub, video_to_video_dub
from pipeline.tts import _edge_tts, synthesize
from utils.subtitles import SubtitleSegment


class TestSpeakerVoiceCloning(unittest.TestCase):
    def test_edge_tts_accepts_pitch_and_passes_to_communicate(self):
        with patch("edge_tts.Communicate") as mock_comm:
            from unittest.mock import AsyncMock
            mock_instance = MagicMock()
            mock_instance.save = AsyncMock()
            mock_comm.return_value = mock_instance

            import asyncio
            asyncio.run(_edge_tts("hello", "en-IN-PrabhatNeural", "out.mp3", rate="+10%", pitch="+15Hz"))

            mock_comm.assert_called_once_with(
                text="hello",
                voice="en-IN-PrabhatNeural",
                rate="+10%",
                pitch="+15Hz",
            )
            mock_instance.save.assert_awaited_once_with("out.mp3")

    def test_synthesize_metadata_and_edge_matcher(self):
        with patch("pipeline.tts.analyze_speaker_voice") as mock_analyze, \
             patch("pipeline.tts._run_async") as mock_run:
            mock_analyze.return_value = {
                "f0_hz": 215.4,
                "detected_gender": "female",
                "gender_used": "female",
                "pitch_offset_hz": 5,
                "pitch_str": "+5Hz",
            }

            res = synthesize(
                text="परीक्षण",
                language="hindi",
                gender="auto",
                output_path="test_out.mp3",
                reference_audio="dummy_ref.wav",
                clone_voice=True,
            )

            mock_analyze.assert_called_once_with("dummy_ref.wav", "auto")
            self.assertEqual(res["output_path"], "test_out.mp3")
            self.assertEqual(res["f0_hz"], 215.4)
            self.assertEqual(res["pitch_offset"], "+5Hz")
            self.assertEqual(res["gender_used"], "female")
            self.assertEqual(res["voice_used"], "hi-IN-SwaraNeural")
            self.assertTrue(res["cloned_voice"])
            mock_run.assert_called_once()

    def test_synthesize_elevenlabs_attempt_and_fallback(self):
        with patch.dict(os.environ, {"ELEVENLABS_API_KEY": "fake_key_123"}), \
             patch("pipeline.tts.analyze_speaker_voice") as mock_analyze, \
             patch("pipeline.tts._elevenlabs_clone_and_tts") as mock_11labs, \
             patch("pipeline.tts._run_async") as mock_run:

            mock_analyze.return_value = {
                "f0_hz": 120.0,
                "detected_gender": "male",
                "gender_used": "male",
                "pitch_offset_hz": -5,
                "pitch_str": "-5Hz",
            }

            mock_run.return_value = "test_out.mp3"

            # Scenario A: ElevenLabs succeeds
            mock_11labs.return_value = "elevenlabs:voice_abc"
            res_success = synthesize(
                text="परीक्षण",
                language="hindi",
                gender="auto",
                output_path="test_out.mp3",
                reference_audio="dummy_ref.wav",
                clone_voice=True,
            )
            self.assertEqual(res_success["voice_used"], "elevenlabs:voice_abc")
            self.assertTrue(res_success["cloned_voice"])
            mock_run.assert_not_called()

            # Scenario B: ElevenLabs fails -> falls back to Edge-TTS
            mock_11labs.side_effect = RuntimeError("ElevenLabs rate limit")
            with patch("pipeline.tts._edge_tts", return_value="test_out.mp3"):
                res_fallback = synthesize(
                    text="परीक्षण",
                    language="hindi",
                    gender="auto",
                    output_path="test_out.mp3",
                    reference_audio="dummy_ref.wav",
                    clone_voice=True,
                )
            self.assertEqual(res_fallback["voice_used"], "hi-IN-MadhurNeural")
            self.assertTrue(res_fallback["cloned_voice"])
            self.assertEqual(res_fallback["pitch_offset"], "-5Hz")
            mock_run.assert_called_once()

    def test_audio_to_audio_dub_passes_cloning_params_and_returns_metadata(self):
        with patch("dubx_core._resolve_audio_file") as mock_resolve, \
             patch("dubx_core.transcribe") as mock_transcribe, \
             patch("dubx_core._translated_segments") as mock_trans, \
             patch("dubx_core.synthesize") as mock_synth:

            from pathlib import Path
            mock_resolve.return_value = Path("dummy_speaker.wav")
            mock_transcribe.return_value = [SubtitleSegment(0.0, 1.0, "Hello")]
            mock_trans.return_value = ([SubtitleSegment(0.0, 1.0, "Hello", "नमस्ते")], "नमस्ते")
            mock_synth.return_value = {
                "output_path": "output.mp3",
                "f0_hz": 130.5,
                "speaker_f0_hz": 130.5,
                "pitch_offset": "+6Hz",
                "gender_used": "male",
                "voice_used": "hi-IN-MadhurNeural",
                "cloned_voice": True,
            }

            res = audio_to_audio_dub(
                "dummy_speaker.wav",
                target_language="hindi",
                gender="auto",
                output_path="custom_out.mp3",
                clone_voice=True,
            )

            mock_synth.assert_called_once_with(
                "नमस्ते",
                "hindi",
                gender="auto",
                output_path="custom_out.mp3",
                rate="+0%",
                reference_audio="dummy_speaker.wav",
                clone_voice=True,
            )

            self.assertTrue(res["cloned_voice"])
            self.assertEqual(res["speaker_f0_hz"], 130.5)
            self.assertEqual(res["pitch_offset"], "+6Hz")
            self.assertEqual(res["voice_used"], "hi-IN-MadhurNeural")

    def test_video_to_video_dub_passes_cloning_params_and_returns_metadata(self):
        with patch("dubx_core._resolve_video_file") as mock_resolve, \
             patch("dubx_core.extract_audio") as mock_extract, \
             patch("dubx_core.separate_stems") as mock_separate, \
             patch("dubx_core.transcribe") as mock_transcribe, \
             patch("dubx_core._translated_segments") as mock_trans, \
             patch("dubx_core.synthesize") as mock_synth, \
             patch("dubx_core.remux_video") as mock_remux:

            from pathlib import Path
            mock_resolve.return_value = Path("dummy_video.mp4")
            mock_extract.return_value = "extracted.wav"
            mock_separate.return_value = ("vocals.wav", "bgm.wav")
            mock_transcribe.return_value = [SubtitleSegment(0.0, 1.0, "Hello")]
            mock_trans.return_value = ([SubtitleSegment(0.0, 1.0, "Hello", "नमस्ते")], "नमस्ते")
            mock_remux.return_value = "final_video.mp4"
            mock_synth.return_value = {
                "output_path": "dubbed.mp3",
                "f0_hz": 220.0,
                "speaker_f0_hz": 220.0,
                "pitch_offset": "+10Hz",
                "gender_used": "female",
                "voice_used": "hi-IN-SwaraNeural",
                "cloned_voice": True,
            }

            res = video_to_video_dub(
                "dummy_video.mp4",
                target_language="hindi",
                gender="auto",
                clone_voice=True,
            )

            mock_synth.assert_called_once()
            _, synth_kwargs = mock_synth.call_args
            self.assertEqual(synth_kwargs.get("reference_audio"), "vocals.wav")
            self.assertEqual(synth_kwargs.get("clone_voice"), True)

            self.assertTrue(res["cloned_voice"])
            self.assertEqual(res["speaker_f0_hz"], 220.0)
            self.assertEqual(res["pitch_offset"], "+10Hz")
            self.assertEqual(res["voice_used"], "hi-IN-SwaraNeural")


if __name__ == "__main__":
    unittest.main()
