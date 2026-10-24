"""
Lexicon/pattern-based extraction of the domain entities OTHER than
price/area/location: listing_type, property_type, bedrooms, furnishing,
amenities.

Every lexicon here maps to a canonical code that already exists in
services/property_fields.py (or, for "parking", an explicit documented
exception - see schema.py). Nothing here is a POI alias; this is
ordinary real-estate domain vocabulary (the kind any Indian property
portal's search bar has to handle), which the task explicitly
distinguishes from POI identity resolution.
"""

from __future__ import annotations

import re
from typing import Optional

from services.nlp.schema import Slot

# ============================================================
# LISTING TYPE
# ============================================================

_RENT_PATTERNS = [
    r"\bfor rent\b", r"\brental\b", r"\brent\b", r"\bto let\b", r"\blease\b",
]
_SELL_PATTERNS = [
    r"\bfor sale\b", r"\bsale\b", r"\bto buy\b", r"\bbuy\b", r"\bpurchase\b", r"\bsell\b",
]


def extract_listing_type(text: str) -> Optional[Slot]:
    for pattern in _RENT_PATTERNS:
        if re.search(pattern, text):
            return Slot(value="rent", confidence=0.95, source=f"lexicon_match:{pattern}")
    for pattern in _SELL_PATTERNS:
        if re.search(pattern, text):
            return Slot(value="sell", confidence=0.95, source=f"lexicon_match:{pattern}")
    return None


# ============================================================
# PROPERTY TYPE
# ============================================================

_PROPERTY_TYPE_LEXICON = [
    # (regex, canonical value) - order matters, more specific first.
    (r"\bpg\b|\bhostel\b|\bpaying guest\b", "pg_hostel"),
    (r"\bbuilder floor\b", "builder_floor"),
    (r"\bfarm ?house\b", "farm_house"),
    (r"\bindependent house\b|\bindividual house\b", "independent_house"),
    (r"\bvilla\b", "villa"),
    (r"\bplot\b|\bland\b", "plot"),
    (r"\bcommercial\b|\boffice space\b|\bshop\b|\bwarehouse\b", "commercial"),
    (r"\bflats?\b|\bapartments?\b", "apartment"),
    (r"\bhouses?\b", "independent_house"),
]


def extract_property_type(text: str) -> Optional[Slot]:
    for pattern, value in _PROPERTY_TYPE_LEXICON:
        if re.search(pattern, text):
            return Slot(value=value, confidence=0.9, source=f"lexicon_match:{pattern}")
    return None


# ============================================================
# BEDROOMS / BHK
# ============================================================

_WORD_NUMBERS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
}


def extract_bedrooms(text: str) -> Optional[Slot]:
    # "2 bhk", "2.5 bhk" (normalize_query already split "2bhk" -> "2 bhk")
    m = re.search(r"(\d+(?:\.\d+)?)\s*bhk\b", text)
    if m:
        return Slot(value=float(m.group(1)), confidence=0.97, source="explicit_numeric_pattern:bhk")

    # "2 bedroom", "3 bedrooms"
    m = re.search(r"(\d+(?:\.\d+)?)\s*bedrooms?\b", text)
    if m:
        return Slot(value=float(m.group(1)), confidence=0.9, source="explicit_numeric_pattern:bedroom")

    # "two bedroom", "three bhk"
    m = re.search(r"\b(one|two|three|four|five|six)\s*(?:bhk|bedrooms?)\b", text)
    if m:
        return Slot(value=float(_WORD_NUMBERS[m.group(1)]), confidence=0.85, source="word_number")

    return None


# ============================================================
# FURNISHING
# ============================================================

def extract_furnishing(text: str) -> Optional[Slot]:
    # `\s*` (zero-OR-MORE), not `[\s]?` (zero-or-ONE): upstream masking
    # (nearby-facility / location span replacement - see
    # services/nlp/parser.py) replaces a matched span with spaces equal
    # to its own length, which can legitimately leave MULTIPLE spaces
    # between "semi"/"fully"/"un" and "furnished" if something in
    # between got masked. A real bug this fixes: `[\s]?` only tolerates
    # at most one space, so "semi   furnished" (3 spaces) fell through
    # all the way to the bare "furnished" pattern below and was
    # misreported as fully_furnished instead of semi_furnished.
    if re.search(r"\bsemi\s*furnished\b", text):
        return Slot(value="semi_furnished", confidence=0.95, source="lexicon_match:semi_furnished")
    if re.search(r"\bun\s*furnished\b|\bnot\s+furnished\b", text):
        return Slot(value="unfurnished", confidence=0.95, source="lexicon_match:unfurnished")
    if re.search(r"\bfully\s*furnished\b", text):
        return Slot(value="fully_furnished", confidence=0.95, source="lexicon_match:fully_furnished")
    if re.search(r"\bfurnished\b", text):
        return Slot(value="fully_furnished", confidence=0.7, source="lexicon_match:furnished_bare")
    return None


# ============================================================
# AMENITIES (multi-value)
# ============================================================

_AMENITY_LEXICON = [
    (r"\bparking\b", "parking"),
    (r"\blift\b|\belevator\b", "lift"),
    (r"\bpower backup\b|\bgenerator\b|\binverter\b", "power_backup"),
    (r"\b24x7 security\b|\bsecurity\b|\bguard\b", "security"),
    (r"\bcctv\b", "cctv"),
    (r"\bintercom\b", "intercom"),
    (r"\bfire safety\b", "fire_safety"),
    (r"\b24x7 water\b|\bwater supply\b", "water_supply"),
    (r"\bpiped gas\b|\bgas pipeline\b", "gas_pipeline"),
    (r"\bsolar\b", "solar"),
    (r"\bev charging\b|\belectric vehicle charging\b", "ev_charging"),
    (r"\bswimming pool\b|\bpool\b", "swimming_pool"),
    (r"\bgym(?:nasium)?\b", "gym"),
    (r"\bclubhouse\b|\bclub house\b", "clubhouse"),
    (r"\bindoor games\b", "indoor_games"),
    (r"\boutdoor games\b", "outdoor_games"),
    (r"\bchildren'?s? play area\b|\bkids? play area\b", "childrens_play_area"),
    (r"\bjogging track\b", "jogging_track"),
    (r"\bsports facilit", "sports_facilities"),
    (r"\bterrace garden\b", "terrace_garden"),
    # Negative lookbehind is required, not decorative: without it, "terrace
    # garden" would ALSO match this bare pattern (\bgarden\b is satisfied by
    # the "garden" substring inside "terrace garden" too), producing both
    # "terrace_garden" AND "garden" from a single phrase - a real duplicate
    # extraction caught by Phase 2.5's held-out test set (a query combining
    # "terrace garden" with another amenity), since the development set
    # never happened to test that specific amenity in a query at all. See
    # docs/PHASE_2_5_NLP_EVALUATION.md section 12 (error analysis).
    (r"(?<!terrace )\bgarden\b", "garden"),
    (r"\bpark\b", "park"),
    (r"\blawn\b", "lawn"),
    (r"\bmodular kitchen\b", "modular_kitchen"),
    (r"\bpooja room\b", "pooja_room"),
    (r"\bstudy room\b", "study_room"),
    (r"\bstore room\b", "store_room"),
    (r"\butility room\b", "utility_room"),
    (r"\bservant room\b", "servant_room"),
    (r"\bbalcony\b|\bbalconies\b", "balcony"),
    (r"\bprivate terrace\b", "private_terrace"),
    (r"\bhome theatre\b|\bhome theater\b", "home_theatre"),
]


def extract_amenities(text: str) -> list:
    """Returns a list of Slot, one per distinct amenity found (no
    duplicates even if the same amenity phrase appears twice)."""

    found = {}
    for pattern, value in _AMENITY_LEXICON:
        m = re.search(pattern, text)
        if m and value not in found:
            found[value] = Slot(value=value, confidence=0.9, source=f"lexicon_match:{pattern}")
    return list(found.values())
