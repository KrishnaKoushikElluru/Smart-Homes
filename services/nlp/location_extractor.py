"""
Location MENTION extraction - not resolution.

This module identifies that a query mentions a place and classifies
what KIND of mention it looks like (a specific named POI vs a bare
city/locality name). It NEVER produces latitude/longitude, never calls
Mappls or OSM, and never maintains a table of known POI names/aliases.
Resolving "VIT Chennai" to an actual entity and coordinates is Phase
1's job entirely (services/mappls_service.py + osm_location_service.py)
- seeing that boundary violated would be a design bug, not a feature.

Two location.type outcomes are produced:

  "poi"          - a "near X / around X / close to X / within N km of X"
                   construction was found. X is very likely a specific
                   named place (a college, mall, hospital, landmark) -
                   exactly the kind of mention Phase 1 is built to
                   resolve.
  "area_or_city"  - a bare location phrase with no such preposition
                   (typically "in <place>" at the end of a query, or a
                   known Indian city name appearing anywhere). Could be
                   a city, a locality, or a full address - this module
                   deliberately does NOT try to tell those apart from
                   text alone, since doing so reliably needs exactly
                   the kind of gazetteer/gaming this task prohibits
                   building as a POI alias table. That distinction is
                   left to Phase 1 to figure out during resolution.

A small, explicitly-labeled list of major Indian city names is used
ONLY to raise confidence for the "area_or_city" case (e.g. recognizing
"Chennai" as a real city name, not a locality guess) - this is generic
geography, not POI-specific aliasing, and is never used to resolve
coordinates itself.
"""

from __future__ import annotations

import re
from typing import Optional

from services.nlp.schema import LocationMention

# Prepositions that signal "the following phrase is a specific place the
# user wants proximity to" - this is what distinguishes a POI mention
# from a bare area/city mention.
_POI_PREPOSITIONS = (
    r"near(?:by)?", r"around", r"close to", r"beside", r"next to",
    r"within\s+\d+(?:\.\d+)?\s*km\s+of", r"within\s+\d+(?:\.\d+)?\s*kilometers?\s+of",
)

# Words that end a location span (the start of some other constraint) -
# used to know where to STOP capturing the location phrase.
_STOP_WORDS = (
    "under", "below", "less than", "up to", "within", "above", "over",
    "more than", "around", "approx", "approximately", "about", "between",
    # Bare "for" (not just "for rent"/"for sale") catches any trailing
    # "for X" clause - e.g. a PG listing's "near SRM for boys" - since a
    # place name essentially never contains the bare word "for". Caught
    # during a spot-check with a fresh query outside the formal benchmark.
    "for", "with", "having", "bhk", "bedroom", "sqft",
    "sq ft", "square feet", "furnished", "unfurnished", "budget", "price",
    "rs", "inr", "crore", "lakh", "lakhs", "thousand",
)

# Word-bounded on both sides: without \b, a short stop word like "rs"
# would match as a bare substring inside an unrelated word (the exact
# bug that turned "University" into "Univeity" in normalize_query,
# before that was fixed - same class of mistake, different module).
_STOP_PATTERN = r"\b(?:" + "|".join(re.escape(w) for w in _STOP_WORDS) + r")\b"

# Generic geography, not a POI alias table: recognizing that "chennai"
# is a city name doesn't tell us WHERE it is, and resolving it still
# goes through Phase 1 exactly like a POI does.
_KNOWN_CITIES = {
    "chennai", "bangalore", "bengaluru", "hyderabad", "mumbai", "delhi",
    "pune", "kolkata", "coimbatore", "madurai", "trichy", "tiruchirapalli",
    "salem", "vellore", "tirunelveli", "erode", "kochi", "cochin",
    "thiruvananthapuram", "trivandrum", "visakhapatnam", "vizag",
    "gurgaon", "gurugram", "noida", "ahmedabad", "jaipur", "lucknow",
    "kanpur", "nagpur", "indore", "bhopal", "chandigarh", "mysore", "mysuru",
}


def _capture_phrase(text: str, start: int) -> str:
    """From `start`, capture tokens until a stop-word/end of string."""
    remainder = text[start:]
    m = re.search(_STOP_PATTERN, remainder)
    phrase = remainder[: m.start()] if m else remainder
    # Trim trailing connector words that shouldn't be part of the place name.
    phrase = re.sub(r"\s+(?:with|having|and)\s*$", "", phrase).strip()
    phrase = phrase.strip(" ,.")
    return phrase


_NUMERIC_PHRASE_RE = re.compile(
    r"^\s*\d+(?:\.\d+)?\s*(?:k|thousand|l|lac|lacs|lakh|lakhs|cr|crore|crores|sqft|sq ?ft|square ?feet)?\s*$"
)


def _looks_numeric(phrase: str) -> bool:
    """True if `phrase` is basically just a number (with an optional
    currency/area unit) rather than a place name - e.g. "1 crore" or
    "1200 sqft". Needed because "around" is genuinely ambiguous between
    a location preposition ("around Anna Nagar") and a price/area
    approximation word ("around 1 crore") - a real collision caught
    during evaluation, where "villa around 1 crore" was extracting
    "1 crore" as a POI location name."""
    return bool(_NUMERIC_PHRASE_RE.match(phrase))


def _original_case(phrase: str, original_text: Optional[str]) -> str:
    """Recover the original casing of `phrase` (extracted from lowercased
    text) by searching for it case-insensitively in `original_text` -
    so "vit chennai" comes back as "VIT Chennai", not "Vit Chennai".
    Falls back to title-case if `original_text` isn't given or the
    phrase can't be found there verbatim (e.g. normalization inserted a
    space that wasn't in the original)."""
    if original_text:
        m = re.search(re.escape(phrase), original_text, re.IGNORECASE)
        if m:
            return m.group(0)
    return phrase.title()


def extract_location(text: str, original_text: Optional[str] = None) -> Optional[LocationMention]:
    """`text` should already be normalize_query()'d. `original_text`,
    if given, is used only to recover natural casing for the returned
    `query` (e.g. "VIT Chennai" instead of "Vit Chennai") - matching
    itself always runs on the normalized, lowercased `text`. Returns
    None if no location mention is found at all."""

    # 1. POI-style mention: "near/around/close to/within N km of <place>"
    for prep in _POI_PREPOSITIONS:
        m = re.search(prep, text)
        if m:
            phrase = _capture_phrase(text, m.end())
            if phrase and _looks_numeric(phrase):
                # "around 1 crore" / "around 1200 sqft" - a price/area
                # approximation, not a place. Skip this preposition match
                # entirely rather than returning a bogus location.
                continue
            if phrase:
                return LocationMention(
                    type="poi",
                    query=_original_case(phrase, original_text),
                    raw_text=text[m.start():m.end() + len(phrase) + 1],
                    confidence=0.85,
                )

    # 2. Bare "in <place>" mention.
    m = re.search(r"\bin\s+", text)
    if m:
        phrase = _capture_phrase(text, m.end())
        if phrase:
            known = phrase.strip().split()[-1] in _KNOWN_CITIES or phrase.strip() in _KNOWN_CITIES
            return LocationMention(
                type="area_or_city",
                query=_original_case(phrase, original_text),
                raw_text=text[m.start():m.end() + len(phrase)],
                confidence=0.75 if known else 0.5,
            )

    # 3. A known city name appearing anywhere, with no preposition at all
    # (e.g. "chennai 2 bhk apartment for rent").
    for city in _KNOWN_CITIES:
        m = re.search(rf"\b{re.escape(city)}\b", text)
        if m:
            return LocationMention(
                type="area_or_city",
                query=_original_case(city, original_text),
                raw_text=m.group(0),
                confidence=0.6,
            )

    return None
