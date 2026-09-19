"""Indic-aware syllable/akshara budgeting helpers.

Indic scripts are closer to orthographic syllable units than English phoneme
counts.  This intentionally lightweight counter is useful for the review UI
and for a deterministic offline fallback; a phonemizer can replace it later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_VOWELS = set("अआइईउऊऋएऐओऔািীুূৃেৈোৌெேைொோௌిీుూృెేైొోౌౘಂಃঅআইঈউঊএঐওঔিীুূৃেৈোৌㅏㅓㅗㅜㅡㅣ")
_LATIN_VOWELS = set("aeiouy")


def count_syllables(text: str) -> int:
    """Estimate spoken syllables, returning at least one for non-empty text."""

    if not text or not text.strip():
        return 0
    indic = sum(char in _VOWELS for char in text)
    latin_words = re.findall(r"[A-Za-z]+", text)
    latin = 0
    for word in latin_words:
        groups = re.findall(r"[aeiouy]+", word.lower())
        latin += max(1, len(groups))
    punctuation_words = len(re.findall(r"\S+", text))
    return max(1, indic + latin or punctuation_words)


@dataclass(frozen=True)
class SyllableBudget:
    duration_seconds: float
    target_syllables: int
    actual_syllables: int
    status: str
    ratio: float


def budget_for(text: str, duration_seconds: float, syllables_per_second: float = 4.0) -> SyllableBudget:
    """Calculate the review status used by the implementation specification."""

    duration = max(0.0, float(duration_seconds))
    target = max(1, round(duration * syllables_per_second))
    actual = count_syllables(text)
    ratio = actual / target if target else 0.0
    if ratio <= 1.0:
        status = "fit"
    elif ratio <= 1.15:
        status = "tight"
    else:
        status = "overflow"
    return SyllableBudget(duration, target, actual, status, round(ratio, 3))


def trim_to_budget(text: str, target_syllables: int) -> str:
    """Conservatively shorten a sentence at word boundaries for human review."""

    words = text.split()
    if count_syllables(text) <= target_syllables:
        return text
    kept: list[str] = []
    for word in words:
        candidate = " ".join(kept + [word])
        if count_syllables(candidate) > target_syllables and kept:
            break
        kept.append(word)
    return " ".join(kept).rstrip(" ,;:") or words[0]
