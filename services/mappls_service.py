"""
Mappls Text Search / Nearby Search - production entity resolver +
nearby-place discovery.

resolve_place() turns a free-text query ("VIT Chennai") into the single
Mappls-resolved POI candidate {placeName, placeAddress, eLoc, type} that
the rest of the location pipeline treats as authoritative. See
services/osm_location_service.py for what happens downstream.

find_nearby_places() (Phase 4.0) is a second, independent Mappls
capability - "what's near this coordinate" rather than "what entity
does this text mean" - added here rather than as a separate module/
client so this file remains the single Mappls integration point (same
static-key `access_token` auth, same request/error conventions). It
does NOT call or depend on resolve_place() and vice versa.

Mappls remains the sole authority for WHICH real-world entity a query
means - this module never re-ranks or second-guesses Mappls' own top
candidate. If Mappls' resolution is itself wrong for an ambiguous query,
that is a Mappls-side limitation to address separately (better location
bias, etc.), not something this module or the downstream OSM resolver
should try to silently correct.

IMPORTANT (verified live against this account, Sep 2026 - see
mappls_geo_test/ for the original capability investigation): NEITHER
Mappls endpoint in this file returns usable latitude/longitude for a
result. Getting actual coordinates for a Mappls-identified place still
requires the existing Phase 1 OSM resolution chain
(services/osm_location_service.py) - this file never invents or derives
coordinates itself.

Never raises for an expected failure (missing key, bad response, Mappls
being down); every path returns the same shape so callers never need a
try/except, matching services/geospatial_service.py's convention.
"""

import requests


MAPPLS_TEXT_SEARCH_URL = "https://search.mappls.com/search/places/textsearch/json"

MAPPLS_NEARBY_URL = "https://search.mappls.com/search/places/nearby/json"

REQUEST_TIMEOUT_SECONDS = 8

# Mappls documents this as the server-side clamp for the Nearby API's
# `radius` parameter - not enforced client-side here, just documented so
# a caller passing something outside this range isn't surprised by
# Mappls silently clamping it.
NEARBY_MIN_RADIUS_METERS = 500
NEARBY_MAX_RADIUS_METERS = 10000


def resolve_place(query, api_key, location_bias=None):
    """
    query: free-text search string.
    api_key: Mappls REST API key (access_token).
    location_bias: optional "lat,lon" string to bias results toward a
      region, matching Mappls' own `location` query parameter.

    Returns:
        {
            "status": "matched" | "no_match" | "error",
            "place_name": str | None,
            "place_address": str | None,
            "eloc": str | None,
            "type": str | None,
            "error": str | None,
        }
    """

    result = {
        "status": "error",
        "place_name": None,
        "place_address": None,
        "eloc": None,
        "type": None,
        "error": None,
    }

    query = (query or "").strip()

    if not query:
        result["error"] = "Empty query."
        return result

    if not api_key:
        result["error"] = "Mappls is not configured."
        return result

    params = {
        "query": query,
        "access_token": api_key,
    }

    if location_bias:
        params["location"] = location_bias

    try:

        response = requests.get(
            MAPPLS_TEXT_SEARCH_URL,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    except requests.RequestException:
        result["error"] = "Mappls request failed or timed out."
        return result

    if response.status_code == 204:
        result["status"] = "no_match"
        return result

    if response.status_code != 200:
        result["error"] = f"Mappls search failed (HTTP {response.status_code})."
        return result

    try:
        data = response.json()

    except ValueError:
        result["error"] = "Mappls returned an unreadable response."
        return result

    candidates = data.get("suggestedLocations")

    if not isinstance(candidates, list) or not candidates:
        result["status"] = "no_match"
        return result

    # Mappls' own top-ranked candidate is the entity we trust - this
    # module does not re-rank Mappls' output.
    top = candidates[0]

    result["status"] = "matched"
    result["place_name"] = top.get("placeName")
    result["place_address"] = top.get("placeAddress")
    result["eloc"] = top.get("eLoc")
    result["type"] = top.get("type")

    return result


def find_nearby_places(keywords, ref_location, radius_m, api_key):
    """
    Discover places near a coordinate via Mappls' Nearby Search API
    (Phase 4.0 - nearby-facility enrichment).

    keywords: free-text search term (e.g. "gym", "hospital", "school") -
      passed straight through as Mappls' own `keywords` parameter. This
      is a category-to-search-term mapping the caller controls (see
      services/nearby_facility_service.py's FACILITY_CATEGORIES), not a
      business-name alias table.
    ref_location: "lat,lon" string - the coordinate to search around.
    radius_m: search radius in meters. Mappls clamps this server-side to
      [NEARBY_MIN_RADIUS_METERS, NEARBY_MAX_RADIUS_METERS] - not
      re-validated here.
    api_key: Mappls REST API key (access_token).

    Returns:
        {
            "status": "matched" | "no_match" | "error",
            "places": [
                {
                    "place_name": str | None,
                    "place_address": str | None,
                    "eloc": str | None,
                    "type": str | None,
                    "distance_m": float | None,  # Mappls' own
                        provider-computed distance from ref_location -
                        NOT derived from any coordinates this module
                        has (it has none - see module docstring).
                    "order_index": int | None,
                },
                ...
            ],
            "error": str | None,
        }

    Never raises - same convention as resolve_place() above.
    """

    result = {
        "status": "error",
        "places": [],
        "error": None,
    }

    keywords = (keywords or "").strip()

    if not keywords:
        result["error"] = "Empty keywords."
        return result

    if not ref_location:
        result["error"] = "A reference location is required."
        return result

    if not api_key:
        result["error"] = "Mappls is not configured."
        return result

    try:
        # Mappls' Nearby API rejects a decimal radius outright (HTTP 400
        # Bad Request) - confirmed live against this account. Callers
        # (e.g. services/nearby_facility_service.py, computing
        # radius_km * 1000.0) naturally produce a float; this is the one
        # place that talks to the actual HTTP API, so it's the right
        # place to guarantee a clean integer regardless of what a caller
        # passed in.
        radius_param = int(round(float(radius_m)))
    except (TypeError, ValueError):
        result["error"] = "Invalid radius."
        return result

    params = {
        "keywords": keywords,
        "refLocation": ref_location,
        "radius": radius_param,
        "access_token": api_key,
    }

    try:

        response = requests.get(
            MAPPLS_NEARBY_URL,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )

    except requests.RequestException:
        result["error"] = "Mappls request failed or timed out."
        return result

    if response.status_code == 204:
        result["status"] = "no_match"
        return result

    if response.status_code != 200:
        result["error"] = f"Mappls nearby search failed (HTTP {response.status_code})."
        return result

    try:
        data = response.json()

    except ValueError:
        result["error"] = "Mappls returned an unreadable response."
        return result

    candidates = data.get("suggestedLocations")

    if not isinstance(candidates, list) or not candidates:
        result["status"] = "no_match"
        return result

    places = []

    for candidate in candidates:

        if not isinstance(candidate, dict):
            continue

        places.append({
            "place_name": candidate.get("placeName"),
            "place_address": candidate.get("placeAddress"),
            "eloc": candidate.get("eLoc"),
            "type": candidate.get("type"),
            "distance_m": candidate.get("distance"),
            "order_index": candidate.get("orderIndex"),
        })

    if not places:
        result["status"] = "no_match"
        return result

    result["status"] = "matched"
    result["places"] = places

    return result
