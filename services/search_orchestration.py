"""
Phase 3 search orchestration: natural-language query -> real MongoDB
filter (+ optional geospatial POI search) -> property results.

    raw_query
        |
        v
    services.nlp.parser.parse()          (Phase 2, untouched)
        |
        v
    StructuredQuery
        |
        +-------------------------------+
        |                               |
        v                               v
    merge_structured_fields()      location.type == "poi"?
    (explicit form fields win           |
     over parsed ones, field-           v
     by-field)                    resolve_poi_location()
        |                          -> services.mappls_service (Phase 1,
        |                             untouched) then
        |                             services.osm_location_service
        |                             (Phase 1, untouched)
        |                               |
        v                               v
    build_mongo_filter()  <----  MATCHED: adds a $near clause on the
        |                        existing location.coordinates 2dsphere
        |                        index. AMBIGUOUS/NO_MATCH/REJECTED/
        |                        ERROR: short-circuits with NO query
        |                        executed - see orchestrate_search().
        v
    PropertyService.filtered_search()   (Phase 3, new - real find(),
        |                                not ranked_search()'s Python
        v                                scoring)
    property documents

This module NEVER calls Mappls/OSM for anything other than resolving a
StructuredQuery.location that is already type=="poi" (i.e. it never
invents a location to resolve), NEVER invents coordinates for a failed
resolution, and NEVER silently drops a price/area bound - see
build_mongo_filter()'s docstring for the exact, disclosed rules used
for the two cases that need an explicit policy decision: the "approx"
operator (no natural hard bound) and the generic "parking" amenity code
(no single matching stored field). Both are documented, not guessed.

This is intentionally separate from services/property_services.py's
existing ranked_search() - see that method's own docstring. The
existing structured search endpoint (routes/search_routes.py's
search_rentals(), called with no "query" field) never reaches this
module at all.
"""
from __future__ import annotations

import re
from typing import Optional

from services.nlp.parser import parse as parse_nlp_query
from services import mappls_service


# ============================================================
# CONFIGURATION DEFAULTS
#
# Kept as plain module constants (not env-driven) since these are
# query-interpretation policy choices, not deployment/infra config -
# see the docstrings on build_mongo_filter() and resolve_poi_location()
# for why each value was chosen. DEFAULT_POI_RADIUS_KM mirrors the
# Phase 2 report's own "within 5 km of X" example.
# ============================================================

DEFAULT_POI_RADIUS_KM = 5.0

# No natural-language query gives an exact hard bound for "around X" /
# "approximately X" - a real number is required to build a MongoDB
# range filter, and silently treating "approx" as an exact match would
# make a legitimate approximate query return almost nothing. +/-10% is
# a clear, disclosed, symmetric default - not a silent guess - and can
# be revisited with real usage data later.
APPROX_PRICE_TOLERANCE = 0.10
APPROX_AREA_TOLERANCE = 0.10

# services/property_fields.py's AMENITY_CATEGORIES has no single
# generic "parking" value - it is split into these four. See
# build_mongo_filter()'s docstring for how the NLP layer's generic
# "parking" code (services/nlp/schema.py) is handled here: a disclosed
# "any of these" interpretation, not an invented single-subtype guess.
PARKING_SUBTYPE_FEATURE_CODES = [
    "covered_parking", "open_parking", "visitor_parking", "ev_charging_parking",
]

# Chennai center - same fallback used by routes/property_routes.py's
# existing /api/location/resolve-poi endpoint, for the same reason
# (Mappls resolves short/ambiguous POI names far better with a bias;
# SmartHomes' current listings are Chennai-only today).
DEFAULT_LOCATION_BIAS = "12.9716,80.2217"


# ============================================================
# STEP 1: PARSE + MERGE
# ============================================================

def merge_structured_fields(structured_dict: dict, overrides: dict) -> dict:
    """
    structured_dict: services.nlp.schema.StructuredQuery.to_dict() output.
    overrides: explicit, already-validated structured search fields from
      the request, using the SAME keys and "empty means not specified"
      convention routes/search_routes.py's search_rentals() already
      uses for its own structured fields:
        listing_type (str, "" = not specified)
        property_type (str, "" = not specified)
        bhk (number or None)
        budget (number, <= 0 = not specified - matches the existing
          endpoint's own "budget and budget > 0" convention)
        city (str, "" = not specified)
        locality (str, "" = not specified)

    Returns a merged, internal spec dict. An explicit override ALWAYS
    wins over the parsed equivalent for that field - NLP never silently
    replaces something the caller stated outright. Fields with no
    override and no parsed value are simply absent (never invented).
    """

    def slot_value(key):
        slot = structured_dict.get(key)
        return slot.get("value") if slot else None

    merged: dict = {}

    listing_type = overrides.get("listing_type") or slot_value("listing_type")
    if listing_type:
        merged["listing_type"] = listing_type

    property_type = overrides.get("property_type") or slot_value("property_type")
    if property_type:
        merged["property_type"] = property_type

    bhk = overrides.get("bhk")
    if bhk is None:
        bhk = slot_value("bedrooms")
    if bhk is not None:
        merged["bhk"] = bhk

    furnishing = slot_value("furnishing")  # no explicit-form equivalent exists today
    if furnishing:
        merged["furnishing"] = furnishing

    budget = overrides.get("budget")
    if budget and budget > 0:
        merged["price"] = {"operator": "lte", "value": float(budget)}
    elif structured_dict.get("price"):
        merged["price"] = structured_dict["price"]

    if structured_dict.get("area"):
        merged["area"] = structured_dict["area"]

    amenities = [a["value"] for a in (structured_dict.get("amenities") or [])]
    if amenities:
        merged["amenities"] = amenities

    # Stage 2 (Phase 4): NEARBY facilities, never confused with the
    # PROPERTY amenities list just above - see
    # services/nlp/schema.py's and nearby_facility_extractor.py's
    # module docstrings for the full distinction. No explicit-form
    # override exists for this today (there is no manual "nearby
    # facility" filter in the UI), so this is always exactly what the
    # query parsed to - nothing to merge/override here.
    nearby_facility_requirements = [
        {"category": f["category"], "radius_m": f["radius_m"]}
        for f in (structured_dict.get("nearby_facilities") or [])
    ]
    if nearby_facility_requirements:
        merged["nearby_facility_requirements"] = nearby_facility_requirements

    override_city = overrides.get("city") or ""
    override_locality = overrides.get("locality") or ""

    location = structured_dict.get("location")

    if override_city or override_locality:
        # Explicit city/locality fields always win - even if the query
        # also mentioned a POI, we don't want to silently discard a
        # field the caller stated outright. The POI mention, if any, is
        # simply not used for geospatial filtering in that case.
        merged["city"] = override_city or None
        merged["locality"] = override_locality or None
    elif location and location.get("type") == "area_or_city":
        # ranked_search()'s own city/locality scoring is symmetric and
        # purely additive (see services/property_services.py) - neither
        # field can ever be penalized for not matching, only rewarded
        # for matching. Putting the same parsed text in both lets
        # whichever field the property document actually has it in
        # match, without us having to guess locality-vs-city from text
        # alone (services/nlp/location_extractor.py explicitly does not
        # attempt that distinction - see its module docstring).
        merged["city"] = location["query"]
        merged["locality"] = location["query"]
    elif location and location.get("type") == "poi":
        merged["poi_query"] = location["query"]

    return merged


# ============================================================
# STEP 2: POI RESOLUTION (Phase 1, reused verbatim)
# ============================================================

def resolve_poi_location(
    poi_query: str,
    mappls_api_key: Optional[str],
    osm_service,
    location_bias: Optional[str] = None,
) -> dict:
    """
    Runs the SAME Mappls -> OSM chain routes/property_routes.py's
    /api/location/resolve-poi endpoint already uses. Mappls remains the
    sole authority for WHICH entity the query means; OSM only ever
    tries to locate the entity Mappls already selected - this function
    changes neither of those Phase 1 behaviors.

    Returns:
        {
            "status": "matched" | "ambiguous" | "no_match" | "rejected"
                       | "error",
            "latitude": float | None,
            "longitude": float | None,
            "mappls_place_name": str | None,
            "confidence": float | None,
            "error": str | None,
            "alternates": [{matched_name, matched_address, latitude,
                             longitude, score}, ...],
        }

    "alternates" is passed straight through from OSM's own result (see
    services/osm_location_service.py's resolve_coordinates() docstring)
    - for an "ambiguous" status specifically, it includes the top-ranked
    candidate too (not just runners-up), so a caller can offer the user
    a "did you mean one of these?" picker without a second lookup.
    """

    result = {
        "status": "error",
        "latitude": None,
        "longitude": None,
        "mappls_place_name": None,
        "confidence": None,
        "error": None,
        "alternates": [],
    }

    mappls_result = mappls_service.resolve_place(
        poi_query, mappls_api_key, location_bias=location_bias or DEFAULT_LOCATION_BIAS
    )

    if mappls_result["status"] == "no_match":
        result["status"] = "no_match"
        result["error"] = "Mappls could not resolve this place."
        return result

    if mappls_result["status"] != "matched":
        result["status"] = "error"
        result["error"] = mappls_result.get("error") or "Mappls lookup failed."
        return result

    result["mappls_place_name"] = mappls_result["place_name"]

    osm_result = osm_service.resolve_coordinates({
        "place_name": mappls_result["place_name"],
        "address": mappls_result["place_address"],
        "eloc": mappls_result["eloc"],
        "type": mappls_result["type"],
    })

    result["status"] = osm_result["status"]
    result["confidence"] = osm_result["confidence"]
    result["error"] = osm_result["error"]
    result["alternates"] = osm_result.get("alternates", [])

    if osm_result["status"] == "matched":
        result["latitude"] = osm_result["latitude"]
        result["longitude"] = osm_result["longitude"]

    return result


# ============================================================
# STEP 3: MONGO FILTER CONSTRUCTION
# ============================================================

def _range_filter(constraint: dict, approx_tolerance: float) -> Optional[dict]:
    """Turns a schema.RangeConstraint dict into a MongoDB range operator
    dict. Preserves operator semantics exactly - lte/gte are never
    collapsed into eq, between always keeps both bounds. "approx" is the
    one operator with no natural hard bound in the source query - see
    APPROX_PRICE_TOLERANCE/APPROX_AREA_TOLERANCE above for the
    disclosed, symmetric-percentage policy used here."""

    operator = constraint.get("operator")

    if operator == "between":
        lo, hi = constraint.get("value_min"), constraint.get("value_max")
        if lo is None or hi is None:
            return None
        return {"$gte": lo, "$lte": hi}

    value = constraint.get("value")
    if value is None:
        return None

    if operator == "lte":
        return {"$lte": value}
    if operator == "gte":
        return {"$gte": value}
    if operator == "eq":
        return {"$eq": value}
    if operator == "approx":
        return {
            "$gte": value * (1 - approx_tolerance),
            "$lte": value * (1 + approx_tolerance),
        }

    return None


def build_mongo_filter(merged: dict) -> tuple:
    """
    Builds (mongo_filter, applied_filters_summary) from a merged spec
    (see merge_structured_fields()). Does NOT add a geospatial clause -
    that is added separately by orchestrate_search() only once a POI
    has actually resolved to coordinates, since a filter dict with no
    valid geo clause must never be silently sent as if it had one.

    applied_filters_summary is a plain-data, safe-to-return-to-the-
    caller description of what was actually applied (Step 9's debug
    metadata) - never includes API keys or other secrets.
    """

    mongo_filter: dict = {"listing.status": "active"}
    applied = {}
    and_clauses = []

    if merged.get("listing_type"):
        mongo_filter["listing.type"] = merged["listing_type"]
        applied["listing_type"] = merged["listing_type"]

    if merged.get("property_type"):
        mongo_filter["property.type"] = merged["property_type"]
        applied["property_type"] = merged["property_type"]

    if merged.get("bhk") is not None:
        mongo_filter["property.bhk"] = merged["bhk"]
        applied["bhk"] = merged["bhk"]

    if merged.get("furnishing"):
        mongo_filter["property.furnishing"] = merged["furnishing"]
        applied["furnishing"] = merged["furnishing"]

    if merged.get("price"):
        price_filter = _range_filter(merged["price"], APPROX_PRICE_TOLERANCE)
        if price_filter:
            mongo_filter["listing.price"] = price_filter
            applied["price"] = {**merged["price"], "mongo": price_filter}

    if merged.get("area"):
        area_filter = _range_filter(merged["area"], APPROX_AREA_TOLERANCE)
        if area_filter:
            mongo_filter["property.area_sqft"] = area_filter
            applied["area"] = {**merged["area"], "mongo": area_filter}

    amenities = merged.get("amenities") or []
    if amenities:
        applied_amenities = []
        for code in amenities:
            if code == "parking":
                # Disclosed generic interpretation, not an invented
                # single-subtype guess - see PARKING_SUBTYPE_FEATURE_CODES
                # above. Matches if the property has ANY parking.
                and_clauses.append({"features": {"$in": PARKING_SUBTYPE_FEATURE_CODES}})
                applied_amenities.append({"parking": PARKING_SUBTYPE_FEATURE_CODES})
            else:
                and_clauses.append({"features": code})
                applied_amenities.append(code)
        applied["amenities"] = applied_amenities

    nearby_facility_requirements = merged.get("nearby_facility_requirements") or []
    if nearby_facility_requirements:
        # Stage 2: uses services/nearby_facility_service.py's ALREADY-
        # STORED nearby_facilities[] data (see that module - Mappls is
        # NEVER called per search here, only once, at registration
        # time). One $elemMatch per requested category - a single
        # $elemMatch cannot require two DIFFERENT array elements to
        # both exist, so multiple categories become multiple $and
        # clauses (the existing $and mechanism, same as amenities
        # above). No radius given -> match on category alone (whatever
        # distance was actually stored at enrichment time - see
        # NearbyFacilityRequirement's own docstring for why that's
        # never silently treated as "any distance at all"). A radius
        # narrower than what's actually STORED for a genuinely-close
        # facility cannot incorrectly exclude it - $lte only ever
        # narrows the match, never widens it past what was discovered.
        applied_nearby = []
        for requirement in nearby_facility_requirements:
            category = requirement.get("category")
            if not category:
                continue
            elem_match: dict = {"category": category}
            radius_m = requirement.get("radius_m")
            if radius_m is not None:
                elem_match["distance_m"] = {"$lte": radius_m}
            and_clauses.append({"nearby_facilities": {"$elemMatch": elem_match}})
            applied_nearby.append({"category": category, "radius_m": radius_m})
        if applied_nearby:
            applied["nearby_facilities"] = applied_nearby

    city = merged.get("city")
    locality = merged.get("locality")
    if city or locality:
        text = city or locality
        pattern = re.escape(text)
        and_clauses.append({"$or": [
            {"location.city": {"$regex": pattern, "$options": "i"}},
            {"location.locality": {"$regex": pattern, "$options": "i"}},
        ]})
        applied["area_or_city_text"] = text

    if and_clauses:
        mongo_filter["$and"] = and_clauses

    return mongo_filter, applied


def _nearby_facility_enrichment_caveat(property_service, nearby_facility_requirements: list) -> Optional[dict]:
    """Stage 2: when a search used a nearby-facility constraint, this
    reports how many OTHER active listings simply haven't finished
    background enrichment yet (services/nearby_facility_service.py,
    Stage 1) - status missing/"pending"/"failed"/"skipped". Those
    properties are silently absent from the result set (a MongoDB
    filter can only return matches, never explain a non-match), which
    would otherwise look identical to "these listings genuinely have no
    gym nearby". This turns that into an honest, visible caveat instead
    - never claims enrichment failure means "no facility exists" (the
    explicit requirement this exists to satisfy).

    One extra, cheap count_documents() call - only made when a
    nearby-facility constraint is actually present in the query, never
    on every search."""

    if not nearby_facility_requirements:
        return None

    unenriched_count = property_service.count({
        "listing.status": "active",
        "$or": [
            {"nearby_facilities_metadata": {"$exists": False}},
            {"nearby_facilities_metadata.status": {"$in": ["pending", "failed", "skipped"]}},
        ],
    })

    return {
        "unenriched_active_listings": unenriched_count,
        "note": (
            "Some active listings have not finished nearby-facility enrichment yet "
            "and could not be checked for this search - this is not the same as "
            "confirming they have no nearby match."
        ) if unenriched_count else None,
    }


# ============================================================
# STEP 4: FULL ORCHESTRATION
# ============================================================

def orchestrate_search(
    raw_query: str,
    overrides: dict,
    mappls_api_key: Optional[str],
    osm_service,
    property_service,
    poi_radius_km: float = DEFAULT_POI_RADIUS_KM,
    location_bias: Optional[str] = None,
    explicit_coordinates: Optional[tuple] = None,
) -> dict:
    """
    Full Phase 3 pipeline for one search request. Never raises for a
    malformed/unknown query - services.nlp.parser.parse() itself never
    raises (see test_nlp_parser.py), and every failure mode below
    resolves to an explicit result rather than an exception.

    explicit_coordinates: optional (latitude, longitude) tuple. When
    given, POI resolution (Mappls/OSM) is skipped ENTIRELY for this
    call - used when a caller already knows exactly where to search,
    e.g. the user picked one specific option from a previous
    "ambiguous" result's alternates (see resolve_poi_location()'s
    docstring) rather than the free-text POI mention being re-resolved
    (which would just be ambiguous again, since nothing about the query
    text changed). Every other parsed/explicit field is still applied
    normally - only the location step is replaced.

    Returns:
        {
            "parsed_query": StructuredQuery.to_dict(),
            "location_resolution": resolve_poi_location() result | None,
            "applied_filters": dict,
            "properties": [...],
        }
    """

    structured = parse_nlp_query(raw_query or "")
    structured_dict = structured.to_dict()

    merged = merge_structured_fields(structured_dict, overrides)

    poi_query = merged.pop("poi_query", None)

    # Stage 2: computed once, attached to every return path below (see
    # _nearby_facility_enrichment_caveat()'s own docstring) - None when
    # this search used no nearby-facility constraint at all, so callers
    # never have to distinguish "no caveat" from "zero unenriched
    # listings" via a falsy count.
    nearby_facility_enrichment_caveat = _nearby_facility_enrichment_caveat(
        property_service, merged.get("nearby_facility_requirements") or []
    )

    if explicit_coordinates is not None:
        latitude, longitude = explicit_coordinates

        mongo_filter, applied_filters = build_mongo_filter(merged)
        mongo_filter["location.coordinates"] = {
            "$near": {
                "$geometry": {"type": "Point", "coordinates": [longitude, latitude]},
                "$maxDistance": poi_radius_km * 1000.0,
            }
        }
        applied_filters["poi_radius_km"] = poi_radius_km

        properties = property_service.filtered_search(mongo_filter)

        return {
            "parsed_query": structured_dict,
            "location_resolution": {
                "status": "matched",
                "latitude": latitude,
                "longitude": longitude,
                "mappls_place_name": None,
                "confidence": None,
                "error": None,
                "alternates": [],
            },
            "applied_filters": applied_filters,
            "properties": properties,
            "nearby_facility_enrichment_caveat": nearby_facility_enrichment_caveat,
        }

    if poi_query:
        location_resolution = resolve_poi_location(
            poi_query, mappls_api_key, osm_service, location_bias=location_bias
        )

        if location_resolution["status"] != "matched":
            # Do NOT silently fall back to a location-unfiltered search -
            # that would return results for an unrelated area as if they
            # satisfied a location constraint the user explicitly gave.
            # Every other parsed/explicit filter is still reported in
            # applied_filters for transparency, but no query is run.
            _, applied_filters = build_mongo_filter(merged)
            return {
                "parsed_query": structured_dict,
                "location_resolution": location_resolution,
                "applied_filters": applied_filters,
                "properties": [],
                "nearby_facility_enrichment_caveat": nearby_facility_enrichment_caveat,
            }

        mongo_filter, applied_filters = build_mongo_filter(merged)
        mongo_filter["location.coordinates"] = {
            "$near": {
                "$geometry": {
                    "type": "Point",
                    "coordinates": [location_resolution["longitude"], location_resolution["latitude"]],
                },
                "$maxDistance": poi_radius_km * 1000.0,
            }
        }
        applied_filters["poi_radius_km"] = poi_radius_km

        properties = property_service.filtered_search(mongo_filter)

        return {
            "parsed_query": structured_dict,
            "location_resolution": location_resolution,
            "applied_filters": applied_filters,
            "properties": properties,
            "nearby_facility_enrichment_caveat": nearby_facility_enrichment_caveat,
        }

    # No POI to resolve - a plain filtered search (possibly with a
    # city/locality text filter, possibly with none at all).
    mongo_filter, applied_filters = build_mongo_filter(merged)
    properties = property_service.filtered_search(mongo_filter)

    return {
        "parsed_query": structured_dict,
        "location_resolution": None,
        "applied_filters": applied_filters,
        "properties": properties,
        "nearby_facility_enrichment_caveat": nearby_facility_enrichment_caveat,
    }
