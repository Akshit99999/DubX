"""Online/offline transcreation with the seven implementation directives."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from config import language_config
from utils.syllable_budget import SyllableBudget, budget_for, trim_to_budget


_GEMINI_RETRY_AFTER = 0.0


OFFLINE_IDIOMS: dict[str, dict[str, str]] = {
    "don't put all your eggs in one basket": {
        "meaning": "Do not concentrate all your resources or investments in one place to mitigate risk.",
        "hindi": "सारा पैसा एक जगह मत लगाओ भाई, रिस्क बढ़ जाएगा!",
        "tamil": "ஒரே இடத்தில் எல்லா பணத்தையும் போடாதீங்க, ரிஸ்க் அதிகம்!",
        "telugu": "మొత్తం డబ్బు ఒకే చోట పెట్టకు బ్రో, రిస్క్ ఎక్కువ!",
        "bengali": "সব টাকা এক জায়গায় ঢালিস না রে, ঝুঁকি বেশি!",
        "marathi": "सगळा पैसा एकाच ठिकाणी लावू नकोस रे, धोका वाढेल!",
        "kannada": "ಎಲ್ಲಾ ದುಡ್ಡನ್ನ ಒಂದೇ ಕಡೆ ಹಾಕಬೇಡ ಮಗಾ, ರಿಸ್ಕ್ ಜಾಸ್ತಿ!",
        "gujarati": "બધા પૈસા એક જ જગ્યાએ ન મૂક ભાઈ, રિસ્ક વધી જશે!",
        "malayalam": "എല്ലാ പണവും ഒരേ സ്ഥലത്ത് ഇടല്ലേ അളിയാ, റിസ്ക് കൂടും!",
    },
    "that's a steal at this price": {
        "meaning": "It is an extraordinarily good bargain / very cheap.",
        "hindi": "इस कीमत पर तो भाई एकदम लूट मची है!",
        "tamil": "இந்த விலைக்கு இது செம லாபம் டா!",
        "telugu": "ఈ ప్రైస్ కి ఇది సూపర్ డీల్ బ్రో!",
        "bengali": "এই দামে তো পুরো জলের দরে পেয়ে গেলে রে!",
        "marathi": "ह्या किमतीत तर एकदम भारी डील आहे रे!",
        "kannada": "ಈ ಬೆಲೆಗೆ ಇದು ಸಖತ್ ಆಫರ್ ಮಗಾ!",
        "gujarati": "આ ભાવે તો ભાઈ એકદમ બેસ્ટ ડીલ છે!",
        "malayalam": "ഈ വിലയ്ക്ക് ഇത് അടിപൊളി ഡീൽ ആണളിയാ!",
    },
    "he hit it out of the park": {
        "meaning": "He did an exceptionally brilliant job / succeeded completely.",
        "hindi": "उसने तो भाई एकदम कमाल कर दिया!",
        "tamil": "அவன் சும்மா பிரிச்சு மேஞ்சுட்டான் டா!",
        "telugu": "వాడు అదరగొట్టేసాడు రా!",
        "bengali": "ও তো ফাটিয়ে দিয়েছে রে!",
        "marathi": "त्याने तर कमालच केली राव!",
        "kannada": "ಅವನು ಧೂಳೆಬ್ಬಿಸಿಬಿಟ್ಟ ಮಗಾ!",
        "gujarati": "એણે તો ભાઈ કમાલ કરી નાખી!",
        "malayalam": "അവൻ പൊളിച്ചടുക്കിയളിയാ!",
    },
    "piece of cake": {
        "meaning": "Something that is very easy to accomplish.",
        "hindi": "अरे ये तो बाएं हाथ का खेल है!",
        "tamil": "இது ரொம்ப ஈஸி டா, அல்வா சாப்பிடுற மாதிரி!",
        "telugu": "ఇది చాలా ఈజీ రా, చిటికెలో చేసేయొచ్చు!",
        "bengali": "এটা তো জলভাত রে!",
        "marathi": "हे तर अगदी डाव्या हाताचा खेळ आहे!",
        "kannada": "ಇದು ನೀರು ಕುಡಿದಷ್ಟೇ ಸುಲಭ ಮಗಾ!",
        "gujarati": "આ તો એકદમ સહેલું છે ભાઈ!",
        "malayalam": "ഇത് ഈസിയല്ലേ അളിയാ, വെണ്ണയിൽ കത്തി പോലെ!",
    },
    "the market is on fire": {
        "meaning": "The financial market is experiencing huge bullish momentum.",
        "hindi": "मार्केट में तो भाई पूरी धूम मची है!",
        "tamil": "மார்க்கெட் தீ பிடிச்சு எரியுது டா!",
        "telugu": "మార్కెట్ లో ఫుల్ బూమ్ నడుస్తోంది రా!",
        "bengali": "মার্কেটে পুরো আগুন লেগেছে রে!",
        "marathi": "मार्केटमध्ये तर एकदम धूम सुरू आहे!",
        "kannada": "ಮಾರ್ಕೆಟ್ ಅಲ್ಲಿ ಸಖತ್ ಜೋಶ್ ಇದೆ ಮಗಾ!",
        "gujarati": "માર્કેટમાં તો ભાઈ ધૂમ મચી છે!",
        "malayalam": "മാർക്കറ്റിൽ മൊത്തം കത്തിക്കയറിയിരിക്കുവാണളിയാ!",
    },
    "break a leg": {
        "meaning": "Good luck / do your absolute best.",
        "hindi": "बेस्ट ऑफ लक भाई, कमाल कर देना!",
        "tamil": "வெற்றி பெற வாழ்த்துகள் டா, கலக்கு!",
        "telugu": "ఆల్ ది బెస్ట్ రా, అదరగొట్టు!",
        "bengali": "ফাটিয়ে দে রে, শুভকামনা রইল!",
        "marathi": "धमाल कर रे, ऑल द बेस्ट!",
        "kannada": "ಆಲ್ ದಿ ಬೆಸ್ಟ್ ಮಗಾ, ಧೂಳೆಬ್ಬಿಸು!",
        "gujarati": "ઓલ ધ બેસ્ટ ભાઈ, કમાલ કરી દે!",
        "malayalam": "ഓൾ ദ ബെസ്റ്റ് അളിയാ, പൊളിക്ക്!",
    },
}


SYSTEM_PROMPT = """You are an expert Indian dubbing director and transcreator.
Never translate word-for-word. Preserve intent, emotional energy, humour, sarcasm,
metaphors, rhetorical pauses, named entities, numbers, units, URLs, and modern loan
words. Use natural spoken {language} in a {register} register. Do not invent facts,
omit safety-critical qualifications, add explanations to the spoken line, or return
Markdown. Keep the result within the supplied syllable budget. Return strict JSON
with only detected_intent, transcreated_text, and explanation."""


def _normalise(text: str) -> str:
    cleaned = text.replace("’", "'").replace("‘", "'").replace('"', "").replace('"', "")
    return re.sub(r"\s+", " ", cleaned.strip().lower()).rstrip(".!?")


def _gemini(text: str, language: str, budget: SyllableBudget | None, api_key: str | None, register: str) -> dict[str, Any] | None:
    global _GEMINI_RETRY_AFTER
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key or os.getenv("DUBX_OFFLINE_MODE") == "1" or time.monotonic() < _GEMINI_RETRY_AFTER:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        budget_text = f"Target syllables: {budget.target_syllables}." if budget else ""
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=f"{budget_text}\nTranscreate this text:\n{text}",
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT.format(language=language, register=register),
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        raw_text = getattr(response, "text", None)
        if not raw_text:
            return None
        cleaned_json = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.IGNORECASE)
        cleaned_json = re.sub(r"\s*```$", "", cleaned_json.strip())
        data = json.loads(cleaned_json)
        if not isinstance(data, dict) or not data.get("transcreated_text"):
            return None
        return data
    except Exception as exc:
        # Avoid hammering a quota-limited key once a provider asks us to wait.
        if "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc):
            _GEMINI_RETRY_AFTER = time.monotonic() + 60
            print("[DubX] Gemini quota is unavailable; using offline transcreation for 60 seconds.")
        else:
            print(f"[DubX] Gemini unavailable; using offline transcreation: {exc}")
        return None


def transcreate(
    text: str,
    target_language: str = "hindi",
    api_key: str | None = None,
    duration_seconds: float | None = None,
    dialect_level: int = 2,
) -> dict[str, Any]:
    """Transcreate text, using Gemini when configured and an offline KB otherwise."""

    config = language_config(target_language)
    lang_key = target_language.lower()
    if dialect_level not in {1, 2, 3}:
        raise ValueError("dialect_level must be 1 (formal), 2 (conversational), or 3 (street slang)")
    register = {1: "clear professional", 2: "warm conversational", 3: "natural youth slang"}[dialect_level]
    budget = budget_for(text, duration_seconds) if duration_seconds is not None else None
    online = _gemini(text, config["name"], budget, api_key, register)
    if online:
        output = online.get("transcreated_text", text)
        if budget and budget_for(output, budget.duration_seconds).status == "overflow":
            output = trim_to_budget(output, budget.target_syllables)
        return {
            "original_text": text,
            "detected_intent": online.get("detected_intent", "Preserved contextual meaning"),
            "transcreated_text": output,
            "explanation": online.get("explanation", "Gemini transcreation"),
            "budget": budget,
            "engine": "gemini",
            "register": register,
        }

    entry = OFFLINE_IDIOMS.get(_normalise(text))
    if entry:
        output = entry.get(lang_key, entry.get("hindi", text))
        if budget and budget_for(output, budget.duration_seconds).status == "overflow":
            output = trim_to_budget(output, budget.target_syllables)
        return {
            "original_text": text,
            "detected_intent": entry["meaning"],
            "transcreated_text": output,
            "explanation": f"Matched cultural equivalent for {config['name']}.",
            "budget": budget,
            "engine": "offline-idiom",
            "register": register,
        }

    return {
        "original_text": text,
        "detected_intent": "General conversational statement",
        "transcreated_text": text,
        "explanation": "No offline idiom match; set GEMINI_API_KEY for LLM transcreation.",
        "budget": budget,
        "engine": "offline-pass-through",
        "register": register,
    }
