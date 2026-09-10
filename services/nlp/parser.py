"""
Phase 2 NLP pipeline orchestrator.

    normalize
        |
    nearby-facility mention detection (Stage 2)  -- mask its spans
        |
    location mention detection                    -- mask its span
        |
    numeric extraction (price, area)
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

parse() itself is a thin wrapper around _parse_configured() with every
stage enabled - the production behavior. _parse_configured() exists so
evaluation/nlp/ablation.py can selectively disable one stage at a time
(normalization, location masking, numeric parsing) to measure its real
contribution, without duplicating this pipeline. See Phase 2.5's report,
docs/PHASE_2_5_NLP_EVALUATION.md, section 11 (ablation study).

STAGE 2 (Phase 4) ADDITION: nearby-facility mentions ("flat near a gym")
are extracted and masked FIRST, before location extraction runs - "near
a gym" would otherwise be misread by extract_location() as a POI
mention (treating "gym" as a place name), and a bare "gym nearby" could
make extract_location() try to capture unrelated TRAILING text as a
place name (its own POI-preposition pattern matches the bare substring
"nearby" too, not just "near"). See
services/nlp/nearby_facility_extractor.py's module docstring for the
full collision analysis. This is a NEW stage, not a rewrite of any
existing one - normalization/location_extractor/entity_extractor/
numeric_parser are all completely unmodified.

NEVER calls services/mappls_service.py or services/osm_location_service.py.
NEVER produces latitude/longitude. This is enforced by never importing
those modules here at all - see test_nlp_parser.py's boundary tests.
"""

from __future__ import annotations

import re

from services.nlp.normalization import normalize_query
from services.nlp.numeric_parser import extract_price, extract_area
from services.nlp.location_extractor import extract_location
from services.nlp.nearby_facility_extractor import (
    extract_nearby_facilities, extract_unsupported_nearby_mentions,
)
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
    return _parse_configured(raw_query)


def _parse_configured(
    raw_query: str,
    *,
    use_normalization: bool = True,
    use_location_masking: bool = True,
    use_numeric: bool = True,
) -> StructuredQuery:
    """The actual pipeline, with each ablatable stage gated behind a
    keyword-only flag that defaults to True (reproducing parse()'s exact
    production behavior). Not part of the public API - external callers
    should use parse(); this exists for evaluation/nlp/ablation.py."""
    if not raw_query or not raw_query.strip():
        return StructuredQuery(raw_query=raw_query or "", intent="unknown",
                                warnings=["empty query"])

    normalized = normalize_query(raw_query) if use_normalization else (raw_query or "").lower()

    # Nearby-facility mentions (Stage 2) are extracted and masked BEFORE
    # location extraction even runs - see this file's module docstring
    # and nearby_facility_extractor.py's for why ("near a gym" / "gym
    # nearby" would otherwise confuse extract_location()'s own
    # POI-preposition matching).
    nearby_facilities = extract_nearby_facilities(normalized)

    # A recognized-but-UNSUPPORTED nearby-facility mention ("pool nearby"
    # - see nearby_facility_extractor.py's docstring, "POOL / SWIMMING
    # POOL") must be masked out too, for the same reason a supported one
    # is: left unmasked, entity_extractor.py's property-amenity lexicon
    # would pick up the bare "pool" and silently misreport it as the
    # property's OWN amenity, when the user actually asked for a nearby
    # one - exactly the amenity/nearby-facility confusion this whole
    # layer exists to prevent. Surfaced explicitly via unsupported_phrases
    # instead (the same mechanism already used for other recognized-but-
    # unmapped domain language below), never silently dropped and never
    # silently reinterpreted.
    unsupported_nearby = extract_unsupported_nearby_mentions(normalized)

    # Both extractors above run independently against the SAME original
    # `normalized` text, so their raw_text spans can overlap or nest (a
    # coordinated-group match like "pool and hospital should be nearby"
    # fully contains the shorter single-noun match "hospital should be
    # nearby" found for a different category). Masking shorter-first
    # would blank part of a longer span before it's masked, so the
    # longer .replace() call then can't find its own text anymore and
    # silently becomes a no-op - a real bug caught while testing this
    # fix ("pool and hospital should be nearby" leaving "pool" unmasked
    # and mis-picked-up as a property amenity). Masking LONGEST-first
    # guarantees every span is still intact when it's its turn; a
    # shorter span fully inside an already-masked region then correctly
    # no-ops instead of corrupting anything.
    all_raw_spans = [r.raw_text for r in nearby_facilities if r.raw_text]
    all_raw_spans.extend(m["raw_text"] for m in unsupported_nearby if m.get("raw_text"))
    text_for_location = normalized
    for raw_text in sorted(set(all_raw_spans), key=len, reverse=True):
        text_for_location = text_for_location.replace(
            raw_text, " " * len(raw_text)
        )

    # Location is extracted next and its matched span is masked out
    # before every other extractor runs, so a place name that happens to
    # contain an ordinary English word ("Guindy National PARK") can
    # never also be picked up as an amenity/entity mention. A real
    # collision caught during evaluation: "villa beside Guindy National
    # Park" was extracting amenity="park" from inside the place name.
    # (use_location_masking=False reproduces exactly this bug on purpose
    # - see the "no location masking" ablation config.)
    location = extract_location(text_for_location, original_text=raw_query)
    working_text = text_for_location
    if use_location_masking and location and location.raw_text:
        working_text = text_for_location.replace(location.raw_text, " " * len(location.raw_text))

    listing_type = extract_listing_type(working_text)
    property_type = extract_property_type(working_text)
    bedrooms = extract_bedrooms(working_text)
    furnishing = extract_furnishing(working_text)
    amenities = extract_amenities(working_text)

    if use_numeric:
        price = extract_price(working_text)
        area = extract_area(working_text)
    else:
        price = None
        area = None

    warnings = []
    if price and price.operator == "eq" and price.raw_text and not re.search(
        r"price|budget|rent|cost|rs", price.raw_text
    ):
        warnings.append("price constraint has no explicit operator keyword; interpreted as a target value, not a bound")

    # "walkable"/"walking distance" is a QUALITATIVE phrase this phase's
    # data model has no numeric radius for - the facility requirement is
    # kept (radius_m=None, same as an unqualified "nearby"), never given
    # a fabricated distance, but the query DID ask for something more
    # specific than "no preference" - surfaced explicitly rather than
    # silently collapsed into an ordinary unqualified requirement. See
    # nearby_facility_extractor.py's docstring.
    for requirement in nearby_facilities:
        if requirement.raw_text and re.search(r"\bwalk(?:able|ing)\s+distance\b", requirement.raw_text):
            warnings.append(
                f"'{requirement.raw_text}' asks for {requirement.category} within walking distance, "
                "which this system cannot resolve to a specific radius; kept as an unqualified "
                "nearby-facility requirement instead of inventing a distance"
            )

    unsupported = _detect_unsupported(working_text)
    unsupported.extend(
        f"{mention['category']} nearby (recognized but not a supported nearby-facility category)"
        for mention in unsupported_nearby
    )

    has_any_signal = any([
        listing_type, property_type, bedrooms, furnishing, price, area,
        amenities, location, nearby_facilities,
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
        nearby_facilities=nearby_facilities,
        unsupported_phrases=unsupported,
        warnings=warnings,
    )

    problems = validate_structured_query(sq)
    if problems:
        sq.warnings.extend(f"validation: {p}" for p in problems)

    return sq
