"""
Stage 2 - nearby-FACILITY mention extraction (as opposed to Phase 2's
existing extract_amenities() in entity_extractor.py, which extracts
PROPERTY amenities).

The distinction this whole module exists to preserve:

  PROPERTY AMENITY   "flat with a gym"       -> the property itself has
                                                 a gym (entity_extractor.py,
                                                 unchanged)
  NEARBY FACILITY    "flat near a gym"       -> a gym exists somewhere
                                                 near the property
                                                 (THIS module)

Both "gym" and "park" are also property-amenity words (see
entity_extractor.py's _AMENITY_LEXICON) - a bare "gym" or "park" with no
proximity wrapper around it is deliberately left alone here and is
still picked up as a property amenity by the existing, unmodified
entity_extractor.py. This module only claims a span when it is wrapped
in an explicit proximity construction (a preposition like "near"/
"around"/"close to", or the word "nearby", optionally with a distance
qualifier like "within 1 km").

Like location_extractor.py, this module NEVER calls Mappls/OSM/MongoDB
and never produces coordinates - it only identifies that a facility
CATEGORY was mentioned with a proximity relationship, as free-standing
text-processing. Resolving "how far is a real gym from this specific
property" is entirely services/search_orchestration.py's job (Stage 2,
using services/nearby_facility_service.py's ALREADY-STORED data - see
that module's own docstring), reusing the same architecture the rest of
this NLP layer already respects.

NEARBY_FACILITY_CATEGORIES below is intentionally a plain, self-contained
dict - NOT imported from services/nearby_facility_service.py - to
preserve services/nlp/'s existing zero-dependency boundary on any
Mappls/OSM/Phase 4 service (enforced by test_nlp_parser.py's
NoCoordinatesOrPhase1CallsTests, which statically checks every
services/nlp/*.py file never imports mappls_service or
osm_location_service - importing nearby_facility_service, which itself
imports mappls_service, would transitively violate that same boundary
in spirit even where the exact substring check might not catch it).
Values are hand-kept in sync with FACILITY_CATEGORIES' keys there - see
this module's own test coverage for the cross-check.

DOCUMENTED LIMITATION (deliberately not addressed further per the
"smallest deterministic extension necessary" instruction): this is a
fixed set of proximity/phrasing patterns, not a general grammar. Novel
phrasings not covered below are not recognized - the query simply
produces no nearby_facilities entry for that mention, exactly like any
other unsupported phrasing elsewhere in this NLP layer (no silent
guessing, no crash).

CORRECTNESS-PASS ADDITIONS (post-Phase-4-Stage-2 bug fixes):

  - "<facility> should be nearby" (a copula between the facility and
    "nearby") is now recognized, not just the bare "<facility> nearby".

  - A COORDINATED LIST of facilities sharing one trailing "nearby" /
    "should be nearby" - "gym and pool should be nearby", "gym,
    hospital and bank nearby" - is now recognized via
    _extract_coordinated_group(), which finds the whole list span and
    then checks each known facility noun within it. This is generic
    coordination handling (comma/"and" separated), not a hardcoded
    pairing of any two specific facility words.

  - "<facility> (should be) (in) walk(ing|able) distance" is recognized
    as a NEARBY FACILITY requirement, but - per this project's explicit
    "never fabricate a distance" rule - "walkable"/"walking" is a
    QUALITATIVE phrase with no defined numeric radius in this phase's
    data model, so it produces radius_m=None (exactly like an
    unqualified "nearby") rather than inventing a number. parser.py
    detects the "walk" wording in the requirement's raw_text and
    surfaces it as an explicit warning (never silently dropped, never
    silently given a made-up radius).

  - "pool" / "swimming pool", wrapped in the SAME proximity language
    ("near a pool", "pool nearby", "pool should be nearby"), is
    recognized as a facility MENTION but is explicitly UNSUPPORTED: the
    real Phase 4 taxonomy (services/nearby_facility_service.FACILITY_CATEGORIES,
    duplicated here as NEARBY_FACILITY_CATEGORIES) has no swimming_pool
    category - Mappls-category support for it was never verified live,
    so one is not invented here. See extract_unsupported_nearby_mentions()
    below: these are reported through StructuredQuery.unsupported_phrases
    (the same existing mechanism parser.py already uses for other
    recognized-but-unmapped domain language, e.g. "gated community"),
    NOT silently left for entity_extractor.py's property-amenity lexicon
    to reinterpret as "the property itself has a pool" - that would be
    exactly the amenity/nearby-facility confusion this whole module
    exists to prevent. "pool"/"swimming pool" is a generic category
    keyword, not a business-name alias.
"""

from __future__ import annotations

import re
from typing import Optional

from services.nlp.schema import NearbyFacilityRequirement

# Kept in sync with services/nearby_facility_service.FACILITY_CATEGORIES'
# keys - see this module's module docstring for why it is a separate,
# non-imported copy rather than a shared import.
NEARBY_FACILITY_CATEGORIES = {
    "gym", "hospital", "school", "college", "supermarket", "pharmacy",
    "restaurant", "bank", "atm", "metro_station", "railway_station",
    "bus_stop", "shopping_mall", "park", "police_station", "fire_station",
    "petrol_station",
}

# Natural-language noun phrase(s) -> canonical category. Order within
# this list does not matter (each category is tried independently, not
# as one combined alternation), but every value here must be a key in
# NEARBY_FACILITY_CATEGORIES above (checked by this module's own tests).
_FACILITY_NOUNS = [
    (r"gyms?|gymnasiums?", "gym"),
    (r"hospitals?", "hospital"),
    (r"schools?", "school"),
    (r"colleges?", "college"),
    (r"supermarkets?", "supermarket"),
    (r"pharmac(?:y|ies)", "pharmacy"),
    (r"restaurants?", "restaurant"),
    (r"banks?", "bank"),
    (r"atms?", "atm"),
    (r"metro\s+stations?", "metro_station"),
    (r"railway\s+stations?|train\s+stations?", "railway_station"),
    (r"bus\s+stops?|bus\s+stands?", "bus_stop"),
    (r"shopping\s+malls?|malls?", "shopping_mall"),
    (r"parks?", "park"),
    (r"police\s+stations?", "police_station"),
    (r"fire\s+stations?", "fire_station"),
    (r"petrol\s+(?:pumps?|stations?)|gas\s+stations?", "petrol_station"),
]

# A generic, non-business-specific keyword. See this module's docstring
# ("POOL / SWIMMING POOL") for why this is deliberately kept OUT of
# NEARBY_FACILITY_CATEGORIES / _FACILITY_NOUNS - it is a recognized-but-
# UNSUPPORTED nearby-facility mention, never turned into a
# NearbyFacilityRequirement.
_UNSUPPORTED_FACILITY_NOUNS = [
    (r"swimming\s+pools?|pools?", "swimming_pool"),
]

_PREP = r"(?:near(?:by)?|around|close to|next to|beside)"
_ARTICLE = r"(?:a\s+|an\s+|the\s+)?"
_RADIUS_NUM = r"(\d+(?:\.\d+)?)"
_RADIUS_UNIT = r"(km|kilometers?|kilometres?|m|meters?|metres?)"

# "<facility> should be nearby" / "<facility> nearby" - a copula ("should
# be") between the facility and "nearby" is optional, not required.
_NEARBY_POSTFIX = r"nearby"
_NEARBY_COPULA = r"(?:should\s+be\s+)?"

# "walkable"/"walking" distance is a QUALITATIVE phrase with no defined
# numeric radius in this phase's data model - matched so the facility
# requirement itself is never dropped, but deliberately never given a
# radius_m value. See this module's docstring.
_WALKABLE_DISTANCE = r"(?:should\s+be\s+)?(?:in\s+)?walk(?:able|ing)\s+distance"


def _radius_to_meters(number_str: str, unit_str: str) -> float:
    value = float(number_str)
    return value * 1000.0 if unit_str.lower().startswith("k") else value


def _build_patterns(noun_pattern: str):
    """Ordered most-specific-first: a radius-qualified match must never
    lose to a shorter, radius-less match of the same mention (e.g.
    "near a hospital within 1 km" must capture the "within 1 km" part,
    not stop at "near a hospital" and leave the radius unclaimed for a
    LATER, unrelated pattern to possibly mis-parse)."""

    return [
        # "near/around/... a <facility> within N km"  (this phase's own worked example)
        re.compile(rf"{_PREP}\s+{_ARTICLE}(?:{noun_pattern})\s+within\s+{_RADIUS_NUM}\s*{_RADIUS_UNIT}\b"),
        # "within N km of a <facility>"
        re.compile(rf"within\s+{_RADIUS_NUM}\s*{_RADIUS_UNIT}\s+of\s+{_ARTICLE}(?:{noun_pattern})\b"),
        # "<facility> within N km"  (no leading preposition)
        re.compile(rf"{_ARTICLE}(?:{noun_pattern})\s+within\s+{_RADIUS_NUM}\s*{_RADIUS_UNIT}\b"),
        # "near/around/... a <facility>"  (no radius)
        re.compile(rf"{_PREP}\s+{_ARTICLE}(?:{noun_pattern})\b"),
        # "<facility> (should be) walk(ing|able) distance"  (qualitative,
        # deliberately no radius - see _WALKABLE_DISTANCE above)
        re.compile(rf"{_ARTICLE}(?:{noun_pattern})\s+{_WALKABLE_DISTANCE}\b"),
        # "<facility> (should be) nearby"  (postfix, no radius)
        re.compile(rf"{_ARTICLE}(?:{noun_pattern})\s+{_NEARBY_COPULA}{_NEARBY_POSTFIX}\b"),
    ]


# Patterns 1-3 above capture a radius (two groups: number, unit);
# patterns 4-6 capture none. Indices into the list returned by
# _build_patterns(), used only to know which capture-group shape to
# expect - not a magic constant duplicated anywhere else.
_RADIUS_PATTERN_COUNT = 3


def _match_single_noun(text: str, noun_pattern: str):
    """Runs one noun's full pattern set against `text`, most-specific
    first. Returns (match, radius_m) or (None, None)."""

    for index, pattern in enumerate(_build_patterns(noun_pattern)):

        match = pattern.search(text)

        if not match:
            continue

        radius_m: Optional[float] = None

        if index < _RADIUS_PATTERN_COUNT:
            radius_m = _radius_to_meters(match.group(1), match.group(2))

        return match, radius_m

    return None, None


# Coordination: "<facility>[, <facility>]* (and <facility>)? (should be)?
# nearby" - e.g. "gym and pool should be nearby", "gym, hospital and bank
# nearby". Generic list-of-known-nouns handling, not a hardcoded pairing
# of any two specific words - see this module's docstring.
_COORD_SEP = r"(?:\s*,\s*|\s+and\s+)"


def _coordinated_group_pattern(all_noun_alternation: str):
    return re.compile(
        rf"(?:(?:{all_noun_alternation}){_COORD_SEP})+(?:{all_noun_alternation})"
        rf"\s+{_NEARBY_COPULA}{_NEARBY_POSTFIX}\b"
    )


def _extract_coordinated_group(text: str, already_found_categories: set):
    """Finds a coordinated list of facility nouns that all share one
    trailing "nearby"/"should be nearby" (a construction none of the
    single-noun patterns above can catch, since a noun in the MIDDLE of
    the list - "gym" in "gym and pool should be nearby" - is not
    immediately followed by "nearby" at all). Returns
    (new_requirements, new_unsupported_mentions, matched_raw_text) -
    matched_raw_text is None when no coordinated group was found.
    Categories already present in `already_found_categories` are skipped
    (already claimed by a more specific single-noun match)."""

    all_entries = _FACILITY_NOUNS + _UNSUPPORTED_FACILITY_NOUNS
    all_noun_alternation = "|".join(f"(?:{p})" for p, _ in all_entries)

    match = _coordinated_group_pattern(all_noun_alternation).search(text)

    if not match:
        return [], [], None

    group_text = match.group(0)

    new_requirements = []
    new_unsupported = []

    # Every requirement/mention found in this coordinated group is given
    # the FULL group span as its raw_text (not just its own bare noun
    # word) - deliberately, so masking it out of text_for_location (see
    # parser.py) removes the whole coordinated clause in one shot,
    # regardless of which category happens to be masked first. A
    # duplicate .replace() of the same already-masked span is a safe
    # no-op, not an error.
    for noun_pattern, category in _FACILITY_NOUNS:
        if category in already_found_categories:
            continue
        if re.search(rf"\b(?:{noun_pattern})\b", group_text):
            new_requirements.append(NearbyFacilityRequirement(
                category=category, radius_m=None,
                raw_text=group_text, confidence=0.75,
            ))

    for noun_pattern, canonical in _UNSUPPORTED_FACILITY_NOUNS:
        if re.search(rf"\b(?:{noun_pattern})\b", group_text):
            new_unsupported.append({"category": canonical, "raw_text": group_text})

    return new_requirements, new_unsupported, group_text


def extract_nearby_facilities(text: str) -> list:
    """`text` should already be normalize_query()'d (same convention as
    location_extractor.extract_location()). Returns a list of
    NearbyFacilityRequirement - zero, one, or many (a query may
    legitimately mention several different facility categories). At
    most one requirement per CATEGORY is produced (the first, most
    specific pattern match for that category wins - see
    _build_patterns()'s docstring); a category mentioned twice with two
    different radii is a known, documented simplification, not a
    crash or a silent wrong answer.

    An explicitly UNSUPPORTED facility mention (currently just
    "pool"/"swimming pool" - see this module's docstring) is never
    included here; use extract_unsupported_nearby_mentions() for those."""

    found = []

    for noun_pattern, category in _FACILITY_NOUNS:

        match, radius_m = _match_single_noun(text, noun_pattern)

        if not match:
            continue

        found.append(NearbyFacilityRequirement(
            category=category,
            radius_m=radius_m,
            raw_text=match.group(0),
            confidence=0.85 if radius_m is not None else 0.8,
        ))

    already_found = {r.category for r in found}
    new_requirements, _unsupported, _raw = _extract_coordinated_group(text, already_found)
    found.extend(new_requirements)

    return found


def extract_unsupported_nearby_mentions(text: str) -> list:
    """Companion to extract_nearby_facilities(): recognized proximity-
    wrapped mentions of a facility category this phase's taxonomy does
    NOT support (currently just "pool"/"swimming pool"). Returns a list
    of {"category": ..., "raw_text": ...} dicts - never a
    NearbyFacilityRequirement (that would fail
    schema.validate_structured_query()'s category check, since
    "swimming_pool" is deliberately not in NEARBY_FACILITY_CATEGORIES).
    parser.py surfaces these through StructuredQuery.unsupported_phrases
    and masks their raw_text out of the working text, exactly like a
    supported nearby-facility mention - so an unsupported nearby mention
    is never left for entity_extractor.py's property-amenity lexicon to
    silently reinterpret as a property amenity."""

    found = []

    for noun_pattern, canonical in _UNSUPPORTED_FACILITY_NOUNS:

        match, _radius_m = _match_single_noun(text, noun_pattern)

        if match:
            found.append({"category": canonical, "raw_text": match.group(0)})

    already_found_categories = set()  # unsupported nouns never compete with supported ones for this pass
    _requirements, new_unsupported, _raw = _extract_coordinated_group(text, already_found_categories)

    found_categories = {f["category"] for f in found}
    for entry in new_unsupported:
        if entry["category"] not in found_categories:
            found.append(entry)

    return found
