"""Dynamic primary/secondary language code-mixing.

The matrix is deliberately data-driven: a pair is not restricted to a fixed
allow-list. Gemini can synthesize any two configured languages, while the
offline examples cover the combinations called out in the product brief.
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

from config import language_config
from pipeline.transcreation import OFFLINE_IDIOMS, transcreate
from utils.syllable_budget import budget_for, trim_to_budget


OFFLINE_MIXES: dict[tuple[str, str, str], dict[str, str]] = {
    ("hindi", "punjabi", "don't put all your eggs in one basket"): {
        "native": "भाई, सारा पैसा इक्को जगह मत ला, मार्केट विच बहुत वड्डा रिस्क हो सकदा!",
        "romanized": "Bhai, saara paisa ikko jagah mat laa, market vich vadda risk ho sakda!",
        "style": "Hind-Punjabi",
    },
    ("english", "punjabi", "don't put all your eggs in one basket"): {
        "native": "Bro, don't invest all money in one place, bohot vadda loss ho sakda!",
        "romanized": "Bro, don't invest all money in one place, bohot vadda loss ho sakda!",
        "style": "Punglish",
    },
    ("hindi", "english", "don't put all your eggs in one basket"): {
        "native": "भाई, sara paisa ek jagah mat lagao, market mein risk bohot zyada hai!",
        "romanized": "Bhai, sara paisa ek jagah mat lagao, market mein risk bohot zyada hai!",
        "style": "Hinglish",
    },
    ("tamil", "english", "don't put all your eggs in one basket"): {
        "native": "Macha, ore idathula ellam invest pannatha, market risk romba jaasthi da!",
        "romanized": "Macha, ore idathula ellam invest pannatha, market risk romba jaasthi da!",
        "style": "Tanglish",
    },
    ("telugu", "english", "don't put all your eggs in one basket"): {
        "native": "Bro, motham money okke daggara pettaku, market lo risk chala ekkuva untadi!",
        "romanized": "Bro, motham money okke daggara pettaku, market lo risk chala ekkuva untadi!",
        "style": "Tenglish",
    },
    ("hindi", "marathi", "don't put all your eggs in one basket"): {
        "native": "भावा, सगळा पैसा एकाच ठिकाणी लावू नको, मार्केटमध्ये लय रिस्क आहे!",
        "romanized": "Bhava, sagla paisa ekach thikani laavu nako, marketmadhe lay risk aahe!",
        "style": "Mumbaikar",
    },
}


_ROMAN_MAP = str.maketrans({
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ee", "उ": "u", "ऊ": "oo", "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au",
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n", "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m", "य": "y", "र": "r", "ल": "l", "व": "v", "श": "sh", "ष": "sh", "स": "s", "ह": "h", "ा": "a", "ि": "i", "ी": "i", "ु": "u", "ू": "u", "े": "e", "ै": "ai", "ो": "o", "ौ": "au", "ं": "n", "ः": "h", "्": "",
    "ਅ": "a", "ਆ": "aa", "ਇ": "i", "ਈ": "ee", "ਉ": "u", "ਊ": "oo", "ਏ": "e", "ਐ": "ai", "ਓ": "o", "ਔ": "au", "ਕ": "k", "ਖ": "kh", "ਗ": "g", "ਘ": "gh", "ਚ": "ch", "ਛ": "chh", "ਜ": "j", "ਝ": "jh", "ਟ": "t", "ਠ": "th", "ਡ": "d", "ਢ": "dh", "ਤ": "t", "ਥ": "th", "ਦ": "d", "ਧ": "dh", "ਨ": "n", "ਪ": "p", "ਫ": "ph", "ਬ": "b", "ਭ": "bh", "ਮ": "m", "ਯ": "y", "ਰ": "r", "ਲ": "l", "ਵ": "v", "ਸ": "s", "ਹ": "h", "ਾ": "a", "ਿ": "i", "ੀ": "i", "ੁ": "u", "ੂ": "u", "ੇ": "e", "ੈ": "ai", "ੋ": "o", "ੌ": "au", "ਂ": "n", "ੱ": "",
})


def romanize_text(text: str) -> str:
    """Best-effort Latin rendering for captions and social copy."""

    return re.sub(r"\s+", " ", text.translate(_ROMAN_MAP)).strip()


def _normalise(text: str) -> str:
    cleaned = text.replace("’", "'").replace("‘", "'").replace('"', "").replace('"', "")
    return re.sub(r"\s+", " ", cleaned.strip().lower()).rstrip(".!?")


def _gemini_mix(text: str, primary: str, secondary: str, intensity: int, script: str, api_key: str | None) -> dict[str, Any] | None:
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        prompt = (
            f"Primary language: {language_config(primary)['name']}\n"
            f"Secondary language: {language_config(secondary)['name']}\n"
            f"Code-mixing intensity: {intensity}/3 (1=15%, 2=30%, 3=50% secondary language)\n"
            f"Script preference: {script}\n\nText: {text}"
        )
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-1.5-flash"),
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=(
                    "You are an Indian bilingual dubbing director. Blend grammar and idioms naturally, "
                    "preserve humor and intent, and return strict JSON with native, romanized, detected_intent, style."
                ),
                response_mime_type="application/json",
                temperature=0.4,
            ),
        )
        raw_text = getattr(response, "text", None)
        if not raw_text:
            return None
        cleaned_json = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.IGNORECASE)
        cleaned_json = re.sub(r"\s*```$", "", cleaned_json.strip())
        data = json.loads(cleaned_json)
        if isinstance(data, dict) and (data.get("native") or data.get("romanized")):
            return data
    except Exception as exc:
        print(f"[DubX] Gemini code-mixing unavailable; using offline matrix: {exc}")
    return None


def code_mix_text(text: str, primary_language: str, secondary_language: str, intensity: int = 2, script: str = "native", api_key: str | None = None, duration_seconds: float | None = None) -> dict[str, Any]:
    """Generate a mixed-language result for any two configured languages."""

    primary = primary_language.strip().lower()
    secondary = secondary_language.strip().lower()
    language_config(primary)
    language_config(secondary)
    if primary == secondary:
        raise ValueError("Primary and secondary languages must be different")
    if intensity not in (1, 2, 3):
        raise ValueError("intensity must be 1, 2, or 3")
    script = script.strip().lower()
    if script not in {"native", "romanized", "dual"}:
        raise ValueError("script must be native, romanized, or dual")

    key = (primary, secondary, _normalise(text))
    result = _gemini_mix(text, primary, secondary, intensity, script, api_key)
    engine = "gemini" if result else None
    if not result:
        result = OFFLINE_MIXES.get(key)
        if result:
            engine = "offline-matrix"
    if not result:
        base = transcreate(text, primary, api_key=api_key, duration_seconds=duration_seconds)
        marker = {
            "english": "bro",
            "punjabi": "ve",
            "hindi": "bhai",
            "tamil": "da",
            "telugu": "bro",
        }.get(secondary, "bro")
        native = f"{base['transcreated_text']} {marker}!"
        result = {
            "native": native,
            "romanized": romanize_text(native),
            "style": f"{language_config(primary)['name']} + {language_config(secondary)['name']}",
            "detected_intent": base["detected_intent"],
        }
        engine = "offline-fallback"

    native = result.get("native") or result.get("transcreated_text") or text
    romanized = result.get("romanized") or romanize_text(native)
    if duration_seconds is not None:
        budget = budget_for(native, duration_seconds)
        if budget.status == "overflow":
            native = trim_to_budget(native, budget.target_syllables)
            romanized = trim_to_budget(romanized, budget.target_syllables)
    else:
        budget = None

    if script == "native":
        output = native
    elif script == "romanized":
        output = romanized
    else:
        output = f"{native}\n(Roman: {romanized})"
    return {
        "pillar": "Dual-Language Code-Mixing",
        "original_text": text,
        "primary_language": language_config(primary)["name"],
        "secondary_language": language_config(secondary)["name"],
        "intensity": intensity,
        "script": script,
        "style": result.get("style", f"{primary} + {secondary}"),
        "detected_intent": result.get("detected_intent", "Preserved contextual meaning"),
        "native_text": native,
        "romanized_text": romanized,
        "transcreated_text": output,
        "budget": budget,
        "engine": engine or "offline-matrix",
    }
