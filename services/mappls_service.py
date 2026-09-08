"""
Mappls Text Search - production entity resolver.

Turns a free-text query ("VIT Chennai") into the single Mappls-resolved
POI candidate {placeName, placeAddress, eLoc, type} that the rest of the
location pipeline treats as authoritative. See
services/osm_location_service.py for what happens downstream.

Mappls remains the sole authority for WHICH real-world entity a query
means - this module never re-ranks or second-guesses Mappls' own top
candidate. If Mappls' resolution is itself wrong for an ambiguous query,
that is a Mappls-side limitation to address separately (better location
bias, etc.), not something this module or the downstream OSM resolver
should try to silently correct.

Never raises for an expected failure (missing key, bad response, Mappls
being down); every path returns the same shape so callers never need a
try/except, matching services/geospatial_service.py's convention.
"""

import requests


MAPPLS_TEXT_SEARCH_URL = "https://search.mappls.com/search/places/textsearch/json"

REQUEST_TIMEOUT_SECONDS = 8


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
