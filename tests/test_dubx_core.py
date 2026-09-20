import unittest
import tempfile
from pathlib import Path
from unittest.mock import patch

from dubx_core import _mix_subtitle_tracks, dual_language_code_mix, text_to_text_dub
from pipeline.transcreation import transcreate_batch
from pipeline.remux import mix_timed_audio_tracks
from utils.subtitles import SubtitleSegment, format_srt, format_vtt, normalize_srt_file
from utils.syllable_budget import budget_for, count_syllables


class DubXOfflineTests(unittest.TestCase):
    def test_idiom_uses_cultural_equivalent(self):
        result = text_to_text_dub("Don't put all your eggs in one basket", "hindi")
        self.assertIn("एक जगह", result["transcreated_text"])
        self.assertNotIn("अंडे", result["transcreated_text"])

    def test_all_languages_have_offline_voice_config(self):
        for language in ("hindi", "tamil", "telugu", "bengali", "marathi", "kannada", "gujarati", "malayalam"):
            result = text_to_text_dub("piece of cake", language)
            self.assertTrue(result["transcreated_text"])

    def test_budget_status(self):
        budget = budget_for("This is easy", 1.0)
        self.assertGreaterEqual(budget.target_syllables, 1)
        self.assertIn(budget.status, {"fit", "tight", "overflow"})
        self.assertGreater(count_syllables("hello"), 0)

    def test_subtitle_formats(self):
        segments = [SubtitleSegment(0, 1.25, "Hello", "नमस्ते")]
        self.assertIn("00:00:00,000 --> 00:00:01,250", format_srt(segments))
        self.assertTrue(format_vtt(segments).startswith("WEBVTT"))

    def test_subtitle_cues_are_single_line(self):
        segment = SubtitleSegment(0, 1, "Hello\nthere", "नमस्ते\nदोस्त")
        self.assertEqual(segment.text, "Hello there")
        self.assertEqual(segment.translated_text, "नमस्ते दोस्त")

    def test_existing_srt_cues_are_normalized_to_one_line(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "source.srt"
            path.write_text("1\n00:00:00,000 --> 00:00:01,000\nनमस्ते\nदोस्त\n", encoding="utf-8")
            normalize_srt_file(path)
            self.assertIn("नमस्ते दोस्त", path.read_text(encoding="utf-8"))

    def test_timed_code_mix_uses_secondary_cues(self):
        with tempfile.TemporaryDirectory() as directory:
            primary = Path(directory) / "primary.srt"
            secondary = Path(directory) / "secondary.srt"
            primary.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nHindi one\n\n2\n00:00:01,000 --> 00:00:02,000\nHindi two\n",
                encoding="utf-8",
            )
            secondary.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\nPunjabi one\n\n2\n00:00:01,000 --> 00:00:02,000\nPunjabi two\n",
                encoding="utf-8",
            )
            segments, cues = _mix_subtitle_tracks(str(primary), str(secondary), intensity=3)
            self.assertEqual(len(segments), 2)
            self.assertEqual(len(cues), 1)
            self.assertTrue(any("Punjabi" in segment.translated_text for segment in segments))

    def test_timed_code_mix_keeps_secondary_audio_inside_selected_cues(self):
        with patch("pipeline.remux.require_ffmpeg"), patch("pipeline.remux._run") as run:
            mix_timed_audio_tracks("primary.wav", "punjabi.wav", [(1.0, 2.0)], "mixed.wav")
        command = run.call_args.args[0]
        graph = command[command.index("-filter_complex") + 1]
        self.assertIn("[1:a]volume=0:enable='not(between(t,1.000,2.000))'", graph)
        self.assertNotIn("volume=0,volume=1", graph)

    def test_dynamic_code_mix_matrix(self):
        result = dual_language_code_mix(
            "Don't put all your eggs in one basket",
            primary_language="hindi",
            secondary_language="punjabi",
            intensity=2,
            script="dual",
        )
        self.assertEqual(result["style"], "Hind-Punjabi")
        self.assertIn("Roman:", result["transcreated_text"])
        self.assertIn("विच", result["native_text"])

    def test_any_two_configured_languages_have_fallback(self):
        result = dual_language_code_mix("Subscribe to the app", "malayalam", "english", script="romanized")
        self.assertEqual(result["script"], "romanized")
        self.assertTrue(result["transcreated_text"])

    def test_batch_translation_receives_dialogue_context(self):
        segments = [
            SubtitleSegment(0, 1, "Maya picked up the package."),
            SubtitleSegment(1, 2, "She opened it."),
            SubtitleSegment(2, 3, "It was fragile."),
        ]
        with patch("pipeline.transcreation._astra_batch", return_value={0: "a", 1: "b", 2: "c"}) as batch:
            translated = transcreate_batch(segments, "hindi", api_key="test-key")
        request = batch.call_args.args[0]
        self.assertIn("Maya picked up the package.", request["source_context"])
        self.assertEqual(request["segments"][1]["context_before"], "Maya picked up the package.")
        self.assertEqual(request["segments"][1]["context_after"], "It was fragile.")
        self.assertEqual([item.translated_text for item in translated], ["a", "b", "c"])

    def test_text_context_is_forwarded_to_transcreation(self):
        with patch("dubx_core.transcreate") as transcreate:
            transcreate.return_value = {
                "transcreated_text": "संदर्भित पंक्ति",
                "detected_intent": "keep the previous scene's tone",
                "explanation": "context retained",
                "budget": None,
                "engine": "mock",
            }
            text_to_text_dub("That was close.", "hindi", context="Maya has just escaped a storm.")
        self.assertEqual(transcreate.call_args.kwargs["context"], "Maya has just escaped a storm.")


if __name__ == "__main__":
    unittest.main()
