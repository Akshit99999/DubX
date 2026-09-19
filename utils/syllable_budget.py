"""Indic-aware syllable/akshara budgeting helpers.

Indic scripts are closer to orthographic syllable units than English phoneme
counts.  This intentionally lightweight counter is useful for the review UI
and for a deterministic offline fallback; a phonemizer can replace it later.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


_VIRAMAS = {
    "\u094d",  # Devanagari virama
    "\u09cd",  # Bengali virama
    "\u0a4d",  # Gurmukhi virama
    "\u0acd",  # Gujarati virama
    "\u0bcd",  # Tamil virama
    "\u0c4d",  # Telugu virama
    "\u0ccd",  # Kannada virama
    "\u0d4d",  # Malayalam virama
}

_INDIC_INDEPENDENT_VOWELS = {
    # Devanagari (Hindi, Marathi)
    "अ", "आ", "इ", "ई", "उ", "ऊ", "ऋ", "ए", "ऐ", "ओ", "औ",
    # Bengali
    "অ", "আ", "ই", "ঈ", "উ", "ঊ", "ঋ", "এ", "ঐ", "ও", "ঔ",
    # Gurmukhi (Punjabi)
    "ਅ", "ਆ", "ਇ", "ਈ", "ਉ", "ਊ", "ਏ", "ਐ", "ਓ", "ਔ",
    # Gujarati
    "અ", "આ", "ઇ", "ઈ", "ઉ", "ઊ", "ઋ", "એ", "ઐ", "ઓ", "ઔ",
    # Tamil
    "அ", "ஆ", "இ", "ஈ", "உ", "ஊ", "எ", "ஏ", "ஐ", "ஒ", "ஓ", "ஔ",
    # Telugu
    "అ", "ఆ", "ఇ", "ఈ", "ఉ", "ఊ", "ఋ", "ఎ", "ఏ", "ఐ", "ఒ", "ఓ", "ఔ",
    # Kannada
    "ಅ", "ಆ", "ಇ", "ಈ", "ಉ", "ಊ", "ಋ", "ಎ", "ಏ", "ಐ", "ಒ", "ಓ", "ಔ",
    # Malayalam
    "അ", "ആ", "ഇ", "ഈ", "ഉ", "ഊ", "ഋ", "എ", "ഏ", "ഐ", "ഒ", "ഓ", "ഔ",
}


def _is_indic_consonant(ch: str) -> bool:
    cp = ord(ch)
    return (
        (0x0915 <= cp <= 0x0939) or (0x0958 <= cp <= 0x095F) or  # Devanagari
        (0x0995 <= cp <= 0x09B9) or (0x09DC <= cp <= 0x09DF) or  # Bengali
        (0x0A15 <= cp <= 0x0A39) or (0x0A59 <= cp <= 0x0A5E) or  # Gurmukhi
        (0x0A95 <= cp <= 0x0AB9) or                              # Gujarati
        (0x0B95 <= cp <= 0x0BB9) or                              # Tamil
        (0x0C15 <= cp <= 0x0C39) or (0x0C58 <= cp <= 0x0C5A) or  # Telugu
        (0x0C95 <= cp <= 0x0CB9) or (0x0CDE == cp) or            # Kannada
        (0x0D15 <= cp <= 0x0D3A)                                 # Malayalam
    )


def count_syllables(text: str) -> int:
    """Estimate spoken syllables/aksharas, returning at least one for non-empty text."""

    if not text or not text.strip():
        return 0

    indic_aksharas = 0
    n = len(text)
    for i, ch in enumerate(text):
        if ch in _INDIC_INDEPENDENT_VOWELS:
            indic_aksharas += 1
        elif _is_indic_consonant(ch):
            next_ch = text[i + 1] if i + 1 < n else ""
            if next_ch not in _VIRAMAS:
                indic_aksharas += 1

    latin_words = re.findall(r"[A-Za-z]+", text)
    latin = 0
    for word in latin_words:
        groups = re.findall(r"[aeiouy]+", word.lower())
        latin += max(1, len(groups))

    punctuation_words = len(re.findall(r"\S+", text))
    return max(1, indic_aksharas + latin or punctuation_words)


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
