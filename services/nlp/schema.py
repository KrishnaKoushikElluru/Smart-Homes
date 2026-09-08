"""
Structured query contract for Phase 2 (NLP query understanding).

Every extracted field is wrapped in a Slot so downstream code always
knows THREE things, never just a bare value:

  1. the value (or None if nothing was found)
  2. a confidence score in [0, 1]
  3. a source label explaining HOW it was extracted

This is deliberately kept separate from Phase 1's POI-matching confidence
(services/osm_location_service.py's entity-match score/margin) - the two
numbers measure different things and must never be conflated. See
docs/PHASE_2_NLP_REPORT.md.

Canonical vocabulary is pinned to services/property_fields.py wherever
that registry already defines one (property_type, listing_type, BHK,
furnishing, amenity codes) so a later integration phase can hand this
output straight to the existing schema without a translation table.
Note one real mismatch worth knowing up front: property_fields.py's
listing type value is "sell", not "sale" - Phase 2 follows the real
schema, not the illustrative "sale" spelling from the task's example.

Nothing here calls Mappls, calls OSM, or produces latitude/longitude.
LocationMention.query is free text for Phase 1 to resolve LATER - this
module only identifies that a location was mentioned and what kind it
looks like.
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Any, Optional


# ============================================================
# CANONICAL VOCABULARY (pinned to services/property_fields.py)
# ============================================================

LISTING_TYPES = {"rent", "sell"}

PROPERTY_TYPES = {
    "apartment", "independent_house", "villa", "builder_floor",
    "plot", "farm_house", "pg_hostel", "commercial", "other",
}

FURNISHING_VALUES = {"unfurnished", "semi_furnished", "fully_furnished"}

# AMENITY_CATEGORIES codes from property_fields.py, flattened, PLUS one
# deliberate addition: "parking" as a generic code. property_fields.py
# has no single generic "parking" amenity (it's split into
# covered_parking/open_parking/visitor_parking/ev_charging_parking under
# PARKING_FIELDS) - but "with parking" is exactly how users phrase this,
# and forcing a guess between "covered" vs "open" from bare text would be
# inventing information the query doesn't contain. "parking" is kept as
# an explicit, generic NLP-layer code; mapping it to the right granular
# field is a future integration decision, not this phase's job.
AMENITY_VALUES = {
    "parking",
    # building
    "lift", "power_backup", "security", "cctv", "intercom", "fire_safety",
    "water_supply", "gas_pipeline", "solar", "ev_charging",
    # recreation
    "swimming_pool", "gym", "clubhouse", "indoor_games", "outdoor_games",
    "childrens_play_area", "jogging_track", "sports_facilities",
    # outdoor
    "garden", "park", "lawn", "terrace_garden",
    # property
    "modular_kitchen", "pooja_room", "study_room", "store_room",
    "utility_room", "servant_room", "balcony", "private_terrace",
    "home_theatre",
}

LOCATION_TYPES = {"poi", "area_or_city", "unknown"}
PRICE_OPERATORS = {"lte", "gte", "eq", "approx", "between"}
AREA_OPERATORS = PRICE_OPERATORS


# ============================================================
# SLOT: value + confidence + provenance, for ANY extracted field
# ============================================================

@dataclass
class Slot:
    value: Any
    confidence: float
    source: str  # e.g. "explicit_numeric_pattern", "lexicon_match", "word_number"

    def to_dict(self):
        return {"value": self.value, "confidence": round(self.confidence, 3), "source": self.source}


@dataclass
class RangeConstraint:
    """Used for both price and area - same shape, different units."""
    operator: str          # one of PRICE_OPERATORS / AREA_OPERATORS
    value: Optional[float] = None       # for lte/gte/eq/approx
    value_min: Optional[float] = None   # for "between"
    value_max: Optional[float] = None   # for "between"
    unit: Optional[str] = None          # "inr" for price, "sqft" for area
    raw_text: Optional[str] = None      # the matched span, for traceability

    def to_dict(self):
        return {
            "operator": self.operator,
            "value": self.value,
            "value_min": self.value_min,
            "value_max": self.value_max,
            "unit": self.unit,
            "raw_text": self.raw_text,
        }


@dataclass
class LocationMention:
    type: str            # one of LOCATION_TYPES
    query: str            # the location text itself, e.g. "VIT Chennai" - for Phase 1 to resolve later
    raw_text: str          # the matched span in the original query (may include "near")
    confidence: float

    def to_dict(self):
        return {
            "type": self.type, "query": self.query,
            "raw_text": self.raw_text, "confidence": round(self.confidence, 3),
        }


@dataclass
class StructuredQuery:
    """
    The full Phase 2 output. Every optional field is EXPLICITLY None
    when not found - nothing is silently omitted or invented. Amenities
    is a list of Slots (each amenity mention gets its own confidence,
    since "with parking and a gym" has two independent extractions).
    """
    raw_query: str
    intent: str  # "property_search" | "unknown"
    listing_type: Optional[Slot] = None
    property_type: Optional[Slot] = None
    bedrooms: Optional[Slot] = None
    furnishing: Optional[Slot] = None
    price: Optional[RangeConstraint] = None
    area: Optional[RangeConstraint] = None
    amenities: list = field(default_factory=list)   # list[Slot]
    location: Optional[LocationMention] = None
    unsupported_phrases: list = field(default_factory=list)  # list[str]
    warnings: list = field(default_factory=list)              # list[str]

    def to_dict(self):
        return {
            "raw_query": self.raw_query,
            "intent": self.intent,
            "listing_type": self.listing_type.to_dict() if self.listing_type else None,
            "property_type": self.property_type.to_dict() if self.property_type else None,
            "bedrooms": self.bedrooms.to_dict() if self.bedrooms else None,
            "furnishing": self.furnishing.to_dict() if self.furnishing else None,
            "price": self.price.to_dict() if self.price else None,
            "area": self.area.to_dict() if self.area else None,
            "amenities": [a.to_dict() for a in self.amenities],
            "location": self.location.to_dict() if self.location else None,
            "unsupported_phrases": list(self.unsupported_phrases),
            "warnings": list(self.warnings),
        }


def validate_structured_query(sq: StructuredQuery) -> list:
    """Lightweight self-check - returns a list of validation problems
    (empty = valid). Does not raise; callers decide what to do with a
    non-empty list. Catches the failure modes that would silently
    corrupt a downstream search (e.g. an out-of-vocabulary value that
    slipped past extraction)."""

    problems = []

    if sq.intent not in ("property_search", "unknown"):
        problems.append(f"invalid intent: {sq.intent!r}")

    if sq.listing_type and sq.listing_type.value not in LISTING_TYPES:
        problems.append(f"invalid listing_type: {sq.listing_type.value!r}")

    if sq.property_type and sq.property_type.value not in PROPERTY_TYPES:
        problems.append(f"invalid property_type: {sq.property_type.value!r}")

    if sq.furnishing and sq.furnishing.value not in FURNISHING_VALUES:
        problems.append(f"invalid furnishing: {sq.furnishing.value!r}")

    if sq.location and sq.location.type not in LOCATION_TYPES:
        problems.append(f"invalid location.type: {sq.location.type!r}")

    if sq.price and sq.price.operator not in PRICE_OPERATORS:
        problems.append(f"invalid price.operator: {sq.price.operator!r}")

    if sq.price and sq.price.operator == "between" and (sq.price.value_min is None or sq.price.value_max is None):
        problems.append("price operator=between requires value_min and value_max")

    for a in sq.amenities:
        if a.value not in AMENITY_VALUES:
            problems.append(f"invalid amenity: {a.value!r}")

    for slot_name in ("listing_type", "property_type", "bedrooms", "furnishing"):
        slot = getattr(sq, slot_name)
        if slot and not (0.0 <= slot.confidence <= 1.0):
            problems.append(f"{slot_name} confidence out of range: {slot.confidence}")

    return problems
