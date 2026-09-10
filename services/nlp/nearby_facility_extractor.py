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
phrasings ("would love a gym close by", "gym in walking distance") are
not recognized - the query simply produces no nearby_facilities entry
for that mention, exactly like any other unsupported phrasing elsewhere
in this NLP layer (no silent guessing, no crash).
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

_PREP = r"(?:near(?:by)?|around|close to|next to|beside)"
_ARTICLE = r"(?:a\s+|an\s+|the\s+)?"
_RADIUS_NUM = r"(\d+(?:\.\d+)?)"
_RADIUS_UNIT = r"(km|kilometers?|kilometres?|m|meters?|metres?)"


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
        # "<facility> nearby"  (postfix, no radius)
        re.compile(rf"{_ARTICLE}(?:{noun_pattern})\s+nearby\b"),
    ]


# Patterns 1-3 above capture a radius (two groups: number, unit);
# patterns 4-5 capture none. Indices into the list returned by
# _build_patterns(), used only to know which capture-group shape to
# expect - not a magic constant duplicated anywhere else.
_RADIUS_PATTERN_COUNT = 3


def extract_nearby_facilities(text: str) -> list:
    """`text` should already be normalize_query()'d (same convention as
    location_extractor.extract_location()). Returns a list of
    NearbyFacilityRequirement - zero, one, or many (a query may
    legitimately mention several different facility categories). At
    most one requirement per CATEGORY is produced (the first, most
    specific pattern match for that category wins - see
    _build_patterns()'s docstring); a category mentioned twice with two
    different radii is a known, documented simplification, not a
    crash or a silent wrong answer."""

    found = []

    for noun_pattern, category in _FACILITY_NOUNS:

        patterns = _build_patterns(noun_pattern)

        for index, pattern in enumerate(patterns):

            match = pattern.search(text)

            if not match:
                continue

            radius_m: Optional[float] = None

            if index < _RADIUS_PATTERN_COUNT:
                radius_m = _radius_to_meters(match.group(1), match.group(2))

            found.append(NearbyFacilityRequirement(
                category=category,
                radius_m=radius_m,
                raw_text=match.group(0),
                confidence=0.85 if radius_m is not None else 0.8,
            ))

            break  # most-specific pattern already matched for this category

    return found
