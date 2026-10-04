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
from services import location_provider_service


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

def merge_structured_fields(
    structured_dict: dict, overrides: dict, default_listing_type: Optional[str] = None
) -> dict:
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
    default_listing_type: optional page-level fallback (e.g. the
      Rentals page defaulting to "rent"), used ONLY when neither an
      explicit override NOR the NLP parse produced a listing_type.
      Deliberately a caller-supplied value, never hardcoded here -
      this function stays generic across every caller (e.g.
      routes/design_routes.py passes none and keeps today's "absent
      means absent" behavior).

    Returns a merged, internal spec dict. Precedence for listing_type
    (and every other overridable field) is: explicit override first
    (a manual/explicit value from the caller), then the NLP-parsed
    value (explicit intent in the query text, e.g. "for sale"), then
    default_listing_type last. An explicit override or explicit NLP
    intent ALWAYS wins over the page-level default - NLP never
    silently replaces something the caller stated outright, and the
    default never silently replaces explicit NLP intent either. Fields
    with no override, no parsed value, and no default are simply
    absent (never invented).
    """

    def slot_value(key):
        slot = structured_dict.get(key)
        return slot.get("value") if slot else None

    merged: dict = {}

    listing_type = (
        overrides.get("listing_type")
        or slot_value("listing_type")
        or default_listing_type
    )
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
        detected_city = location.get("city")
        if detected_city:
            # services/nlp/location_extractor.py detected a genuine
            # "<locality> <city>" or "<locality>, <city>" split (e.g.
            # "Velachery Chennai" -> locality="Velachery",
            # city="Chennai") - match each part against its OWN text
            # independently (see build_mongo_filter() below) instead of
            # requiring a single field to contain both words as one
            # literal substring. This is the fix for queries like
            # "2 BHK in Velachery Chennai" never matching a document
            # storing city="Chennai"/locality="Velachery" separately.
            merged["city"] = detected_city
            merged["locality"] = location["query"]
        else:
            # No split detected (a plain city name, or a plain locality
            # name with no recognized city attached) - existing
            # symmetric behavior, UNCHANGED: ranked_search()'s own city/
            # locality scoring is symmetric and purely additive (see
            # services/property_services.py) - neither field can ever
            # be penalized for not matching, only rewarded for
            # matching. Putting the same parsed text in both lets
            # whichever field the property document actually has it in
            # match, without us having to guess locality-vs-city from
            # text alone.
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
# STEP 2b: PROVIDER ORCHESTRATION (Ola primary, Mappls+OSM fallback)
#
# Composes services/location_provider_service.py's Ola-only resolver
# with resolve_poi_location() (Phase 1, unchanged, directly above) as
# the fallback. This composition deliberately lives HERE rather than
# inside location_provider_service.py itself - that module must not
# import this one (this module already imports it for the Ola step),
# which would be a circular import; keeping the fallback wiring at this
# level also means every existing Mappls/OSM test's patch target (e.g.
# "services.search_orchestration.mappls_service.resolve_place") stays
# valid unchanged, since resolve_poi_location() itself is untouched.
# ============================================================

def _city_already_mentioned(query: str, city: str) -> bool:
    """Case-insensitive, word-bounded: does `query` already contain
    `city` as a token? Prevents resolve_poi_location_via_best_provider()
    below from ever producing "VIT Chennai, Chennai" or re-appending a
    city that's already part of the POI text (e.g. "Marina Mall,
    Chennai" after a FIRST retry already added it, should this function
    somehow be called twice for the same effective query - defense in
    depth, even though the caller only ever retries once)."""

    return bool(re.search(rf"\b{re.escape(city)}\b", query, re.IGNORECASE))


def resolve_poi_location_via_best_provider(
    poi_query: str,
    ola_api_key: Optional[str],
    mappls_api_key: Optional[str],
    osm_service,
    location_bias: Optional[str] = None,
    detected_city: Optional[str] = None,
) -> dict:
    """
    Ola PRIMARY -> Mappls+OSM FALLBACK, per this phase's required
    architecture. Ola is tried first; only when it does NOT produce a
    safe "matched" result (no_match / ambiguous / error) does this fall
    back to the exact same Mappls -> OSM chain
    routes/property_routes.py's /api/location/resolve-poi endpoint and
    the pre-Ola search flow already used. Never turns a failed/
    ambiguous Ola lookup into an unfiltered or arbitrary location -
    every status below is one of resolve_poi_location()'s own explicit
    vocabulary (matched/ambiguous/no_match/rejected/error), PLUS this
    function's own "ambiguous-with-alternates-to-pick-from" case below.

    detected_city: optional, from services.nlp.schema.LocationMention.city
    (see services/nlp/location_extractor.py) - a city name the NLP
    layer found WITHIN the user's own POI phrase (e.g. "Chennai" from
    "VIT Chennai", or "Bangalore" from "Phoenix Mall in Bangalore").
    NEVER a hardcoded default, NEVER invented when the user didn't
    mention one - None here means "no city information available",
    and this function then behaves EXACTLY as before this parameter
    existed (every call site that omits it, e.g. any direct/older
    caller, is completely unaffected).

    Two NEW behaviors, both strictly additive on top of the pre-
    existing Ola -> Mappls -> OSM chain - the provider order itself is
    never changed:

    1. AMBIGUOUS + alternates available: Ola's own candidates are
       SURFACED (status="ambiguous", "alternates" populated with
       place_id/provider="ola" included - see
       services/location_provider_service.py's resolve_location_via_ola())
       instead of silently discarding them and giving Mappls+OSM an
       independent attempt (the PRE-EXISTING behavior, which the
       existing test suite's history already names explicitly - see
       test_search_orchestration.py). The existing frontend "did you
       mean one of these?" picker (templates/rentals.html) already
       dispatches on exactly this status/shape - no new endpoint was
       needed for this. If Ola is ambiguous with ZERO alternates (a
       defensive edge case, not expected in practice), this still
       falls through to Mappls -> OSM exactly as before.

    2. NO_MATCH + a usable detected_city not already present in
       `poi_query`: retries Ola EXACTLY ONCE with
       "<poi_query>, <detected_city>" (reusing
       location_provider_service.resolve_location_via_ola() itself -
       no second Ola implementation). If that retry is "matched", its
       coordinates are returned directly (Mappls/OSM never run at
       all). If the retry is anything else (no_match / ambiguous /
       error), this falls through to the EXISTING Mappls -> OSM chain
       using the ORIGINAL (un-suffixed) poi_query - never the retry
       string, and never a third Ola attempt, never a Mappls/OSM
       retry. A retry result of "ambiguous" is deliberately treated
       the same as "no_match" here (falls through) rather than
       surfacing a SECOND picker for a city-qualified guess the user
       never typed themselves - a disclosed scope decision, not an
       oversight.

    Returns the SAME shape as resolve_poi_location() (see its
    docstring), plus one extra key:
        "provider": "ola" | "mappls" | None
            None when nothing resolved (no_match/ambiguous/error) -
            there is no provider to credit for a non-final result.
    """

    ola_result = location_provider_service.resolve_location_via_ola(
        poi_query, ola_api_key, location_bias=location_bias
    )

    if ola_result["status"] == "matched":
        return {
            "status": "matched",
            "latitude": ola_result["latitude"],
            "longitude": ola_result["longitude"],
            "mappls_place_name": None,
            "confidence": ola_result["confidence"],
            "error": None,
            "alternates": [],
            "provider": "ola",
        }

    if ola_result["status"] == "ambiguous" and ola_result["alternates"]:
        # Objective 1: let the user choose from Ola's own candidates
        # rather than silently handing an independent attempt to
        # Mappls+OSM. See this function's docstring, point 1.
        return {
            "status": "ambiguous",
            "latitude": None,
            "longitude": None,
            "mappls_place_name": None,
            "confidence": ola_result["confidence"],
            "error": ola_result["error"],
            "alternates": ola_result["alternates"],
            "provider": None,
        }

    if (
        ola_result["status"] == "no_match"
        and detected_city
        and not _city_already_mentioned(poi_query, detected_city)
    ):
        retry_query = f"{poi_query}, {detected_city}"
        retry_result = location_provider_service.resolve_location_via_ola(
            retry_query, ola_api_key, location_bias=location_bias
        )

        if retry_result["status"] == "matched":
            return {
                "status": "matched",
                "latitude": retry_result["latitude"],
                "longitude": retry_result["longitude"],
                "mappls_place_name": None,
                "confidence": retry_result["confidence"],
                "error": None,
                "alternates": [],
                "provider": "ola",
            }
        # Retry ambiguous/no_match/error - exactly one additional Ola
        # attempt maximum (see this function's docstring, point 2) -
        # falls through below using the ORIGINAL poi_query, never the
        # retry string and never a third Ola call.

    # Ola did not produce a safe result (no_match with no usable city,
    # ambiguous with no alternates, a failed retry, or error) - fall
    # back to the existing, unmodified Mappls -> OSM chain, using the
    # ORIGINAL poi_query.
    fallback = resolve_poi_location(
        poi_query, mappls_api_key, osm_service, location_bias=location_bias
    )
    fallback["provider"] = "mappls" if fallback["status"] == "matched" else None
    return fallback


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

    # One $or clause (matching EITHER location.city or location.locality
    # - never assuming which field actually holds a given piece of text,
    # the same "don't guess locality-vs-city" philosophy
    # services/nlp/location_extractor.py already follows) PER DISTINCT
    # text, $and-ed together. When city == locality (the existing
    # single-text case - a plain city name or a plain locality name
    # with no separate city attached) this collapses to exactly one
    # clause, byte-for-byte the prior behavior. When city != locality
    # (services/nlp/location_extractor.py detected a genuine
    # "<locality> <city>" split, e.g. "Velachery"/"Chennai"), this
    # requires BOTH texts to independently be found somewhere in the
    # location sub-document, instead of silently ignoring one of them.
    location_texts = []
    for text in (city, locality):
        if text and text not in location_texts:
            location_texts.append(text)

    if location_texts:
        for text in location_texts:
            pattern = re.escape(text)
            and_clauses.append({"$or": [
                {"location.city": {"$regex": pattern, "$options": "i"}},
                {"location.locality": {"$regex": pattern, "$options": "i"}},
            ]})
        # Always a single string (never a list) - square_yards_service.
        # build_search_args() and the frontend both expect a plain
        # location string here. A genuine two-part split joins as
        # "Velachery, Chennai" - itself a perfectly good location
        # string for Square Yards too, not just for Mongo.
        applied["area_or_city_text"] = ", ".join(location_texts)

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


def _attach_matched_nearby_facilities(properties: list, nearby_facility_requirements: list) -> None:
    """Phase 5 (Part 7/8): for every property in a search that used a
    nearby-facility constraint, records WHICH of that property's own
    stored services/nearby_facility_service.py facilities actually
    satisfied each requested category - so the UI can show the real
    facility NAME ("Gold's Gym - 780 m away") instead of just the bare
    category ("Gym - 780 m away").

    Mutates each property dict in place, attaching a
    "_matched_nearby_facilities" key - the SAME pattern
    services/property_services.py's ranked_search() already uses for
    "_match_score" (an internal, underscore-prefixed field the search
    layer adds on top of the stored document; routes/search_routes.py's
    serializer reads it and exposes it under the public name
    "matched_nearby_facilities", omitting the key entirely for an
    ordinary search with no nearby-facility requirement - see that
    serializer for why response size/shape for ordinary searches is
    unaffected).

    Selection semantics when a property has MULTIPLE stored facilities
    for the same requested category: picks the CLOSEST one
    (minimum distance_m). This matches the order
    services/nearby_facility_service.py already stores them in (each
    category's discovered places are sorted closest-first before
    being kept - see that module's _discover_category()) - not a new
    ranking rule invented here.

    A requirement with no matching stored facility on a given property
    (should not normally happen for a property that matched the
    $elemMatch filter at all, but handled defensively - e.g. a property
    matching on ONE of several requested categories) is simply omitted
    from that property's list rather than guessed at.
    """

    if not nearby_facility_requirements:
        return

    for property_item in properties:

        stored = property_item.get("nearby_facilities") or []
        matched = []

        for requirement in nearby_facility_requirements:

            category = requirement.get("category")
            radius_m = requirement.get("radius_m")

            if not category:
                continue

            candidates = [
                facility for facility in stored
                if facility.get("category") == category
                and (
                    radius_m is None
                    or (facility.get("distance_m") is not None and facility["distance_m"] <= radius_m)
                )
            ]

            if not candidates:
                continue

            best = min(
                candidates,
                key=lambda f: f["distance_m"] if f.get("distance_m") is not None else float("inf"),
            )

            matched.append({
                "category": category,
                "name": best.get("name"),
                "distance_m": best.get("distance_m"),
            })

        property_item["_matched_nearby_facilities"] = matched


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
    ola_api_key: Optional[str] = None,
    default_listing_type: Optional[str] = None,
) -> dict:
    """
    Full Phase 3 pipeline for one search request. Never raises for a
    malformed/unknown query - services.nlp.parser.parse() itself never
    raises (see test_nlp_parser.py), and every failure mode below
    resolves to an explicit result rather than an exception.

    default_listing_type: optional, passed straight through to
    merge_structured_fields() - see that function's docstring. A new
    KEYWORD-only-by-convention parameter appended at the end, same as
    ola_api_key below, so every existing positional call keeps working
    unchanged. None (the default) preserves today's behavior exactly.

    ola_api_key: optional, added for this phase's Ola-primary/Mappls-
    fallback provider architecture (see
    resolve_poi_location_via_best_provider() above). Deliberately a new
    KEYWORD-only-by-convention parameter appended at the end, not
    inserted earlier - every existing positional call to this function
    (see test_search_orchestration.py) must keep working unchanged.
    When omitted (None), POI resolution falls straight to the existing
    Mappls -> OSM chain, exactly as before this phase - Ola is additive,
    never a hard dependency.

    explicit_coordinates: optional (latitude, longitude) tuple. When
    given, POI resolution (Ola/Mappls/OSM) is skipped ENTIRELY for this
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
            "location_resolution":
                resolve_poi_location_via_best_provider() result | None,
            "applied_filters": dict,
            "properties": [...],
        }
    """

    structured = parse_nlp_query(raw_query or "")
    structured_dict = structured.to_dict()

    merged = merge_structured_fields(
        structured_dict, overrides, default_listing_type=default_listing_type
    )

    poi_query = merged.pop("poi_query", None)

    # services.nlp.schema.LocationMention.city - a city name the NLP
    # layer found WITHIN the user's own POI phrase (see
    # services/nlp/location_extractor.py). Always None for a
    # non-"poi" location (or no location at all) - by construction,
    # never guessed here. Passed straight through to
    # resolve_poi_location_via_best_provider()'s city-qualified retry;
    # see that function's own docstring for the full behavior.
    detected_city = ((structured_dict.get("location") or {}).get("city"))

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
        _attach_matched_nearby_facilities(properties, merged.get("nearby_facility_requirements") or [])

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
                "provider": None,
            },
            "applied_filters": applied_filters,
            "properties": properties,
            "nearby_facility_enrichment_caveat": nearby_facility_enrichment_caveat,
        }

    if poi_query:
        location_resolution = resolve_poi_location_via_best_provider(
            poi_query, ola_api_key, mappls_api_key, osm_service, location_bias=location_bias,
            detected_city=detected_city,
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
        _attach_matched_nearby_facilities(properties, merged.get("nearby_facility_requirements") or [])

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
    _attach_matched_nearby_facilities(properties, merged.get("nearby_facility_requirements") or [])

    return {
        "parsed_query": structured_dict,
        "location_resolution": None,
        "applied_filters": applied_filters,
        "properties": properties,
        "nearby_facility_enrichment_caveat": nearby_facility_enrichment_caveat,
    }
