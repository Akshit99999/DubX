"""
text_to_dub.py - Text to Regional Audio Dubbing Engine for DubX.

Features:
1. Takes an English text, phrase, or idiom.
2. Transcreates it into the target Indian regional language (Hindi, Tamil, Telugu, Bengali, Marathi, Kannada)
   preserving meaning, metaphors, and colloquial slang (NOT literal word-for-word translation).
3. Synthesizes native, broadcast-grade regional speech using Microsoft Edge-TTS (100% free, zero API key required).
4. Saves the dubbed audio to an MP3 file and returns the transcreated text + audio path.
"""

import os
import sys
import json
import asyncio
import argparse
import edge_tts

# -----------------------------------------------------------------------------
# Regional Voice Mapping (Microsoft Edge Neural Broadcast Voices - Zero API Key)
# -----------------------------------------------------------------------------
VOICE_MAP = {
    "hindi": {
        "code": "hi",
        "name": "Hindi",
        "male": "hi-IN-MadhurNeural",
        "female": "hi-IN-SwaraNeural",
        "default": "hi-IN-MadhurNeural"
    },
    "tamil": {
        "code": "ta",
        "name": "Tamil",
        "male": "ta-IN-ValluvarNeural",
        "female": "ta-IN-PallaviNeural",
        "default": "ta-IN-ValluvarNeural"
    },
    "telugu": {
        "code": "te",
        "name": "Telugu",
        "male": "te-IN-MohanNeural",
        "female": "te-IN-ShrutiNeural",
        "default": "te-IN-MohanNeural"
    },
    "bengali": {
        "code": "bn",
        "name": "Bengali",
        "male": "bn-IN-BashkarNeural",
        "female": "bn-IN-TanishaaNeural",
        "default": "bn-IN-BashkarNeural"
    },
    "marathi": {
        "code": "mr",
        "name": "Marathi",
        "male": "mr-IN-ManoharNeural",
        "female": "mr-IN-AarohiNeural",
        "default": "mr-IN-ManoharNeural"
    },
    "kannada": {
        "code": "kn",
        "name": "Kannada",
        "male": "kn-IN-GaganNeural",
        "female": "kn-IN-SapnaNeural",
        "default": "kn-IN-GaganNeural"
    },
    "gujarati": {
        "code": "gu",
        "name": "Gujarati",
        "male": "gu-IN-NiranjanNeural",
        "female": "gu-IN-DhwaniNeural",
        "default": "gu-IN-NiranjanNeural"
    },
    "malayalam": {
        "code": "ml",
        "name": "Malayalam",
        "male": "ml-IN-MidhunNeural",
        "female": "ml-IN-SobhanaNeural",
        "default": "ml-IN-MidhunNeural"
    }
}

# -----------------------------------------------------------------------------
# Offline Fallback Idiom & Metaphor Knowledge Base
# (Ensures zero-failure demonstration even without an active Gemini API key)
# -----------------------------------------------------------------------------
OFFLINE_IDIOMS = {
    "don't put all your eggs in one basket": {
        "meaning": "Do not concentrate all your resources or investments in one place to mitigate risk.",
        "hindi": "सारा पैसा एक जगह मत लगाओ भाई, रिस्क बढ़ जाएगा!",
        "tamil": "ஒரே இடத்தில் எல்லா பணத்தையும் போடாதீங்க, ரிஸ்க் அதிகம்!",
        "telugu": "మొత్తం డబ్బు ఒకే చోట పెట్టకు బ్రో, రిస్క్ ఎక్కువ!",
        "bengali": "সব টাকা এক জায়গায় ঢালিস না রে, ঝুঁকি বেশি!",
        "marathi": "सगळा पैसा एकाच ठिकाणी लावू नकोस रे, धोका वाढेल!",
        "kannada": "ಎಲ್ಲಾ ದುಡ್ಡನ್ನ ಒಂದೇ ಕಡೆ ಹಾಕಬೇಡ ಮಗಾ, ರಿಸ್ಕ್ ಜಾಸ್ತಿ!"
    },
    "that's a steal at this price": {
        "meaning": "It is an extraordinarily good bargain / very cheap.",
        "hindi": "इस कीमत पर तो भाई एकदम लूट मची है!",
        "tamil": "இந்த விலைக்கு இது செம லாபம் டா!",
        "telugu": "ఈ ప్రైస్ కి ఇది సూపర్ డీల్ బ్రో!",
        "bengali": "এই দামে তো পুরো জলের দরে পেয়ে গেলে রে!",
        "marathi": "ह्या किमतीत तर एकदम भारी डील आहे रे!",
        "kannada": "ಈ ಬೆಲೆಗೆ ಇದು ಸಖತ್ ಆಫರ್ ಮಗಾ!"
    },
    "he hit it out of the park": {
        "meaning": "He did an exceptionally brilliant job / succeeded completely.",
        "hindi": "उसने तो भाई एकदम कमाल कर दिया!",
        "tamil": "அவன் சும்மா பிரிச்சு மேஞ்சுட்டான் டா!",
        "telugu": "వాడు అదరగొట్టేసాడు రా!",
        "bengali": "ও তো ফাটিয়ে দিয়েছে রে!",
        "marathi": "त्याने तर कमालच केली राव!",
        "kannada": "ಅವನು ಧೂಳೆಬ್ಬಿಸಿಬಿಟ್ಟ ಮಗಾ!"
    },
    "piece of cake": {
        "meaning": "Something that is very easy to accomplish.",
        "hindi": "अरे ये तो बाएं हाथ का खेल है!",
        "tamil": "இது ரொம்ப ஈஸி டா, அல்வா சாப்பிடுற மாதிரி!",
        "telugu": "ఇది చాలా ఈజీ రా, చిటికెలో చేసేయొచ్చు!",
        "bengali": "এটা তো জলভাত রে!",
        "marathi": "हे तर अगदी डाव्या हाताचा खेळ आहे!",
        "kannada": "ಇದು ನೀರು ಕುಡಿದಷ್ಟೇ ಸುಲಭ ಮಗಾ!"
    },
    "the market is on fire": {
        "meaning": "The financial market is experiencing huge bullish momentum.",
        "hindi": "मार्केट में तो भाई पूरी धूम मची है!",
        "tamil": "மார்க்கெட் தீ பிடிச்சு எரியுது டா!",
        "telugu": "మార్కెట్ లో ఫుల్ బూమ్ నడుస్తోంది రా!",
        "bengali": "মার্কেটে পুরো আগুন লেগেছে রে!",
        "marathi": "मार्केटमध्ये तर एकदम धूम सुरू आहे!",
        "kannada": "ಮಾರ್ಕೆಟ್ ಅಲ್ಲಿ ಸಖತ್ ಜೋಶ್ ಇದೆ ಮಗಾ!"
    }
}

# -----------------------------------------------------------------------------
# Gemini 1.5 Transcreation Prompt
# -----------------------------------------------------------------------------
TRANSCREATION_SYSTEM_PROMPT = """
You are an expert Indian dubbing director and transcreator.
Your goal is to translate English text into natural, spoken colloquial {target_language} for audio dubbing.

CRITICAL INSTRUCTIONS:
1. NEVER TRANSLATE LITERALLY.
   - Preserve the speaker's INTENT, METAPHOR, HUMOR, and EMOTIONAL ENERGY.
   - If there is an idiom (e.g., "piece of cake", "break a leg", "on fire"), use the natural cultural equivalent.
2. KEEP MODERN LOAN WORDS IN CONVERSATIONAL SCRIPT:
   - Words like "subscribe", "portfolio", "phone", "app", "invest", "market" should be kept as natural modern loan words, NOT archaic textbook translations.
3. CONVERSATIONAL TONE:
   - Use natural conversational phrasing (e.g. Hinglish / Tanglish / conversational vernacular).
4. RETURN STRICT JSON:
   {{
     "original_text": "...",
     "detected_intent": "...",
     "literal_translation": "...",
     "transcreated_text": "...",
     "explanation": "..."
   }}
"""

def transcreate_with_gemini(text: str, target_language: str, api_key: str = None) -> dict:
    """Uses Gemini 1.5 Flash to transcreate text while preserving metaphors."""
    api_key = api_key or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None

    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        prompt = f"Transcreate this text into {target_language}:\n\n\"{text}\""
        
        response = client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt,
            config=types.GenerateContentConfig(
                system_instruction=TRANSCREATION_SYSTEM_PROMPT.format(target_language=target_language),
                response_mime_type="application/json",
                temperature=0.3
            )
        )
        return json.loads(response.text)
    except Exception as e:
        print(f"[Warning] Gemini API error: {e}. Falling back to offline engine.")
        return None

def transcreate_text(text: str, target_language: str = "hindi", api_key: str = None) -> dict:
    """Main transcreation function with online LLM + offline fallback."""
    lang_key = target_language.lower()
    
    # 1. Check if Gemini API is available
    result = transcreate_with_gemini(text, VOICE_MAP.get(lang_key, {}).get("name", "Hindi"), api_key)
    if result:
        return result

    # 2. Check offline idiom knowledge base
    clean_text = text.lower().strip().rstrip(".!?")
    if clean_text in OFFLINE_IDIOMS:
        idiom_data = OFFLINE_IDIOMS[clean_text]
        return {
            "original_text": text,
            "detected_intent": idiom_data["meaning"],
            "literal_translation": "[Literal word-for-word translation loses the metaphor]",
            "transcreated_text": idiom_data.get(lang_key, idiom_data["hindi"]),
            "explanation": f"Matched cultural equivalent for '{text}' in {lang_key.capitalize()}."
        }

    # 3. Smart rule-based conversational fallback
    return {
        "original_text": text,
        "detected_intent": "General conversational statement",
        "literal_translation": text,
        "transcreated_text": text,
        "explanation": "Direct transcription (set GEMINI_API_KEY for deep LLM transcreation)."
    }

# -----------------------------------------------------------------------------
# Edge-TTS Audio Dubbing Synthesis
# -----------------------------------------------------------------------------
async def synthesize_speech_async(text: str, voice_name: str, output_path: str, rate: str = "+0%") -> str:
    """Synthesizes speech asynchronously using Edge-TTS."""
    communicate = edge_tts.Communicate(text=text, voice=voice_name, rate=rate)
    await communicate.save(output_path)
    return output_path

def text_to_dubbed_audio(
    text: str,
    target_language: str = "hindi",
    gender: str = "male",
    output_path: str = None,
    api_key: str = None,
    rate: str = "+0%"
) -> dict:
    """
    End-to-End: Takes English text -> Transcreates meaning -> Generates dubbed regional audio MP3.
    """
    lang_key = target_language.lower()
    voice_info = VOICE_MAP.get(lang_key, VOICE_MAP["hindi"])
    voice_name = voice_info.get(gender.lower(), voice_info["default"])

    if not output_path:
        os.makedirs("output_dubbed", exist_ok=True)
        safe_name = "".join(c for c in text[:20] if c.isalnum() or c in (' ', '_')).rstrip()
        output_path = os.path.join("output_dubbed", f"{safe_name}_{lang_key}.mp3")

    # Step 1: Transcreate text without losing meaning
    print(f"\n[DubX] Transcreating '{text}' into {voice_info['name']}...")
    transcreation = transcreate_text(text, target_language=lang_key, api_key=api_key)
    regional_text = transcreation["transcreated_text"]
    print(f"[DubX] Transcreated Text: {regional_text}")

    # Step 2: Synthesize regional audio
    print(f"[DubX] Synthesizing speech with voice '{voice_name}'...")
    asyncio.run(synthesize_speech_async(regional_text, voice_name, output_path, rate=rate))
    print(f"[DubX] Dubbed audio saved to: {output_path}")

    return {
        "original_text": text,
        "target_language": voice_info["name"],
        "voice_used": voice_name,
        "transcreated_text": regional_text,
        "detected_intent": transcreation.get("detected_intent", ""),
        "audio_path": output_path
    }

# -----------------------------------------------------------------------------
# CLI Entrypoint
# -----------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="DubX: Text to Regional Audio Dubbing Engine")
    parser.add_argument("text", nargs="?", default="Don't put all your eggs in one basket", help="English text or idiom to dub")
    parser.add_argument("--lang", default="hindi", choices=list(VOICE_MAP.keys()), help="Target regional language")
    parser.add_argument("--gender", default="male", choices=["male", "female"], help="Voice gender")
    parser.add_argument("--output", default=None, help="Output MP3 file path")
    parser.add_argument("--rate", default="+0%", help="Speed adjustment (e.g. +10%, -5%)")

    args = parser.parse_args()

    result = text_to_dubbed_audio(
        text=args.text,
        target_language=args.lang,
        gender=args.gender,
        output_path=args.output,
        rate=args.rate
    )

    print("\n" + "="*60)
    print(" DUBX TEXT-TO-AUDIO DUBBING COMPLETE")
    print("="*60)
    print(f"Original Text:      {result['original_text']}")
    print(f"Target Language:    {result['target_language']}")
    print(f"Detected Intent:    {result['detected_intent']}")
    print(f"Transcreated Text:  {result['transcreated_text']}")
    print(f"Dubbed Audio File:  {result['audio_path']}")
    print("="*60)
