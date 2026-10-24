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


# A comma (or semicolon) ends a POI/area clause exactly like a stop word
# does - "near VIT Chennai, i need a gym nearby" is two clauses, not one
# place name that happens to contain "i need a gym nearby". This is
# generic punctuation handling, not a per-place special case: it applies
# identically regardless of which words appear on either side of the
# comma - see test_location_extractor.py's CommaBoundaryTests, which
# checks this against several different POI names precisely to prove
# that. A real, pre-existing bug (documented in
# docs/PHASE_4_STAGE_2_NEARBY_FACILITY_SEARCH.md's "known limitation"
# section) before this fix: _capture_phrase only looked for the next
# STOP_WORD, so a comma-separated trailing clause with no stop word of
# its own (e.g. "i need a gym nearby") was captured as part of the place
# name instead of ending it.
_CLAUSE_BOUNDARY_PATTERN = r","


def _detect_trailing_city(remainder: str, phrase: str) -> Optional[str]:
    """Detects a KNOWN city name associated with an already-captured POI
    `phrase` (from `remainder`, the text right after the POI
    preposition) - REUSES this module's existing _KNOWN_CITIES set and
    _capture_phrase() helper; does not add a second city parser or a
    second gazetteer.

    NEVER changes `phrase` itself - this is purely additive detection
    for LocationMention.city, read by
    services/search_orchestration.py's city-qualified Ola retry. The
    POI name (`query`/`raw_text`) keeps its exact existing value and
    existing test coverage (test_location_extractor.py's
    CommaBoundaryTests/ExistingPoiPatternsStillWorkTests) regardless of
    whether a city is also detected here.

    Two shapes, matching the two ways _capture_phrase() can end a
    phrase:
      1. No comma stopped the phrase ("near vit chennai",
         "near phoenix mall in bangalore") - the city, if any, is the
         LAST WORD of `phrase` itself (works whether or not a
         preposition like "in" sits in between - "phoenix mall in
         bangalore"'s last word is "bangalore" either way).
      2. A comma stopped the phrase ("near marina mall, chennai") -
         `phrase` itself never contains the city (the comma already
         excluded it, exactly as test_vit_chennai_stops_at_comma's
         group of tests requires - unchanged here). The city, if any,
         is in the clause immediately following that comma, captured
         with the SAME _capture_phrase() function reused on that
         sub-string.
    """

    # Re-finds the SAME boundary _capture_phrase() already computed
    # internally (its own stop_match/comma_match/end logic, reused
    # verbatim here rather than threaded through as a return value -
    # that function's existing signature/callers stay untouched), to
    # know precisely whether a comma is what ended `phrase`, and if so,
    # exactly where it sits in `remainder` so the clause right after it
    # can be captured.
    stop_match = re.search(_STOP_PATTERN, remainder)
    comma_match = re.search(_CLAUSE_BOUNDARY_PATTERN, remainder)
    end_positions = [m.start() for m in (stop_match, comma_match) if m]
    end = min(end_positions) if end_positions else len(remainder)

    if comma_match and comma_match.start() == end:
        next_clause = _capture_phrase(remainder, end + 1)
        candidate = next_clause.strip().lower()
        if candidate and candidate in _KNOWN_CITIES:
            return next_clause.strip()
        return None

    words = phrase.strip().split()
    if not words:
        return None
    last_word = words[-1].strip(" ,.")
    if last_word.lower() in _KNOWN_CITIES:
        return last_word
    return None


def _split_area_or_city_phrase(phrase: str, remainder_after_phrase: str) -> tuple:
    """For a bare "in <place>" area_or_city phrase, detects whether the
    captured `phrase` is actually "<locality> <city>" (no comma - e.g.
    "velachery chennai") or "<locality>, <city>" (comma - e.g.
    "velachery, chennai") and splits them apart, so the locality and
    city can each be matched against MongoDB's SEPARATE location.city /
    location.locality fields instead of requiring one field to contain
    both words as a single literal substring - the exact bug this
    fixes ("Velachery Chennai" never matched a document storing
    city="Chennai"/locality="Velachery" separately, while "Velachery,
    Chennai" happened to work only because the comma caused "Chennai"
    to be dropped entirely and "Velachery" alone was already specific
    enough).

    REUSES _detect_trailing_city() verbatim (the exact same
    _KNOWN_CITIES set and comma/stop-word boundary logic already used
    for POI mentions) rather than adding a second city parser or a
    second gazetteer - this function only adds the locality-splitting
    behavior area_or_city needs on top, which POI mentions must NOT
    have (a POI's `query` must stay byte-for-byte unchanged for Phase 1
    resolution - see _detect_trailing_city()'s own docstring).

    Returns (locality_query, city):
      - (None, None) when `phrase` is ALREADY nothing but a bare city
        name ("chennai") - deliberately left to extract_location()'s
        existing whole-phrase-is-a-city handling, untouched, so a pure
        city-only query's behavior cannot regress.
      - (None, None) when no known city is attached at all (an
        ordinary single-locality phrase like "anna nagar") - also left
        completely unchanged.
      - (locality_text, detected_city) when a genuine two-part split
        was found - "velachery chennai" -> ("velachery", "chennai");
        "velachery, chennai" -> ("velachery", "chennai"); "whitefield
        bangalore" -> ("whitefield", "bangalore"); "t nagar chennai"
        -> ("t nagar", "chennai") (the locality itself can be more
        than one word - only the trailing city is split off).
    """

    detected_city = _detect_trailing_city(remainder_after_phrase, phrase)

    if not detected_city:
        return None, None

    words = phrase.strip().split()
    detected_city_lower = detected_city.strip().lower()

    if words and words[-1].strip(" ,.").lower() == detected_city_lower:
        # No-comma case: the city is the last word of `phrase` itself -
        # strip it off to get the remaining locality text.
        locality_text = " ".join(words[:-1]).strip(" ,.")
    else:
        # Comma case: _capture_phrase() already stopped `phrase` at the
        # comma, so `phrase` IS already just the locality text, and
        # `detected_city` came from the separate clause after the comma.
        locality_text = phrase.strip()

    if not locality_text:
        # The whole phrase WAS just the city itself ("in chennai") -
        # not a locality+city split.
        return None, None

    return locality_text, detected_city


def _capture_phrase(text: str, start: int) -> str:
    """From `start`, capture tokens until a stop-word, a clause-boundary
    comma, or end of string - whichever comes first."""
    remainder = text[start:]
    stop_match = re.search(_STOP_PATTERN, remainder)
    comma_match = re.search(_CLAUSE_BOUNDARY_PATTERN, remainder)
    end_positions = [m.start() for m in (stop_match, comma_match) if m]
    end = min(end_positions) if end_positions else len(remainder)
    phrase = remainder[:end]
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
                detected_city = _detect_trailing_city(text[m.end():], phrase)
                return LocationMention(
                    type="poi",
                    query=_original_case(phrase, original_text),
                    raw_text=text[m.start():m.end() + len(phrase) + 1],
                    confidence=0.85,
                    city=_original_case(detected_city, original_text) if detected_city else None,
                )

    # 2. Bare "in <place>" mention.
    m = re.search(r"\bin\s+", text)
    if m:
        phrase = _capture_phrase(text, m.end())
        if phrase:
            known = phrase.strip().split()[-1] in _KNOWN_CITIES or phrase.strip() in _KNOWN_CITIES
            locality_text, detected_city = _split_area_or_city_phrase(phrase, text[m.end():])
            query_text = locality_text if locality_text else phrase
            return LocationMention(
                type="area_or_city",
                query=_original_case(query_text, original_text),
                raw_text=text[m.start():m.end() + len(phrase)],
                confidence=0.75 if (known or detected_city) else 0.5,
                city=_original_case(detected_city, original_text) if detected_city else None,
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
