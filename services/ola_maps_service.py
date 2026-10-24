"""
Ola Maps Places API integration - PRIMARY location-discovery provider
(see docs/PHASE_5_OLA_MAPS_LOCATION_PROVIDER.md for the full
architecture this is part of).

Live-verified against the actual configured OLA_MAPS_API_KEY (Sep 2026)
before this module was written - see that investigation for the raw
endpoint/field discovery this implementation is based on. Three
operations only, matching what the rest of the app actually needs:

  autocomplete()      "as the user types" candidate discovery. Returns
                       MULTIPLE candidates (never auto-selects one) -
                       many of Ola's own predictions already include
                       coordinates directly (geometry.location), but a
                       caller must not assume that and should always
                       resolve the SELECTED candidate via
                       get_place_details() before treating its
                       coordinates as authoritative (matches this
                       phase's explicit "Ola Autocomplete -> user
                       selects -> Ola Place Details -> lat/lng" flow).

  get_place_details()  place_id -> authoritative coordinates + a
                       structured address breakdown (city/state/
                       locality/postcode), for after a user has picked
                       one specific candidate.

  reverse_geocode()    coordinates -> address fields, for the manual
                       Leaflet map click/drag fallback (replaces
                       Geoapify's reverse-geocode for that one purpose
                       - see routes/property_routes.py's
                       location_reverse()).

Deliberately NOT implemented: bare forward geocoding as a primary
discovery path. Live testing (see the investigation this phase is
built on) showed Ola's plain /geocode endpoint falls back hard to
postal-code-centroid guesses for ambiguous/local names ("Mambakkam,
Chennai" resolved to postal codes 8-32 km away; "SRM University,
Chennai" resolved up to 1688 km away) - autocomplete-then-details is
the reliable path, geocode is not used here at all.

Never raises for an expected failure (missing key, bad response, Ola
being down); every function returns the same predictable shape so
callers never need a try/except - matching services/mappls_service.py's
and services/osm_location_service.py's established convention exactly.
This module NEVER invents/guesses a coordinate - a field that Ola
didn't return comes back as None, never a fabricated value.
"""

import requests


OLA_AUTOCOMPLETE_URL = "https://api.olamaps.io/places/v1/autocomplete"
OLA_PLACE_DETAILS_URL = "https://api.olamaps.io/places/v1/details"
OLA_REVERSE_GEOCODE_URL = "https://api.olamaps.io/places/v1/reverse-geocode"

REQUEST_TIMEOUT_SECONDS = 8

DEFAULT_AUTOCOMPLETE_LIMIT = 6


def _get(url, params, api_key):
    """Shared GET helper - Ola's auth is a bare `api_key` query param on
    every endpoint (confirmed live, not guessed - see this module's
    docstring). Returns (response_or_none, error_message_or_none)."""

    request_params = dict(params)
    request_params["api_key"] = api_key

    try:
        response = requests.get(url, params=request_params, timeout=REQUEST_TIMEOUT_SECONDS)
    except requests.RequestException:
        return None, "Ola Maps request failed or timed out."

    if response.status_code != 200:
        return None, f"Ola Maps request failed (HTTP {response.status_code})."

    try:
        return response.json(), None
    except ValueError:
        return None, "Ola Maps returned an unreadable response."


def autocomplete(query, api_key, location_bias=None, limit=DEFAULT_AUTOCOMPLETE_LIMIT):
    """
    query: free-text search string, as typed by the user.
    api_key: Ola Maps REST API key.
    location_bias: optional "lat,lon" string (Ola's own `location` query
      param) - live-verified to actually change ranking, not a no-op.

    Returns:
        {
            "status": "matched" | "no_match" | "error",
            "candidates": [
                {
                    "provider": "ola",
                    "place_id": str,
                    "name": str,           # main display name
                    "address": str,        # full descriptive address
                    "latitude": float | None,
                    "longitude": float | None,
                    "types": list,
                },
                ...
            ],
            "error": str | None,
        }

    Never auto-selects a candidate - this is a discovery-only function,
    exactly like services/mappls_service.py's find_nearby_places().
    """

    result = {"status": "error", "candidates": [], "error": None}

    query = (query or "").strip()

    if not query:
        result["error"] = "Empty query."
        return result

    if not api_key:
        result["error"] = "Ola Maps is not configured."
        return result

    params = {"input": query}
    if location_bias:
        params["location"] = location_bias

    data, error = _get(OLA_AUTOCOMPLETE_URL, params, api_key)

    if error:
        result["error"] = error
        return result

    predictions = data.get("predictions") if isinstance(data, dict) else None

    if not isinstance(predictions, list) or not predictions:
        result["status"] = "no_match"
        return result

    candidates = []

    for item in predictions[:limit]:

        if not isinstance(item, dict):
            continue

        place_id = item.get("place_id")

        if not place_id:
            # A candidate with no place_id can never be resolved to
            # coordinates later (get_place_details() needs it) - skip
            # rather than return something a caller could select but
            # never finish resolving.
            continue

        structured = item.get("structured_formatting") or {}
        location = (item.get("geometry") or {}).get("location") or {}
        latitude = location.get("lat")
        longitude = location.get("lng")

        candidates.append({
            "provider": "ola",
            "place_id": place_id,
            "name": structured.get("main_text") or item.get("description"),
            "address": item.get("description"),
            "latitude": float(latitude) if latitude is not None else None,
            "longitude": float(longitude) if longitude is not None else None,
            "types": item.get("types") or [],
        })

    if not candidates:
        result["status"] = "no_match"
        return result

    result["status"] = "matched"
    result["candidates"] = candidates
    return result


# Ola's Place Details address_components "types" -> our internal field
# names. Ordered by preference within each internal field (first type
# found wins) - generic Google-Places-style type vocabulary, not
# Ola-specific guessing (confirmed against real live responses).
_CITY_TYPES = ("locality", "administrative_area_level_2")
_STATE_TYPES = ("administrative_area_level_1",)
_LOCALITY_TYPES = ("sublocality", "postal_town", "neighborhood")
_SUB_LOCALITY_TYPES = ("neighborhood", "sublocality_level_2")
_POSTCODE_TYPES = ("postal_code",)


def _component(components, type_names):
    for component in components or []:
        if not isinstance(component, dict):
            continue
        component_types = component.get("types") or []
        for type_name in type_names:
            if type_name in component_types:
                return component.get("long_name")
    return None


def get_place_details(place_id, api_key):
    """
    place_id: an Ola place_id, as returned by autocomplete() above.

    Returns:
        {
            "status": "matched" | "no_match" | "error",
            "name": str | None,
            "formatted_address": str | None,
            "latitude": float | None,
            "longitude": float | None,
            "place_id": str | None,
            "types": list,
            "city": str | None,
            "state": str | None,
            "locality": str | None,
            "sub_locality": str | None,
            "postcode": str | None,
            "error": str | None,
        }

    Never guesses a missing coordinate - "matched" with latitude/
    longitude both None cannot happen; a response with no usable
    geometry.location is treated as "no_match" instead.
    """

    result = {
        "status": "error",
        "name": None,
        "formatted_address": None,
        "latitude": None,
        "longitude": None,
        "place_id": None,
        "types": [],
        "city": None,
        "state": None,
        "locality": None,
        "sub_locality": None,
        "postcode": None,
        "error": None,
    }

    place_id = (place_id or "").strip()

    if not place_id:
        result["error"] = "Empty place_id."
        return result

    if not api_key:
        result["error"] = "Ola Maps is not configured."
        return result

    data, error = _get(OLA_PLACE_DETAILS_URL, {"place_id": place_id}, api_key)

    if error:
        result["error"] = error
        return result

    details = data.get("result") if isinstance(data, dict) else None

    if not isinstance(details, dict):
        result["status"] = "no_match"
        return result

    location = (details.get("geometry") or {}).get("location") or {}
    latitude = location.get("lat")
    longitude = location.get("lng")

    if latitude is None or longitude is None:
        # A Place Details response with a name/address but no usable
        # coordinate is not a safe "matched" result for this app's
        # purposes - the whole point of calling this endpoint is to get
        # a coordinate to put on the map.
        result["status"] = "no_match"
        result["error"] = "Ola Place Details returned no usable coordinates."
        return result

    components = details.get("address_components")

    result["status"] = "matched"
    result["name"] = details.get("name")
    result["formatted_address"] = details.get("formatted_address")
    result["latitude"] = float(latitude)
    result["longitude"] = float(longitude)
    result["place_id"] = details.get("place_id") or place_id
    result["types"] = details.get("types") or []
    result["city"] = _component(components, _CITY_TYPES)
    result["state"] = _component(components, _STATE_TYPES)
    result["locality"] = _component(components, _LOCALITY_TYPES)
    result["sub_locality"] = _component(components, _SUB_LOCALITY_TYPES)
    result["postcode"] = _component(components, _POSTCODE_TYPES)

    return result


def reverse_geocode(latitude, longitude, api_key):
    """
    latitude/longitude: a coordinate the user placed on the map
    (manual click or marker drag) - used ONLY to fill in address text
    fields for convenience, never to move the marker itself (the
    marker's coordinate is already authoritative the moment the user
    placed it).

    Returns:
        {
            "status": "matched" | "no_match" | "error",
            "formatted_address": str | None,
            "city": str | None,
            "state": str | None,
            "locality": str | None,
            "sub_locality": str | None,
            "postcode": str | None,
            "error": str | None,
        }
    """

    result = {
        "status": "error",
        "formatted_address": None,
        "city": None,
        "state": None,
        "locality": None,
        "sub_locality": None,
        "postcode": None,
        "error": None,
    }

    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        result["error"] = "Invalid coordinates."
        return result

    if not api_key:
        result["error"] = "Ola Maps is not configured."
        return result

    data, error = _get(
        OLA_REVERSE_GEOCODE_URL, {"latlng": f"{latitude},{longitude}"}, api_key
    )

    if error:
        result["error"] = error
        return result

    results = data.get("results") if isinstance(data, dict) else None

    if not isinstance(results, list) or not results:
        result["status"] = "no_match"
        return result

    top = results[0]

    if not isinstance(top, dict):
        result["status"] = "no_match"
        return result

    components = top.get("address_components")

    result["status"] = "matched"
    result["formatted_address"] = top.get("formatted_address")
    result["city"] = _component(components, _CITY_TYPES)
    result["state"] = _component(components, _STATE_TYPES)
    result["locality"] = _component(components, _LOCALITY_TYPES)
    result["sub_locality"] = _component(components, _SUB_LOCALITY_TYPES)
    result["postcode"] = _component(components, _POSTCODE_TYPES)

    return result
