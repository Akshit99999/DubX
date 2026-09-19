import unittest

from dubx_core import dual_language_code_mix, text_to_text_dub
from utils.subtitles import SubtitleSegment, format_srt, format_vtt
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


if __name__ == "__main__":
    unittest.main()
