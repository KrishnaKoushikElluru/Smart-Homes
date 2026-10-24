"""
Property Comparison + category-wise rating engine.

PURE / STATELESS: every function here takes plain data in and returns
plain data out. Nothing in this module touches MongoDB, the Square
Yards MCP, or any other network/database call - that is the caller's
job (routes/comparison_routes.py), which fetches a real SmartHomes
property document via the EXISTING PropertyService, or a real Square
Yards listing via the EXISTING
services.external_property_sources.square_yards_service.get_listing_details(),
and passes the raw result in here. Keeping I/O entirely out of this
module is what makes the rating math deterministic, reproducible, and
trivial to unit test without mocking a database or an MCP server.

NO LLM is used anywhere in this module. Every score below is a plain,
documented arithmetic formula over fields that genuinely exist in the
current schema (see services/property_fields.py for SmartHomes' field
registry and services/external_property_sources/square_yards_service.py's
normalize_listing_detail()/normalize_search_card() for Square Yards'
actual shape) - nothing here invents a field a source doesn't provide.

This module is additive only - it does not modify, replace, or import
anything FROM routes/search_routes.py's _serialize_property()/
_serialize_external_result(), which continue to serve search results
exactly as before.
"""

from __future__ import annotations

from datetime import date, datetime

from services.property_fields import FIELD_GROUPS
from services.nearby_facility_service import STATUS_COMPLETED, STATUS_PARTIAL


# ============================================================
# COMPARISON ROW - the unified, cross-source representation
# ============================================================

COMPARISON_ROW_FIELDS = [
    "provider", "id", "title", "property_type", "listing_type",
    "price", "price_on_request", "bhk", "area_sqft", "city", "locality",
    "furnishing", "amenities_flat", "bathrooms", "balconies",
    "floor_number", "facing", "status", "available_from",
    "possession_status", "nearby_facilities", "coordinates",
    "image_url", "detail_url",
]


def _row(**values):
    """Every ComparisonRow field is always present, defaulting to
    None - a field a source genuinely cannot supply is explicit None,
    never simply missing from the dict (so callers never need a
    .get()-with-fallback dance)."""

    row = {key: None for key in COMPARISON_ROW_FIELDS}
    row.update(values)
    return row


def smarthomes_property_to_row(property_id, document):
    """Builds a ComparisonRow from a REAL SmartHomes property document -
    the exact shape routes/property_routes.py's submit_listing() builds
    (see its "BUILD MONGODB DOCUMENT" section). Never mutates `document`."""

    document = document or {}
    listing = document.get("listing") or {}
    prop = document.get("property") or {}
    location = document.get("location") or {}
    rental = document.get("rental") or {}
    sale = document.get("sale") or {}
    media = document.get("media") or {}
    images = media.get("images") or []

    coords_block = (location.get("coordinates") or {})
    coordinates = coords_block.get("coordinates")  # [lon, lat] GeoJSON, or None

    # nearby_facilities is only trustworthy once enrichment has actually
    # finished (STATUS_COMPLETED/STATUS_PARTIAL) - a "pending"/"failed"/
    # "skipped" run, or no enrichment attempted at all, must read as
    # "not available" (None), never as "zero facilities found" (which
    # a bare [] would wrongly imply). Mirrors
    # services/nearby_facility_service.py's own
    # build_nearby_facilities_display() status handling exactly.
    nearby_meta = document.get("nearby_facilities_metadata") or {}
    nearby_status = nearby_meta.get("status")
    nearby_facilities = (
        document.get("nearby_facilities")
        if nearby_status in (STATUS_COMPLETED, STATUS_PARTIAL)
        else None
    )

    return _row(
        provider="smarthomes",
        id=str(property_id) if property_id is not None else None,
        title=listing.get("title"),
        property_type=prop.get("type"),
        listing_type=listing.get("type"),
        price=listing.get("price"),
        price_on_request=False,  # SmartHomes' own listings always have a real price (required field)
        bhk=prop.get("bhk"),
        area_sqft=prop.get("area_sqft"),
        city=location.get("city"),
        locality=location.get("locality"),
        furnishing=prop.get("furnishing"),
        amenities_flat=document.get("features"),
        bathrooms=prop.get("bathrooms"),
        balconies=prop.get("balconies"),
        floor_number=prop.get("floor_number"),
        facing=prop.get("facing"),
        status=listing.get("status"),
        available_from=rental.get("available_from"),
        possession_status=sale.get("possession_status"),
        nearby_facilities=nearby_facilities,
        coordinates=coordinates,
        image_url=(f"/static/images/properties/{images[0]}" if images else None),
        detail_url=(f"/property/{property_id}" if property_id is not None else None),
    )


def square_yards_listing_to_row(normalized):
    """Builds a ComparisonRow from the EXISTING Square Yards normalized
    listing dict (services/external_property_sources/
    square_yards_service.py's normalize_listing_detail()/
    normalize_search_card() shape). Never calls the MCP itself, never
    invents a field that normalizer doesn't actually provide - every
    field below is a direct passthrough. Never mutates `normalized`."""

    normalized = normalized or {}
    images = normalized.get("images") or []

    return _row(
        provider="squareyards",
        id=normalized.get("external_id"),
        title=normalized.get("title"),
        property_type=normalized.get("property_type"),
        listing_type=normalized.get("listing_type"),
        price=normalized.get("price"),
        price_on_request=bool(normalized.get("price_on_request", False)),
        bhk=normalized.get("bhk"),
        area_sqft=normalized.get("area_sqft"),
        city=normalized.get("city"),
        locality=normalized.get("locality"),
        furnishing=normalized.get("furnishing"),
        amenities_flat=normalized.get("amenities"),
        # bathrooms/balconies/floor_number/facing/status/available_from/
        # possession_status/nearby_facilities/coordinates: confirmed via
        # direct inspection that normalize_listing_detail()'s return
        # shape has none of these - left None, never guessed.
        image_url=(images[0] if images else None),
        detail_url=normalized.get("source_url"),
    )


# ============================================================
# RATING CATEGORIES
# ============================================================

CATEGORY_LABELS = {
    "price_value": "Price / Value",
    "location": "Location",
    "facilities": "Facilities / Amenities",
    "availability": "Availability",
    "connectivity": "Connectivity / Nearby Facilities",
    "property_features": "Property Features",
}

# Configurable constants - proposed starting weights, reviewed in the
# design phase. Must always sum to 1.0 (enforced by a test).
BASE_WEIGHTS = {
    "price_value": 0.30,
    "location": 0.20,
    "facilities": 0.20,
    "availability": 0.10,
    "connectivity": 0.10,
    "property_features": 0.10,
}


def _unavailable(reason):
    return {"status": "unavailable", "score": None, "reason": reason}


def _valid(score, reason):
    # Deliberately NOT rounded here - every category score feeds the
    # overall-rating weighted average below, and rounding only happens
    # once, at the very end, in _finalize_for_display() (Phase 2's
    # "round only the final displayed values, not intermediate
    # calculations" requirement).
    return {"status": "valid", "score": float(score), "reason": reason}


# ------------------------------------------------------------
# PRICE / VALUE
# ------------------------------------------------------------

def _effective_cost(row):
    """Returns (cost, basis) or (None, None) if no meaningful cost can
    be computed for this row. Prefers price-per-BHK, then
    price-per-sqft, then falls back to the raw price itself (still
    real, usable data - better than declaring the whole category
    unavailable just because neither BHK nor area happened to be
    usable for this one property)."""

    price = row["price"]
    if row["price_on_request"] or price is None:
        return None, None

    bhk = row["bhk"]
    if bhk:
        try:
            bhk_f = float(bhk)
            if bhk_f > 0:
                return price / bhk_f, "price_per_bhk"
        except (TypeError, ValueError):
            pass

    area = row["area_sqft"]
    if area:
        try:
            area_f = float(area)
            if area_f > 0:
                return price / area_f, "price_per_sqft"
        except (TypeError, ValueError):
            pass

    return price, "raw_price"


_BASIS_LABELS = {
    "price_per_bhk": "price per BHK",
    "price_per_sqft": "price per sq.ft",
    "raw_price": "price",
}


def score_price_value(entry, all_entries):
    row = entry["row"]
    this_cost, basis = _effective_cost(row)

    if this_cost is None:
        reason = "Price on request" if row["price_on_request"] else "Price not available"
        return _unavailable(reason)

    costs = []
    for other in all_entries:
        c, _ = _effective_cost(other["row"])
        if c is not None:
            costs.append(c)

    min_cost, max_cost = min(costs), max(costs)

    if max_cost == min_cost:
        score = 100.0
    else:
        # Lower effective cost -> higher score.
        score = 100.0 * (max_cost - this_cost) / (max_cost - min_cost)

    basis_label = _BASIS_LABELS[basis]
    plural = "y" if len(costs) == 1 else "ies"
    reason = (
        f"Based on {basis_label}, compared against {len(costs)} "
        f"propert{plural} with usable price data in this comparison."
    )
    return _valid(score, reason)


# ------------------------------------------------------------
# LOCATION
# ------------------------------------------------------------

def score_location(entry, all_entries):
    row = entry["row"]

    if not row["city"]:
        return _unavailable("Location data not available")

    # 1 point for city (guaranteed present here), +1 for locality -
    # these are the only two location text fields the unified
    # ComparisonRow carries for EITHER source (Square Yards has no
    # sub_locality/landmark), so both sources are scored on the same
    # 0-2 basis for this component.
    completeness = 1 + (1 if row["locality"] else 0)
    completeness_score = 100.0 * completeness / 2.0

    facilities = row["nearby_facilities"]

    if row["provider"] == "smarthomes" and facilities is not None:
        this_count = len(facilities)
        counts = [
            len(other["row"]["nearby_facilities"])
            for other in all_entries
            if other["row"]["provider"] == "smarthomes"
            and other["row"]["nearby_facilities"] is not None
        ]
        max_count = max(counts) if counts else 0
        facility_score = (100.0 * this_count / max_count) if max_count > 0 else 0.0

        score = 0.5 * completeness_score + 0.5 * facility_score
        reason = (
            f"Address completeness plus {this_count} nearby facilities "
            "(SmartHomes location signal)."
        )
    elif row["provider"] == "squareyards":
        score = completeness_score
        reason = (
            "Based on city/locality only - Square Yards does not provide "
            "coordinates or nearby-facility data."
        )
    else:
        score = completeness_score
        reason = (
            "Based on city/locality only - nearby-facility enrichment is "
            "not yet available for this property."
        )

    return _valid(score, reason)


# ------------------------------------------------------------
# FACILITIES / AMENITIES
# ------------------------------------------------------------

def score_facilities(entry, all_entries):
    row = entry["row"]
    amenities = row["amenities_flat"]

    if amenities is None:
        return _unavailable("Amenity data not available")

    count = len(amenities)
    counts = [
        len(other["row"]["amenities_flat"])
        for other in all_entries
        if other["row"]["amenities_flat"] is not None
    ]

    if not counts:
        return _unavailable("No amenity data available in this comparison")

    max_count = max(counts)

    if max_count == 0:
        # Every property in the set explicitly has zero amenities -
        # a real, valid data point, not "unavailable".
        return _valid(0.0, "No amenities listed for any compared property.")

    score = 100.0 * count / max_count
    if count == max_count:
        reason = f"{count} amenities - highest among compared properties."
    else:
        reason = f"{count} amenities, vs. {max_count} (max in this comparison)."

    return _valid(score, reason)


# ------------------------------------------------------------
# AVAILABILITY (SmartHomes only)
# ------------------------------------------------------------

def _parse_date_like(value):
    """available_from/possession_date may be stored as a date,
    datetime, or ISO string depending on how the form saved it -
    normalizes to a plain date, or None if it can't be parsed. Never
    raises."""

    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value).date()
        except ValueError:
            return None
    return None


def score_availability(entry, all_entries):
    row = entry["row"]

    if row["provider"] != "smarthomes":
        return _unavailable("Not available for this source")

    status = row["status"]
    if not status:
        return _unavailable("Availability data not available")

    if status != "active":
        return _valid(10.0, f"Listing status is '{status}' (not currently active).")

    available_from = _parse_date_like(row["available_from"])
    if available_from is not None:
        if available_from <= date.today():
            return _valid(100.0, "Active and available from today or earlier.")
        return _valid(
            60.0,
            f"Active, but available only from a future date ({available_from.isoformat()}).",
        )

    possession_status = row["possession_status"]
    if possession_status == "ready_to_move":
        return _valid(100.0, "Active and ready to move in.")
    if possession_status == "under_construction":
        return _valid(60.0, "Active, but still under construction.")
    if possession_status:
        return _valid(90.0, f"Active; possession status: {possession_status}.")

    return _valid(90.0, "Listing is active; no specific availability date provided.")


# ------------------------------------------------------------
# CONNECTIVITY / NEARBY FACILITIES (SmartHomes only)
# ------------------------------------------------------------

def score_connectivity(entry, all_entries):
    row = entry["row"]

    if row["provider"] != "smarthomes":
        return _unavailable("Not available for this source")

    facilities = row["nearby_facilities"]
    if facilities is None:
        return _unavailable("Nearby-facility data not yet available for this property")

    # Category DIVERSITY, not raw count - five gyms must not outscore
    # one gym + one school + one hospital.
    this_categories = {f.get("category") for f in facilities if f.get("category")}
    this_diversity = len(this_categories)

    diversities = []
    for other in all_entries:
        other_row = other["row"]
        if other_row["provider"] != "smarthomes" or other_row["nearby_facilities"] is None:
            continue
        other_categories = {
            f.get("category") for f in other_row["nearby_facilities"] if f.get("category")
        }
        diversities.append(len(other_categories))

    max_diversity = max(diversities) if diversities else 0

    if max_diversity == 0:
        return _valid(0.0, "No nearby facilities found for any compared property.")

    score = 100.0 * this_diversity / max_diversity
    reason = (
        f"{this_diversity} distinct nearby-facility categories "
        f"(gym, school, hospital, etc.), vs. {max_diversity} max in this comparison."
    )
    return _valid(score, reason)


# ------------------------------------------------------------
# PROPERTY FEATURES
# ------------------------------------------------------------

# Maps services/property_fields.py's FIELD_GROUPS group key to the
# actual MongoDB document key routes/property_routes.py's
# submit_listing() stores that group's values under - "extra" ->
# "type_details" and "pg" -> "pg_details" are the only two that
# differ from the group key itself (confirmed by direct inspection of
# the "BUILD MONGODB DOCUMENT" section).
_GROUP_KEY_TO_DOC_KEY = {
    "rooms": "rooms",
    "area": "area",
    "building": "building",
    "project": "project",
    "parking": "parking",
    "extra": "type_details",
    "legal": "legal",
    "pg": "pg_details",
}


def _applicable_feature_fields(property_type):
    """Every boolean field (across every FIELD_GROUPS group) whose
    applies_to includes this property_type - these are the fields
    this category counts as "property features". Reuses the EXISTING
    registry rather than hand-maintaining a second list, so this
    stays in sync automatically if the registry ever changes."""

    applicable = []
    for group_key, group_fields in FIELD_GROUPS:
        doc_key = _GROUP_KEY_TO_DOC_KEY[group_key]
        for field in group_fields:
            if field.get("kind") != "bool":
                continue
            if property_type in field.get("applies_to", ()):
                applicable.append((doc_key, field["name"]))
    return applicable


def score_property_features(entry, all_entries):
    row = entry["row"]

    if row["provider"] != "smarthomes":
        # Square Yards only ever exposes a flat, free-text amenity
        # list (already reflected in the Facilities/Amenities category
        # above) - there is no genuine, non-invented way to map that
        # onto SmartHomes' structured per-property-type feature
        # registry, so this category is marked unavailable rather than
        # guessing a mapping that doesn't actually exist.
        return _unavailable(
            "Square Yards does not expose structured property-feature data"
        )

    property_type = row["property_type"]
    applicable = _applicable_feature_fields(property_type)

    if not applicable:
        return _unavailable(f"No feature fields are defined for property type '{property_type}'")

    raw = entry.get("raw") or {}
    positive = 0
    for doc_key, field_name in applicable:
        sub_dict = raw.get(doc_key) or {}
        if sub_dict.get(field_name):
            positive += 1

    score = 100.0 * positive / len(applicable)
    reason = (
        f"{positive} of {len(applicable)} applicable features present "
        f"for property type '{property_type}'."
    )
    return _valid(score, reason)


# ------------------------------------------------------------
# ORCHESTRATION
# ------------------------------------------------------------

CATEGORY_SCORERS = {
    "price_value": score_price_value,
    "location": score_location,
    "facilities": score_facilities,
    "availability": score_availability,
    "connectivity": score_connectivity,
    "property_features": score_property_features,
}


def compute_ratings(entry, all_entries):
    """Computes every category score for ONE entry, then the overall
    rating as a weighted average over only the categories with valid
    data for THIS property, with the remaining weights renormalized
    (never redistributed to a different property, never treated as a
    zero). Returns a brand-new dict - never mutates `entry`."""

    categories = {}
    for key, scorer in CATEGORY_SCORERS.items():
        result = scorer(entry, all_entries)
        result["label"] = CATEGORY_LABELS[key]
        result["weight"] = BASE_WEIGHTS[key]
        categories[key] = result

    valid_keys = [key for key, c in categories.items() if c["status"] == "valid"]
    valid_weight_sum = sum(BASE_WEIGHTS[key] for key in valid_keys)

    if not valid_keys:
        overall = {
            "score": None,
            "status": "unavailable",
            "reason": "No rating categories have valid data for this property.",
            "basis": [],
        }
    else:
        weighted_sum = sum(
            categories[key]["score"] * BASE_WEIGHTS[key] for key in valid_keys
        )
        overall_score = weighted_sum / valid_weight_sum
        basis = [CATEGORY_LABELS[key] for key in valid_keys]
        overall = {
            "score": overall_score,
            "status": "valid",
            "reason": (
                f"Weighted average of {len(basis)} available "
                f"categor{'y' if len(basis) == 1 else 'ies'}: {', '.join(basis)}."
            ),
            "basis": basis,
        }

    return {"categories": categories, "overall": overall}


def _finalize_for_display(ratings):
    """Rounds every score to 2 decimal places - the ONLY rounding step
    in the whole pipeline, applied once, after all weighted-average
    math is already done (Phase 2's explicit requirement). Returns a
    new dict; does not mutate `ratings`."""

    categories = {}
    for key, category in ratings["categories"].items():
        new_category = dict(category)
        if new_category["score"] is not None:
            new_category["score"] = round(new_category["score"], 2)
        categories[key] = new_category

    overall = dict(ratings["overall"])
    if overall["score"] is not None:
        overall["score"] = round(overall["score"], 2)

    return {"categories": categories, "overall": overall}


def compare_properties(entries):
    """entries: list of {"provider", "id", "row": ComparisonRow,
    "raw": <the raw SmartHomes document or Square Yards normalized
    dict that row was built from>}.

    Returns a NEW list of {"row": ComparisonRow, "ratings": {...}} -
    never mutates `entries` or anything inside it (every row/raw dict
    passed in is only ever read, never written)."""

    results = []
    for entry in entries:
        ratings = compute_ratings(entry, entries)
        results.append({
            "row": dict(entry["row"]),
            "ratings": _finalize_for_display(ratings),
        })
    return results
