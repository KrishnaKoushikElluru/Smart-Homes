"""
Phase 2 NLP pipeline orchestrator.

    normalize
        |
    numeric extraction (price, area)
        |
    location mention detection
        |
    domain entity extraction (listing_type, property_type, bedrooms,
                               furnishing, amenities)
        |
    intent classification
        |
    StructuredQuery assembly + validation

This is the ONLY function most callers should use: parse(query) ->
StructuredQuery. Every sub-stage is independently importable (see
services/nlp/*.py) specifically so ablations can bypass a stage - e.g.
an ablation that skips location_extractor entirely, or one that runs
numeric_parser directly on the RAW query instead of the normalized one
- without touching this file. See docs/PHASE_2_NLP_REPORT.md section 12.

NEVER calls services/mappls_service.py or services/osm_location_service.py.
NEVER produces latitude/longitude. This is enforced by never importing
those modules here at all - see test_nlp_parser.py's boundary tests.
"""

from __future__ import annotations

import re

from services.nlp.normalization import normalize_query
from services.nlp.numeric_parser import extract_price, extract_area
from services.nlp.location_extractor import extract_location
from services.nlp.entity_extractor import (
    extract_listing_type, extract_property_type, extract_bedrooms,
    extract_furnishing, extract_amenities,
)
from services.nlp.schema import StructuredQuery, validate_structured_query

# Real-estate-adjacent phrases that are recognizably domain language but
# have no mapped field in this phase's ontology - surfaced explicitly
# rather than silently dropped, per the task's "explicit about
# unsupported constraints" requirement. Not exhaustive by design; this
# is a visibility mechanism; extending the extractors to actually
# understand a phrase is preferred over adding it here forever.
_KNOWN_UNSUPPORTED_PATTERNS = [
    r"\bgated community\b", r"\bvastu\b", r"\bcorner plot\b",
    r"\bsea view\b", r"\bcity view\b", r"\block ?in\b", r"\bnotice period\b",
    r"\bpet friendly\b", r"\bbachelor(?:s)? allowed\b", r"\bfamily only\b",
    r"\bnegotiable\b", r"\bbrokerage\b", r"\bimmediate(?:ly)? available\b",
    r"\bready to move\b", r"\bunder construction\b", r"\brera\b",
]


def _detect_unsupported(text: str) -> list:
    found = []
    for pattern in _KNOWN_UNSUPPORTED_PATTERNS:
        if re.search(pattern, text):
            found.append(re.sub(r"[\\?]", "", pattern).strip("\\b"))
    return found


def parse(raw_query: str) -> StructuredQuery:
    if not raw_query or not raw_query.strip():
        return StructuredQuery(raw_query=raw_query or "", intent="unknown",
                                warnings=["empty query"])

    normalized = normalize_query(raw_query)

    # Location is extracted FIRST and its matched span is masked out
    # before every other extractor runs, so a place name that happens to
    # contain an ordinary English word ("Guindy National PARK") can
    # never also be picked up as an amenity/entity mention. A real
    # collision caught during evaluation: "villa beside Guindy National
    # Park" was extracting amenity="park" from inside the place name.
    location = extract_location(normalized, original_text=raw_query)
    working_text = normalized
    if location and location.raw_text:
        working_text = normalized.replace(location.raw_text, " " * len(location.raw_text))

    listing_type = extract_listing_type(working_text)
    property_type = extract_property_type(working_text)
    bedrooms = extract_bedrooms(working_text)
    furnishing = extract_furnishing(working_text)
    amenities = extract_amenities(working_text)
    price = extract_price(working_text)
    area = extract_area(working_text)

    warnings = []
    if price and price.operator == "eq" and price.raw_text and not re.search(
        r"price|budget|rent|cost|rs", price.raw_text
    ):
        warnings.append("price constraint has no explicit operator keyword; interpreted as a target value, not a bound")

    unsupported = _detect_unsupported(working_text)

    has_any_signal = any([
        listing_type, property_type, bedrooms, furnishing, price, area,
        amenities, location,
    ])
    # A query can be unmistakably real-estate-related even when nothing
    # maps to a known slot ("gated community with vastu compliance") -
    # recognizing domain-adjacent-but-unmapped language is itself a
    # signal that this IS a property search, just one this ontology
    # can't fully structure yet. Only a query with neither a mapped
    # slot NOR any recognized domain language at all is "unknown".
    intent = "property_search" if (has_any_signal or unsupported) else "unknown"

    if not has_any_signal:
        warnings.append("no recognizable real-estate search terms found")

    sq = StructuredQuery(
        raw_query=raw_query,
        intent=intent,
        listing_type=listing_type,
        property_type=property_type,
        bedrooms=bedrooms,
        furnishing=furnishing,
        price=price,
        area=area,
        amenities=amenities,
        location=location,
        unsupported_phrases=unsupported,
        warnings=warnings,
    )

    problems = validate_structured_query(sq)
    if problems:
        sq.warnings.extend(f"validation: {p}" for p in problems)

    return sq
