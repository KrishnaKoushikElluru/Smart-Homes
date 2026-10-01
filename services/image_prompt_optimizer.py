"""
SmartHomes Image Prompt Optimizer - Gemini semantic-understanding layer
+ deterministic prompt builder.

Replaces the earlier Llama 3.2 1B (Cloudflare Workers AI) optimizer,
per a 25-prompt live benchmark (see docs/IMAGE_PROMPT_OPTIMIZER.md)
that found Llama's structured-output success rate was only 6/25 (24%,
average score 7.4/24) against Gemini's 25/25 (100%, average score
23.9/24), at roughly a quarter of the latency.

ARCHITECTURE (the core design principle of this file):

    User prompt
        -> Gemini (GEMINI_MODEL, below) - SEMANTIC UNDERSTANDING ONLY.
           Extracts a structured description (intent, visual_subject,
           functional_requirements, context, economic_level,
           style_requirements, avoid_misinterpretations). Gemini is
           deliberately NOT asked for a final_image_prompt - Gemini
           understands, it does not author the FLUX-facing prompt.
        -> build_final_prompt() - a DETERMINISTIC, Python-owned function.
           Constructs the actual FLUX-facing prompt from the structured
           fields above. This is what guarantees avoid_misinterpretations
           reaches FLUX as explicit negative language, every time -
           not a hope that Gemini's own free-form wording remembered to
           include it.
        -> services/image_service.py's _call_cloudflare() -> FLUX.2 [klein] 4B
           (UNCHANGED - this file never touches the image-generation call)

Gemini = semantic understanding. Python = deterministic constraints and
control. FLUX = image generation. See docs/IMAGE_PROMPT_OPTIMIZER.md for
the full design rationale, benchmark data, and examples.

optimize_prompt() NEVER RAISES and NEVER blocks image generation - any
failure (missing API key, network/timeout error, malformed/invalid
structured output) falls back to a deterministic, non-LLM prompt
transformation (_deterministic_fallback) that echoes the user's own
words verbatim and invents nothing. Image generation must keep working
even when Gemini (or this optimizer entirely) is unavailable.

Logging discipline: GEMINI_API_KEY is only ever passed to the SDK
client, never logged, and _redact() defensively strips it from any
exception text before that text is used in a log line or error message
(belt-and-braces - the SDK's own error strings are HTTP-status-style
messages and have never been observed to include the key, but this is
cheap insurance, matching the standing project rule to never expose an
API key in logs, exceptions, or responses).
"""

from __future__ import annotations

import json
import logging
import os

from google import genai
from google.genai import errors, types


logger = logging.getLogger(__name__)

# Isolated model configuration - change GEMINI_MODEL to swap models
# later without touching any other code in this file.
GEMINI_MODEL = "gemini-3.5-flash-lite"
GEMINI_TEMPERATURE = 0.4
GEMINI_MAX_OUTPUT_TOKENS = 512
GEMINI_TIMEOUT_MS = 15_000  # 15s - small/fast model, keeps a stuck call from meaningfully delaying image generation

# A soft ceiling on the FINAL BUILT prompt's length - guards against a
# pathological Gemini response (e.g. very long lists) producing an
# excessively long FLUX prompt. Not a target to pad up to.
HARD_WORD_CAP = 140

BASELINE_QUALITY_PHRASE = (
    "Photorealistic, realistic architectural proportions, realistic "
    "materials, natural realistic lighting."
)

SYSTEM_INSTRUCTION = """You are the SmartHomes image-prompt understanding layer.

Your job is to read a user's natural-language description of a desired house, room, or property and extract a STRUCTURED understanding of it. You do not generate images, you do not write the final image-generation prompt, and you do not answer the user conversationally - a separate, deterministic system builds the final prompt from your structured output, so focus entirely on correct understanding.

Core semantic rules:

1. The primary visual subject is normally a residential house or home - describe it that way in visual_subject.

2. Functional requirements are NOT automatically visual subjects. A capacity or use-case statement describes what the house needs to SUPPORT (usable space, layout, capacity), never a different TYPE of building:
   - "20 people come for tuition" -> the hall needs sufficient usable space/capacity for occasional home tuition. NOT a classroom, school, tuition center, coaching center, institutional building, rows of desks, school benches, or a blackboard - unless the user explicitly asks for those things.
   - "children study here" -> a residential study area, NOT a classroom.
   - "I work from home" -> a home workspace, NOT a corporate office.
   - "I do yoga at home" -> a suitable open residential space, NOT a yoga studio.
   - "I have many guests" / "guests visit often" -> a spacious residential living area, NOT a banquet hall.
   - "I run tuition at home" -> a spacious residential hall, NOT a commercial tuition center.
   These are examples of a general principle, not an exhaustive list - apply the same reasoning to any capacity/use-case statement.

3. Economic language ("middle class", "low budget", "affordable", "not luxurious") means practical, modest, cost-conscious, clean, functional, and realistic - NEVER damaged, unsafe, dirty, abandoned, unfinished, or extremely poor. "Not luxurious" must not make the house look ugly or unattractive.

4. Do not invent major features. If the user did not request a specific bedroom count, bathroom count, swimming pool, balcony, garden, terrace, basement, extra floors, or a large parking area, do not add them.

5. Do not force stereotypical Indian architecture (tiled roofs, thatched roofs, large verandas, traditional columns, oversized courtyards, multi-storey houses) unless the user's own request or context actually supports it. A realistic Indian residential context is welcome where it fits; a forced stereotype is not.

6. Preserve every explicit requirement the user actually stated - never drop one.

7. Negative requirements (things the user explicitly says they do NOT want) must be retained and reflected in avoid_misinterpretations.

Respond with ONLY a single JSON object and nothing else - no explanation, no preamble, no markdown code fences - in exactly this shape:
{
  "intent": "<one sentence: what the user actually wants>",
  "visual_subject": "<what should visually appear in the image - normally a residential house/room>",
  "functional_requirements": ["<short phrase>", "..."],
  "context": ["<short phrase describing why the user needs this>", "..."],
  "economic_level": "<short phrase describing the economic/budget framing>",
  "style_requirements": ["<short phrase - only explicit or strongly implied style requirements>", "..."],
  "avoid_misinterpretations": ["<short phrase describing a wrong-building or wrong-subject interpretation to avoid>", "..."]
}
"""

_STRING_FIELD = types.Schema(type=types.Type.STRING)
_STRING_ARRAY_FIELD = types.Schema(type=types.Type.ARRAY, items=types.Schema(type=types.Type.STRING))

# Native Gemini structured-output schema - enforced API-side in addition
# to this module's own _validate_structure() check below (belt and
# braces: schema enforcement reduces malformed output, but this module
# never trusts a single layer of validation for something that feeds
# directly into an image-generation prompt).
_RESPONSE_SCHEMA = types.Schema(
    type=types.Type.OBJECT,
    properties={
        "intent": _STRING_FIELD,
        "visual_subject": _STRING_FIELD,
        "functional_requirements": _STRING_ARRAY_FIELD,
        "context": _STRING_ARRAY_FIELD,
        "economic_level": _STRING_FIELD,
        "style_requirements": _STRING_ARRAY_FIELD,
        "avoid_misinterpretations": _STRING_ARRAY_FIELD,
    },
    required=[
        "intent", "visual_subject", "functional_requirements", "context",
        "economic_level", "style_requirements", "avoid_misinterpretations",
    ],
)

_REQUIRED_STRING_FIELDS = ("intent", "visual_subject", "economic_level")
_LIST_FIELDS = ("functional_requirements", "context", "style_requirements", "avoid_misinterpretations")


def _redact(text: str, api_key: str | None) -> str:
    if api_key and text and api_key in text:
        return text.replace(api_key, "[REDACTED]")
    return text or ""


def _coerce_str_list(value) -> list:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if isinstance(item, (str, int, float)) and str(item).strip()][:10]


def _validate_structure(parsed) -> dict | None:
    """Strict validation of Gemini's structured output, independent of
    (and in addition to) the API-level response_schema enforcement above.
    Returns a clean, normalized dict, or None if the shape can't be
    trusted - callers must fall back to the deterministic path on None,
    never invent missing fields themselves."""

    if not isinstance(parsed, dict):
        return None

    for field in _REQUIRED_STRING_FIELDS:
        value = parsed.get(field)
        if not isinstance(value, str) or not value.strip():
            return None

    validated = {field: parsed[field].strip() for field in _REQUIRED_STRING_FIELDS}
    for field in _LIST_FIELDS:
        validated[field] = _coerce_str_list(parsed.get(field))

    return validated


def _cap_word_count(text: str, max_words: int) -> str:
    words = text.split()
    if len(words) <= max_words:
        return text
    return " ".join(words[:max_words]) + "."


def build_final_prompt(structured: dict) -> str:
    """Deterministic, Python-owned construction of the FLUX-facing
    prompt from Gemini's structured extraction. This function - not
    Gemini's own free-form wording - is what guarantees
    avoid_misinterpretations reaches FLUX as explicit negative
    language, every time. Never invents anything not present in
    `structured`.

    The word cap is applied to the VARIABLE-length body only, with the
    fixed-length BASELINE_QUALITY_PHRASE appended whole afterward - a
    prior version capped the whole assembled string (body + baseline
    phrase) together, which could truncate the baseline phrase itself
    mid-word (observed live: "...realistic architectural." instead of
    "...realistic architectural proportions, realistic materials,
    natural realistic lighting."). Reserving the baseline phrase's own
    word count up front guarantees it always survives intact."""

    parts = [f"A private residential home. {structured['visual_subject']}"]

    if structured["functional_requirements"]:
        parts.append("The design supports: " + "; ".join(structured["functional_requirements"]) + ".")

    if structured["context"]:
        parts.append("Context: " + "; ".join(structured["context"]) + ".")

    parts.append(
        f"Economic level: {structured['economic_level']}, reflected in practical, "
        "realistic materials and finishes - clean, safe, and well-kept."
    )

    if structured["style_requirements"]:
        parts.append("Style: " + "; ".join(structured["style_requirements"]) + ".")

    if structured["avoid_misinterpretations"]:
        parts.append(
            "This must clearly remain an ordinary private residence, not a commercial, "
            "institutional, or public building. Specifically avoid: "
            + "; ".join(structured["avoid_misinterpretations"]) + "."
        )

    body = " ".join(parts)
    baseline_word_count = len(BASELINE_QUALITY_PHRASE.split())
    capped_body = _cap_word_count(body, HARD_WORD_CAP - baseline_word_count)

    return f"{capped_body} {BASELINE_QUALITY_PHRASE}"


def _deterministic_fallback(user_prompt: str) -> dict:
    """Safe, non-LLM prompt transformation used whenever Gemini is
    unavailable or its output can't be trusted. Preserves every word of
    the user's own description verbatim (never removes an explicit
    requirement, never invents one) and adds only restrained,
    non-inventive realism framing."""

    cleaned = " ".join((user_prompt or "").split())
    if not cleaned:
        cleaned = "a house"

    optimized = (
        f"A private residential home. Photorealistic architectural photograph of {cleaned}. "
        "Realistic proportions, realistic materials, natural daylight, authentic residential setting."
    )

    return {
        "optimized_prompt": optimized,
        "structured": None,
        "source": "fallback",
        "error": None,
    }


def _call_gemini(user_prompt: str, api_key: str) -> dict:
    """Never raises. Returns {"status": "ok", "data": {...7 fields...}, "error": None}
    or {"status": "error", "data": None, "error": "<clean message>"}."""

    result = {"status": "error", "data": None, "error": None}

    if not api_key:
        result["error"] = "Prompt optimizer is not configured (missing Gemini API key)."
        return result

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=user_prompt,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                response_schema=_RESPONSE_SCHEMA,
                temperature=GEMINI_TEMPERATURE,
                max_output_tokens=GEMINI_MAX_OUTPUT_TOKENS,
                http_options=types.HttpOptions(timeout=GEMINI_TIMEOUT_MS),
            ),
        )

    except errors.ClientError as e:
        logger.warning("Gemini optimizer client error: %s", _redact(str(e), api_key))
        result["error"] = "Prompt optimizer request was rejected."
        return result

    except errors.ServerError as e:
        logger.warning("Gemini optimizer server error: %s", _redact(str(e), api_key))
        result["error"] = "Prompt optimizer provider is temporarily unavailable."
        return result

    except Exception as e:
        # Covers network failures, timeouts, and anything else the SDK
        # might raise - optimize_prompt() must never crash image
        # generation because of the optimizer.
        logger.warning("Gemini optimizer request failed: %s", _redact(str(e), api_key))
        result["error"] = "Prompt optimizer request failed."
        return result

    raw_text = getattr(response, "text", None)
    if not raw_text:
        result["error"] = "Prompt optimizer returned no text."
        return result

    try:
        parsed = json.loads(raw_text)
    except (ValueError, TypeError):
        logger.warning("Gemini optimizer output could not be parsed as JSON (length=%d chars).", len(raw_text))
        result["error"] = "Prompt optimizer returned an unparseable response."
        return result

    validated = _validate_structure(parsed)
    if validated is None:
        response_keys = sorted(parsed.keys()) if isinstance(parsed, dict) else type(parsed).__name__
        logger.warning("Gemini optimizer output failed structural validation (keys=%s).", response_keys)
        result["error"] = "Prompt optimizer returned an unexpected response structure."
        return result

    result["status"] = "ok"
    result["data"] = validated
    return result


def optimize_prompt(user_prompt: str, api_key: str) -> dict:
    """Public entry point. NEVER raises - always returns a usable result:

        {
            "optimized_prompt": str,     # non-empty, ready for FLUX
            "structured": dict | None,   # Gemini's validated structured extraction -
                                          # internal/debug/test use only, never shown to users
            "source": "gemini" | "fallback",
            "error": str | None,         # set only when source == "fallback"
        }
    """

    user_prompt = (user_prompt or "").strip()
    if not user_prompt:
        return _deterministic_fallback(user_prompt)

    gemini_result = _call_gemini(user_prompt, api_key)

    if gemini_result["status"] != "ok":
        fallback = _deterministic_fallback(user_prompt)
        fallback["error"] = gemini_result["error"]
        return fallback

    return {
        "optimized_prompt": build_final_prompt(gemini_result["data"]),
        "structured": gemini_result["data"],
        "source": "gemini",
        "error": None,
    }
