"""
Phase 4.0: nearby-facility enrichment for a registered property.

    property.location.coordinates (already stored, required at
    submission - see routes/property_routes.py's submit_listing())
            |
            v
    for each facility category (see FACILITY_CATEGORIES):
            |
            v
    Mappls Nearby search (services.mappls_service.find_nearby_places)
    -> candidate places, each with MAPPLS' OWN provider-computed
       distance_m from the property's coordinates - verified live
       against this account (Sep 2026): this endpoint does NOT return
       latitude/longitude for a result (same limitation already
       documented in services/mappls_service.py and
       services/osm_location_service.py for Phase 1's text-search flow)
            |
            v
    normalize + de-duplicate (by Mappls eLoc within each category)
            |
            v
    for the closest few candidates per category (bounded - see
    COORDINATE_RESOLUTION_LIMIT_PER_CATEGORY), best-effort resolve
    actual coordinates via the EXISTING Phase 1 OSM chain
    (services.osm_location_service.OSMLocationService.resolve_coordinates) -
    reused exactly as Phase 1/3 already use it, never re-implemented.
    A facility whose coordinates couldn't be resolved (ambiguous/
    no_match/rejected/error, or simply not attempted because of the
    per-category cap) still keeps its Mappls-provided distance_m -
    "we don't know exactly where this is on a map" is not the same
    fact as "we don't know how far it is", and the latter is what
    Mappls already told us directly.
            |
            v
    persist nearby_facilities[] + nearby_facilities_metadata on the
    property document via the EXISTING PropertyService.get_property()/
    update_property() methods - no new MongoDB access pattern

This module NEVER raises. Property registration must succeed
regardless of what happens here (Mappls down, OSM down, malformed
provider data, zero results) - every failure mode is caught and
recorded in nearby_facilities_metadata instead, never silently
swallowed and never allowed to look like a real "no facilities found"
result. See enrich_property_nearby_facilities()'s docstring.

NOT implemented here (deliberately, per this phase's scope): natural-
language "gym nearby" search, ranking/recommendation, road/walking/
driving distance, a scheduled refresh job. This module only builds and
maintains the data those future phases would read.
"""

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from services import mappls_service

# ============================================================
# FACILITY TAXONOMY
#
# Canonical SmartHomes facility category -> the free-text keyword sent
# to Mappls' Nearby Search API (services.mappls_service.find_nearby_places).
# This is a category-to-search-term mapping (a taxonomy), NOT a
# business-name alias table - it never says "this specific business IS
# a gym", only "search Mappls for the word 'gym' to find gyms". Mappls
# itself identifies the actual matching entities.
#
# Extending the taxonomy later is just adding one more entry here - no
# other code needs to change.
# ============================================================

FACILITY_CATEGORIES: dict = {
    "gym": "gym",
    "hospital": "hospital",
    "school": "school",
    "college": "college",
    "supermarket": "supermarket",
    "pharmacy": "pharmacy",
    "restaurant": "restaurant",
    "bank": "bank",
    "atm": "atm",
    "metro_station": "metro station",
    "railway_station": "railway station",
    "bus_stop": "bus stop",
    "shopping_mall": "shopping mall",
    "park": "park",
    "police_station": "police station",
    "fire_station": "fire station",
    "petrol_station": "petrol pump",
}


# ============================================================
# CONFIGURATION DEFAULTS
#
# Real values are read from environment variables in app.py and passed
# in explicitly by the caller (matching services/osm_location_service.py's
# convention: this module never reads os.environ or current_app itself).
# ============================================================

# A real-estate-relevant "walkable/nearby" radius - deliberately tighter
# than Phase 3's SEARCH_POI_RADIUS_KM (5 km), which answers a different
# question ("how far will an ambiguous landmark's area spread affect a
# property SEARCH") than this one ("what counts as a nearby AMENITY for
# someone evaluating a home").
DEFAULT_RADIUS_KM = 2.0

# How many facilities to keep (after de-duplication) per category. Bounds
# document size and keeps the common case (a handful of genuinely close
# options) without silently dropping category coverage.
DEFAULT_MAX_RESULTS_PER_CATEGORY = 5

# How many of those (closest-first) get an actual OSM coordinate lookup
# per category. Mappls' Nearby call itself is cheap (one HTTP request
# per category, no documented rate limit) - the real cost is
# Nominatim's OWN 1 request/second policy (see
# services/osm_location_service.py's MIN_REQUEST_INTERVAL_SECONDS),
# enforced per resolve_coordinates() call and shared across this whole
# app. Resolving coordinates for every candidate in every category
# (up to DEFAULT_MAX_RESULTS_PER_CATEGORY x len(FACILITY_CATEGORIES))
# would make a single property's enrichment take minutes. Keeping this
# small and bounding it PER CATEGORY (not globally) guarantees every
# category gets a fair shot at at least one resolved-coordinate result,
# while keeping worst-case latency proportional to the category count,
# not the per-category result count. See docs/PHASE_4_0_NEARBY_FACILITY_ENRICHMENT.md
# for the latency tradeoff this implies and why it's an accepted,
# disclosed limitation for this phase rather than a background job.
DEFAULT_COORDINATE_RESOLUTION_LIMIT_PER_CATEGORY = 1


# ============================================================
# NORMALIZATION / VALIDATION
# ============================================================

def _is_valid_coordinate(latitude, longitude) -> bool:
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return False
    return -90 <= latitude <= 90 and -180 <= longitude <= 180


def _normalize_name_for_dedup(name: Optional[str]) -> str:
    """Lowercase, strip accents/punctuation/whitespace - used ONLY as a
    fallback dedup key when Mappls' own eLoc is missing (rare). Never
    used to merge two records just because their names look similar
    once normalized THIS aggressively is not attempted - see
    _dedupe_places()'s docstring."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def _normalize_place(raw_place: dict, category: str, radius_m: float) -> Optional[dict]:
    """Turns one services.mappls_service.find_nearby_places() place dict
    into this module's internal facility shape. Returns None for a
    malformed entry (no usable name) rather than raising - a single bad
    record must never take down the rest of a category's results."""

    if not isinstance(raw_place, dict):
        return None

    name = (raw_place.get("place_name") or "").strip()

    if not name:
        return None

    distance_m = raw_place.get("distance_m")

    try:
        distance_m = float(distance_m) if distance_m is not None else None
    except (TypeError, ValueError):
        distance_m = None

    return {
        "name": name,
        "category": category,
        "address": raw_place.get("place_address") or None,
        "latitude": None,
        "longitude": None,
        "coordinates": None,
        "distance_m": distance_m,
        "source": "mappls",
        "coordinate_source": None,
        "provider_id": raw_place.get("eloc") or None,
        "provider_type": raw_place.get("type") or None,
        "fetched_at": datetime.now(timezone.utc),
        "search_radius_m": radius_m,
    }


def _dedupe_places(places: list) -> list:
    """De-duplicates a list of normalized facility dicts (already all
    the same category) using stable provider identity (Mappls eLoc)
    first, falling back to normalized-name-only when eLoc is absent.
    Never merges two DIFFERENT businesses just because their names are
    similar - the fallback key is exact-match-after-normalization, not
    fuzzy matching, and is only reached when the provider gave us no
    stable identity to rely on at all."""

    seen = set()
    deduped = []

    for place in places:

        provider_id = place.get("provider_id")

        if provider_id:
            key = ("id", provider_id)
        else:
            key = ("name", _normalize_name_for_dedup(place.get("name")))

        if key in seen:
            continue

        seen.add(key)
        deduped.append(place)

    return deduped


def _resolve_coordinates_for_place(place: dict, osm_service) -> None:
    """Best-effort: mutates `place` in place, setting latitude/longitude/
    coordinates/coordinate_source if the existing Phase 1 OSM chain can
    resolve them. Leaves the place completely unchanged (still valid,
    still carrying its Mappls-provided distance_m) on ANY non-matched
    OSM status - ambiguous/no_match/rejected/error are all treated the
    same way here: no coordinates, no exception, no retry. This mirrors
    services/search_orchestration.py's resolve_poi_location() use of
    the exact same underlying resolve_coordinates() call."""

    if osm_service is None:
        return

    try:

        osm_result = osm_service.resolve_coordinates({
            "place_name": place["name"],
            "address": place.get("address") or "",
        })

    except Exception:
        # resolve_coordinates() is documented never to raise, but this
        # module's own "never raises" guarantee must hold even if that
        # contract is ever violated by a future change there.
        return

    if not isinstance(osm_result, dict) or osm_result.get("status") != "matched":
        return

    latitude = osm_result.get("latitude")
    longitude = osm_result.get("longitude")

    if not _is_valid_coordinate(latitude, longitude):
        return

    place["latitude"] = float(latitude)
    place["longitude"] = float(longitude)
    place["coordinates"] = {
        "type": "Point",
        "coordinates": [float(longitude), float(latitude)],
    }
    place["coordinate_source"] = "osm"


# ============================================================
# PER-CATEGORY DISCOVERY
# ============================================================

def _discover_category(
    category: str,
    keyword: str,
    ref_location: str,
    radius_m: float,
    mappls_api_key,
    osm_service,
    max_results: int,
    coordinate_resolution_limit: int,
) -> tuple:
    """Returns (places, error). `error` is a short human-readable
    string if the Mappls call for THIS category failed outright (never
    raises); `places` is always a list (possibly empty)."""

    mappls_result = mappls_service.find_nearby_places(
        keyword, ref_location, radius_m, mappls_api_key
    )

    if mappls_result["status"] == "error":
        return [], mappls_result.get("error") or "Mappls nearby search failed."

    if mappls_result["status"] == "no_match":
        return [], None

    normalized = [
        _normalize_place(raw, category, radius_m)
        for raw in mappls_result["places"]
    ]
    normalized = [p for p in normalized if p is not None]

    deduped = _dedupe_places(normalized)

    # Mappls already returns results ordered by its own relevance/
    # distance ranking (see orderIndex in the raw response) - sorting
    # again by the provider distance we trust keeps this deterministic
    # even if that assumption ever changes.
    deduped.sort(key=lambda p: (p["distance_m"] is None, p["distance_m"] or 0))

    kept = deduped[:max_results]

    for place in kept[:coordinate_resolution_limit]:
        _resolve_coordinates_for_place(place, osm_service)

    return kept, None


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def enrich_property_nearby_facilities(
    property_id,
    property_service,
    mappls_api_key,
    osm_service,
    categories: Optional[dict] = None,
    radius_km: Optional[float] = None,
    max_results_per_category: Optional[int] = None,
    coordinate_resolution_limit_per_category: Optional[int] = None,
) -> dict:
    """
    Enriches ONE property with nearby-facility data and persists it via
    the existing PropertyService.update_property() - no new MongoDB
    access pattern. Reusable: this same function is meant to be called
    both right after a property is created (routes/property_routes.py)
    and, later, by a standalone backfill/refresh script/job (see
    docs/PHASE_4_0_NEARBY_FACILITY_ENRICHMENT.md) - it does not assume
    anything about WHEN or WHY it's being called.

    categories: {category_key: mappls_keyword, ...} - defaults to
      FACILITY_CATEGORIES (all of them). A caller may pass a subset for
      a partial re-enrichment.

    Never raises. Returns the same metadata dict that gets stored as
    the property's "nearby_facilities_metadata" field, so a caller can
    inspect what happened without a second read.

    Enrichment is skipped (status="skipped") - NOT attempted, NOT
    marked "failed" - when the property doesn't exist or has no valid
    coordinates yet. That distinction matters: "failed" implies an
    external system let us down; "skipped" means there was nothing
    valid to enrich from in the first place.
    """

    categories = categories or FACILITY_CATEGORIES
    radius_km = radius_km if radius_km is not None else DEFAULT_RADIUS_KM
    max_results_per_category = (
        max_results_per_category
        if max_results_per_category is not None
        else DEFAULT_MAX_RESULTS_PER_CATEGORY
    )
    coordinate_resolution_limit_per_category = (
        coordinate_resolution_limit_per_category
        if coordinate_resolution_limit_per_category is not None
        else DEFAULT_COORDINATE_RESOLUTION_LIMIT_PER_CATEGORY
    )

    radius_m = radius_km * 1000.0

    metadata = {
        "status": "failed",
        "source": "mappls",
        "radius_m": radius_m,
        "enriched_at": datetime.now(timezone.utc),
        "facility_count": 0,
        "categories_requested": sorted(categories.keys()),
        "categories_failed": {},
        "error": None,
    }

    try:
        property_document = property_service.get_property(property_id)
    except Exception as exc:
        metadata["error"] = f"Could not load property: {exc}"
        return metadata

    if not property_document:
        metadata["status"] = "skipped"
        metadata["error"] = "Property not found."
        return metadata

    location = property_document.get("location") or {}
    coordinates_field = location.get("coordinates") or {}
    coordinate_values = coordinates_field.get("coordinates") or []

    if len(coordinate_values) != 2:
        metadata["status"] = "skipped"
        metadata["error"] = "Property has no coordinates to enrich from."
        return metadata

    longitude, latitude = coordinate_values[0], coordinate_values[1]

    if not _is_valid_coordinate(latitude, longitude):
        metadata["status"] = "skipped"
        metadata["error"] = "Property coordinates are invalid."
        return metadata

    ref_location = f"{latitude},{longitude}"

    all_facilities = []
    categories_failed = {}

    for category, keyword in categories.items():

        places, error = _discover_category(
            category,
            keyword,
            ref_location,
            radius_m,
            mappls_api_key,
            osm_service,
            max_results_per_category,
            coordinate_resolution_limit_per_category,
        )

        all_facilities.extend(places)

        if error:
            categories_failed[category] = error

    metadata["facility_count"] = len(all_facilities)
    metadata["categories_failed"] = categories_failed

    if not categories_failed:
        metadata["status"] = "completed"
    elif len(categories_failed) < len(categories):
        metadata["status"] = "partial"
    else:
        metadata["status"] = "failed"
        metadata["error"] = "All facility categories failed to resolve."

    try:

        property_service.update_property(property_id, {
            "nearby_facilities": all_facilities,
            "nearby_facilities_metadata": metadata,
        })

    except Exception as exc:
        # The discovery work itself succeeded but persisting it failed
        # (e.g. a transient Mongo error) - report that honestly rather
        # than claiming "completed" when nothing was actually saved.
        metadata["status"] = "failed"
        metadata["error"] = f"Enrichment data could not be saved: {exc}"

    return metadata
