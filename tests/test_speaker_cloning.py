import base64
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from dubx_core import audio_to_audio_dub, video_to_video_dub
from pipeline.tts import synthesize


class _FakeSarvamResponse:
    audios = [base64.b64encode(b"RIFFfake-wav-data").decode("ascii")]


class _FakeTTS:
    def convert(self, **_kwargs):
        return _FakeSarvamResponse()


class _FakeSarvamClient:
    def __init__(self, **_kwargs):
        self.text_to_speech = _FakeTTS()


class TestSarvamSpeakerWorkflow(unittest.TestCase):
    def test_text_tts_uses_sarvam_not_edge(self):
        with tempfile.TemporaryDirectory() as directory, \
             patch.dict(os.environ, {"SARVAM_API_KEY": "test-key"}), \
             patch.dict(sys.modules, {"sarvamai": types.SimpleNamespace(SarvamAI=_FakeSarvamClient)}):
            output = str(Path(directory) / "speech.wav")
            result = synthesize("नमस्ते", "hindi", output_path=output)
            self.assertTrue(Path(output).is_file())
            self.assertEqual(Path(output).read_bytes(), b"RIFFfake-wav-data")
            self.assertEqual(result["backend"], "sarvam-bulbul:v3")
            self.assertFalse(result["cloned_voice"])

    def test_text_tts_rejects_fake_clone_request(self):
        with self.assertRaisesRegex(RuntimeError, "Sarvam Dubbing"):
            synthesize("नमस्ते", "hindi", output_path="unused.wav", clone_voice=True)

    def test_audio_clone_requires_explicit_consent_and_uses_sarvam_job(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "speaker.wav"
            source.write_bytes(b"RIFFsource")
            audio = Path(directory) / "dub.wav"
            srt = Path(directory) / "dub.srt"
            srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nनमस्ते\n", encoding="utf-8")

            with self.assertRaises(PermissionError):
                audio_to_audio_dub(str(source), clone_voice=True)

            job = {"job_id": "job_123", "clone_method": "sarvam-dubbing", "exports": {"audio": str(audio), "srt": str(srt)}}
            with patch("dubx_core.sarvam_dubbing_available", return_value=True), patch("dubx_core.dub_media", return_value=job) as mock_dub:
                result = audio_to_audio_dub(str(source), "hindi", clone_voice=True, voice_clone_consent=True)
            mock_dub.assert_called_once_with(str(source), "english", "hindi", "audio")
            self.assertTrue(result["voice_cloned"])
            self.assertEqual(result["clone_method"], "sarvam-dubbing")
            self.assertEqual(result["alignment_strategy"], "sarvam-source-timeline")

    def test_video_clone_uses_sarvam_source_timeline(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "speaker.mp4"
            source.write_bytes(b"fake-video")
            video = Path(directory) / "dub.mp4"
            audio = Path(directory) / "dub.wav"
            srt = Path(directory) / "dub.srt"
            srt.write_text("", encoding="utf-8")
            job = {"job_id": "job_456", "clone_method": "sarvam-dubbing", "exports": {"video": str(video), "audio": str(audio), "srt": str(srt)}}
            with patch("dubx_core.sarvam_dubbing_available", return_value=True), patch("dubx_core.dub_media", return_value=job) as mock_dub:
                result = video_to_video_dub(str(source), "tamil", clone_voice=True, voice_clone_consent=True)
            mock_dub.assert_called_once_with(str(source), "english", "tamil", "video")
            self.assertTrue(result["voice_cloned"])
            self.assertTrue(result["bgm_preserved"])


if __name__ == "__main__":
    unittest.main()
