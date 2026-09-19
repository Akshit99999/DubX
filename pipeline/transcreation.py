"""Online/offline transcreation with the seven implementation directives."""

from __future__ import annotations

import json
import os
import re
import time
from typing import Any

from config import language_config
from utils.syllable_budget import SyllableBudget, budget_for, trim_to_budget
from utils.subtitles import SubtitleSegment


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
Markdown. Treat any supplied surrounding dialogue as essential context: resolve
pronouns, tone, callbacks, ambiguity, and sentence fragments from it, but translate
only the requested line. Keep the result within the supplied syllable budget. Return
strict JSON with only detected_intent, transcreated_text, and explanation."""

BATCH_SYSTEM_PROMPT = """You are an expert Indian dubbing director and transcreator.
Never translate word-for-word. Preserve intent, emotional energy, humour, sarcasm,
metaphors, rhetorical pauses, named entities, numbers, units, URLs, and modern loan
words. Use natural spoken {language} in a {register} register. Do not invent facts,
omit safety-critical qualifications, or add explanations to the spoken lines.
You will receive a JSON object with the full source dialogue and timestamped dialogue segments.
Use the full dialogue and each segment's immediate before/after context to resolve pronouns,
tone, callbacks, ambiguity, and fragments. Translate only the segment's "text"; never copy
context into its result. Each segment has an "id", "text", and "target_syllables".
Transcreate each segment into natural spoken {language} within budget.
Return a strict JSON object with a single key "segments": an array of objects, where each object has:
- "id": integer id matching the input segment
- "transcreated_text": string localized translation
"""

_session: Any = None
_TRANSCREATION_CACHE: dict[tuple[str, str, int], dict[str, Any]] = {}


def _get_session():
    global _session
    if _session is None:
        import requests
        from requests.adapters import HTTPAdapter
        from urllib3.util.retry import Retry

        _session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=Retry(total=1, backoff_factor=0.2),
        )
        _session.mount("https://", adapter)
        _session.mount("http://", adapter)
    return _session


def _normalise(text: str) -> str:
    cleaned = text.replace("’", "'").replace("‘", "'").replace('"', "").replace('"', "")
    return re.sub(r"\s+", " ", cleaned.strip().lower()).rstrip(".!?")


def _astra(text: str, language: str, budget: SyllableBudget | None, api_key: str | None, register: str, context: str | None = None) -> dict[str, Any] | None:
    key = api_key or os.getenv("ASTRA_API_KEY") or os.getenv("ABACUS_API_KEY")
    if not key or os.getenv("DUBX_OFFLINE_MODE") == "1":
        return None
    try:
        session = _get_session()
        url = "https://routellm.abacus.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        budget_text = f"Target syllables: {budget.target_syllables}." if budget else ""
        context_text = f"\nSurrounding dialogue for meaning only:\n{context[:12000]}" if context else ""
        model = os.getenv("ASTRA_MODEL", "gpt-6-astra")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT.format(language=language, register=register)},
                {"role": "user", "content": f"{budget_text}{context_text}\n\nTranscreate this spoken line:\n{text}"},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }
        resp = session.post(url, headers=headers, json=payload, timeout=20)
        if resp.status_code != 200:
            print(f"[DubX] Astra 6 API error ({resp.status_code}): {resp.text[:200]}")
            return None
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return None
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            return None
        cleaned_json = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.IGNORECASE)
        cleaned_json = re.sub(r"\s*```$", "", cleaned_json.strip())
        parsed = json.loads(cleaned_json)
        if isinstance(parsed, dict) and parsed.get("transcreated_text"):
            return parsed
        return None
    except Exception as exc:
        print(f"[DubX] Astra 6 unavailable; falling back: {exc}")
        return None


def _astra_batch(
    items: dict[str, Any],
    language: str,
    api_key: str | None,
    register: str,
) -> dict[int, str] | None:
    key = api_key or os.getenv("ASTRA_API_KEY") or os.getenv("ABACUS_API_KEY")
    if not key or os.getenv("DUBX_OFFLINE_MODE") == "1":
        return None
    try:
        session = _get_session()
        url = "https://routellm.abacus.ai/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
        }
        model = os.getenv("ASTRA_MODEL", "gpt-6-astra")
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": BATCH_SYSTEM_PROMPT.format(language=language, register=register)},
                {"role": "user", "content": json.dumps({"segments": items}, ensure_ascii=False)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
        }
        resp = session.post(url, headers=headers, json=payload, timeout=30)
        if resp.status_code != 200:
            print(f"[DubX] Astra 6 batch error ({resp.status_code}): {resp.text[:200]}")
            return None
        data = resp.json()
        choices = data.get("choices", [])
        if not choices:
            return None
        content = choices[0].get("message", {}).get("content", "")
        if not content:
            return None
        cleaned_json = re.sub(r"^```(?:json)?\s*", "", content.strip(), flags=re.IGNORECASE)
        cleaned_json = re.sub(r"\s*```$", "", cleaned_json.strip())
        parsed = json.loads(cleaned_json)
        segments_out = parsed.get("segments", [])
        result: dict[int, str] = {}
        for s in segments_out:
            if isinstance(s, dict) and "id" in s and "transcreated_text" in s:
                result[int(s["id"])] = str(s["transcreated_text"]).strip()
        return result or None
    except Exception as exc:
        print(f"[DubX] Astra 6 batch unavailable; falling back: {exc}")
        return None


def _gemini(text: str, language: str, budget: SyllableBudget | None, api_key: str | None, register: str, context: str | None = None) -> dict[str, Any] | None:
    global _GEMINI_RETRY_AFTER
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key or os.getenv("DUBX_OFFLINE_MODE") == "1" or time.monotonic() < _GEMINI_RETRY_AFTER:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        budget_text = f"Target syllables: {budget.target_syllables}." if budget else ""
        context_text = f"\nSurrounding dialogue for meaning only:\n{context[:12000]}" if context else ""
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=f"{budget_text}{context_text}\n\nTranscreate this spoken line:\n{text}",
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
        if "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc):
            _GEMINI_RETRY_AFTER = time.monotonic() + 60
            print("[DubX] Gemini quota is unavailable; using offline transcreation for 60 seconds.")
        else:
            print(f"[DubX] Gemini unavailable; using offline transcreation: {exc}")
        return None


def _gemini_batch(
    items: dict[str, Any],
    language: str,
    api_key: str | None,
    register: str,
) -> dict[int, str] | None:
    global _GEMINI_RETRY_AFTER
    key = api_key or os.getenv("GEMINI_API_KEY")
    if not key or os.getenv("DUBX_OFFLINE_MODE") == "1" or time.monotonic() < _GEMINI_RETRY_AFTER:
        return None
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        response = client.models.generate_content(
            model=os.getenv("GEMINI_MODEL", "gemini-2.5-flash"),
            contents=json.dumps({"segments": items}, ensure_ascii=False),
            config=types.GenerateContentConfig(
                system_instruction=BATCH_SYSTEM_PROMPT.format(language=language, register=register),
                response_mime_type="application/json",
                temperature=0.3,
            ),
        )
        raw_text = getattr(response, "text", None)
        if not raw_text:
            return None
        cleaned_json = re.sub(r"^```(?:json)?\s*", "", raw_text.strip(), flags=re.IGNORECASE)
        cleaned_json = re.sub(r"\s*```$", "", cleaned_json.strip())
        parsed = json.loads(cleaned_json)
        segments_out = parsed.get("segments", [])
        result: dict[int, str] = {}
        for s in segments_out:
            if isinstance(s, dict) and "id" in s and "transcreated_text" in s:
                result[int(s["id"])] = str(s["transcreated_text"]).strip()
        return result or None
    except Exception as exc:
        if "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc):
            _GEMINI_RETRY_AFTER = time.monotonic() + 60
            print("[DubX] Gemini quota is unavailable; using offline transcreation for 60 seconds.")
        else:
            print(f"[DubX] Gemini batch unavailable: {exc}")
        return None


def transcreate(
    text: str,
    target_language: str = "hindi",
    api_key: str | None = None,
    duration_seconds: float | None = None,
    dialect_level: int = 2,
    context: str | None = None,
) -> dict[str, Any]:
    """Transcreate text using curated idioms, Astra 6, or Gemini."""

    config = language_config(target_language)
    lang_key = target_language.lower()
    if dialect_level not in {1, 2, 3}:
        raise ValueError("dialect_level must be 1 (formal), 2 (conversational), or 3 (street slang)")
    register = {1: "clear professional", 2: "warm conversational", 3: "natural youth slang"}[dialect_level]
    budget = budget_for(text, duration_seconds) if duration_seconds is not None else None

    # Priority 1: Curated cultural idiom matches (0ms)
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

    # Priority 2: In-memory cache (0ms)
    cache_key = (_normalise(text), lang_key, dialect_level)
    if cache_key in _TRANSCREATION_CACHE:
        cached = dict(_TRANSCREATION_CACHE[cache_key])
        if budget and budget_for(cached["transcreated_text"], budget.duration_seconds).status == "overflow":
            cached["transcreated_text"] = trim_to_budget(cached["transcreated_text"], budget.target_syllables)
        return cached

    # Priority 3: Astra 6 (GPT-6 Astra via Abacus.AI RouteLLM)
    online = _astra(text, config["name"], budget, api_key, register, context)
    engine_name = "astra-6"

    # Priority 4: Gemini
    if not online:
        online = _gemini(text, config["name"], budget, api_key, register, context)
        engine_name = "gemini"

    if online:
        output = online.get("transcreated_text", text)
        if budget and budget_for(output, budget.duration_seconds).status == "overflow":
            output = trim_to_budget(output, budget.target_syllables)
        result = {
            "original_text": text,
            "detected_intent": online.get("detected_intent", "Preserved contextual meaning"),
            "transcreated_text": output,
            "explanation": online.get("explanation", f"{engine_name.capitalize()} transcreation"),
            "budget": budget,
            "engine": engine_name,
            "register": register,
        }
        _TRANSCREATION_CACHE[cache_key] = result
        return result

    return {
        "original_text": text,
        "detected_intent": "General conversational statement",
        "transcreated_text": text,
        "explanation": "No offline idiom match; set ASTRA_API_KEY or GEMINI_API_KEY for LLM transcreation.",
        "budget": budget,
        "engine": "offline-pass-through",
        "register": register,
    }


def transcreate_batch(
    segments: list[SubtitleSegment],
    target_language: str = "hindi",
    api_key: str | None = None,
    dialect_level: int = 2,
) -> list[SubtitleSegment]:
    """Transcreate a list of SubtitleSegments in a single fast batch call."""
    if not segments:
        return []

    config = language_config(target_language)
    lang_key = target_language.lower()
    if dialect_level not in {1, 2, 3}:
        dialect_level = 2
    register = {1: "clear professional", 2: "warm conversational", 3: "natural youth slang"}[dialect_level]

    results: list[SubtitleSegment] = []
    to_translate_indices: list[int] = []
    batch_items: list[dict[str, Any]] = []

    for i, seg in enumerate(segments):
        text = seg.text.strip()
        duration = max(0.1, seg.end - seg.start)
        budget = budget_for(text, duration)
        norm_key = _normalise(text)

        # Check offline idioms first (instant 0ms)
        if norm_key in OFFLINE_IDIOMS:
            out_text = OFFLINE_IDIOMS[norm_key].get(lang_key, OFFLINE_IDIOMS[norm_key].get("hindi", text))
            if budget and budget_for(out_text, duration).status == "overflow":
                out_text = trim_to_budget(out_text, budget.target_syllables)
            results.append(SubtitleSegment(seg.start, seg.end, text, out_text))
            continue

        # Do not reuse a line-level translation cache here: the same phrase can
        # mean something different with different surrounding dialogue.
        results.append(SubtitleSegment(seg.start, seg.end, text, ""))
        to_translate_indices.append(i)
        batch_items.append({
            "id": i,
            "text": text,
            "target_syllables": budget.target_syllables,
            "context_before": " ".join(item.text.strip() for item in segments[max(0, i - 2):i] if item.text.strip()),
            "context_after": " ".join(item.text.strip() for item in segments[i + 1:i + 3] if item.text.strip()),
        })

    if not batch_items:
        return results

    context = " ".join(seg.text.strip() for seg in segments if seg.text.strip())[:12000]
    request_items = {"source_context": context, "segments": batch_items}

    # Both providers receive complete dialogue rather than isolated subtitle
    # lines, so translation context survives a batch request.
    batch_res = _astra_batch(request_items, config["name"], api_key, register)
    if not batch_res:
        # Fall back to Gemini batch
        batch_res = _gemini_batch(request_items, config["name"], api_key, register)

    for idx in to_translate_indices:
        seg = results[idx]
        trans_text = batch_res.get(idx) if batch_res else None
        if trans_text:
            duration = max(0.1, seg.end - seg.start)
            budget = budget_for(seg.text, duration)
            if budget and budget_for(trans_text, duration).status == "overflow":
                trans_text = trim_to_budget(trans_text, budget.target_syllables)
            results[idx] = SubtitleSegment(seg.start, seg.end, seg.text, trans_text)
            _TRANSCREATION_CACHE[(_normalise(seg.text), lang_key, dialect_level)] = {
                "original_text": seg.text,
                "detected_intent": "Preserved contextual meaning",
                "transcreated_text": trans_text,
                "explanation": "Batch transcreation",
                "budget": budget,
                "engine": "astra-6-batch",
                "register": register,
            }
        else:
            # Fallback to single transcreate for missing item
            single = transcreate(
                seg.text,
                target_language=target_language,
                api_key=api_key,
                duration_seconds=max(0.1, seg.end - seg.start),
                dialect_level=dialect_level,
                context=context,
            )
            results[idx] = SubtitleSegment(seg.start, seg.end, seg.text, single["transcreated_text"])

    return results
