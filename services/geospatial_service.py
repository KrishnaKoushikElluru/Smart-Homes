"""
GeoSpatial Phase 2 - nearby point-of-interest (POI) discovery.

Turns a property's stored coordinates into normalized, distance-sorted
lists of nearby places across the 42-category SmartHomes POI taxonomy,
using the Geoapify Places API. Every public function returns plain
data, never raises for an expected failure (missing key, bad
coordinates, Geoapify being down, rate limiting, garbage responses),
so a POI lookup can never take the property detail / listing pages
down with it.

QUERY STRATEGY
--------------
Geoapify's /v2/places lets a single request match several category
codes at once (comma-separated, OR semantics), and every returned
feature carries a `properties.categories` array listing every code it
actually matched (leaf codes and their parents, plus unrelated tags
like "vegan"/"halal" for catering places). That means one request per
*semantic group* (see POI_CATEGORY_GROUPS) is enough to cover every
leaf category inside it - we classify each returned feature back into
the specific SmartHomes leaf categor(y/ies) it belongs to by
intersecting its own `categories` array against the codes we own for
that group, rather than guessing from request order. This was
verified against the live API before relying on it (see the Phase 2
extension report). A feature matching more than one leaf in a group
(e.g. a fuel station that also does EV charging) is legitimately
included in every leaf it matches - that is Geoapify's own tagging,
not an arbitrary choice on our part.

This module intentionally does NOT persist POI results anywhere - POIs
are external, time-sensitive data that should be (re)fetched through
this service rather than cached inside a property document.
"""

import math

import requests


GEOAPIFY_PLACES_URL = "https://api.geoapify.com/v2/places"

REQUEST_TIMEOUT_SECONDS = 8

EARTH_RADIUS_KM = 6371.0088

# Upper bound on how many raw features we ask Geoapify for in a single
# grouped request, regardless of how many leaf categories share it.
# Keeps a single HTTP call bounded even if max_results is overridden
# high, while still comfortably covering "max_results per leaf" for
# every group at the default configuration (biggest groups have 5
# leaves x 10 = 50).
MAX_GROUP_FETCH_LIMIT = 100


# ============================================================
# POI TAXONOMY
#
# Single source of truth mapping every SmartHomes semantic category
# to the Geoapify Places category code(s) that satisfy it, and to the
# semantic group it belongs to. Add a new category in both dicts
# below - no route/template changes required.
# ============================================================

POI_CATEGORY_GROUPS = {
    "food": ["restaurants", "cafes", "fast_food", "food_courts"],
    "shopping": ["supermarkets", "convenience_stores", "shopping_malls"],
    "healthcare": ["hospitals", "clinics", "dentists", "pharmacies"],
    "education": ["universities", "colleges", "schools", "libraries"],
    "parks_leisure": ["parks", "playgrounds", "gardens"],
    "fitness_sports": [
        "gyms",
        "fitness_centres",
        "sports_centres",
        "stadiums",
        "swimming_pools",
    ],
    "entertainment": ["cinemas", "theatres", "museums"],
    "transport": ["bus", "train", "subway", "tram", "taxi"],
    "financial_essential": [
        "banks",
        "atms",
        "police",
        "fire_stations",
        "post_offices",
    ],
    "vehicle_services": ["fuel_stations", "ev_charging", "car_wash"],
    "accommodation": ["hotels", "hostels", "apartments"],
}

POI_CATEGORIES = {
    # food
    "restaurants": ["catering.restaurant"],
    "cafes": ["catering.cafe"],
    "fast_food": ["catering.fast_food"],
    "food_courts": ["catering.food_court"],
    # shopping
    "supermarkets": ["commercial.supermarket"],
    "convenience_stores": ["commercial.convenience"],
    "shopping_malls": ["commercial.shopping_mall"],
    # healthcare
    "hospitals": ["healthcare.hospital"],
    "clinics": ["healthcare.clinic_or_praxis"],
    "dentists": ["healthcare.dentist"],
    "pharmacies": ["commercial.health_and_beauty.pharmacy"],
    # education
    "universities": ["education.university"],
    "colleges": ["education.college"],
    "schools": ["education.school"],
    "libraries": ["education.library"],
    # parks / leisure
    "parks": ["leisure.park"],
    "playgrounds": ["leisure.playground"],
    "gardens": ["leisure.park.garden"],
    # fitness / sports
    "gyms": ["sport.fitness.gym"],
    "fitness_centres": ["sport.fitness.fitness_centre"],
    "sports_centres": ["sport.sports_centre"],
    "stadiums": ["sport.stadium"],
    "swimming_pools": ["sport.swimming_pool"],
    # entertainment
    "cinemas": ["entertainment.cinema"],
    "theatres": ["entertainment.culture.theatre"],
    "museums": ["entertainment.museum"],
    # transport
    "bus": ["public_transport.bus"],
    "train": ["public_transport.train"],
    "subway": ["public_transport.subway"],
    "tram": ["public_transport.tram"],
    "taxi": ["service.taxi"],
    # financial / essential services
    "banks": ["service.financial.bank"],
    "atms": ["service.financial.atm"],
    "police": ["service.police"],
    "fire_stations": ["service.fire_station"],
    "post_offices": ["service.post.office"],
    # vehicle services
    "fuel_stations": ["service.vehicle.fuel"],
    "ev_charging": ["service.vehicle.charging_station"],
    "car_wash": ["service.vehicle.car_wash"],
    # accommodation
    "hotels": ["accommodation.hotel"],
    "hostels": ["accommodation.hostel"],
    "apartments": ["accommodation.apartment"],
}

CATEGORY_TO_GROUP = {
    category: group
    for group, categories in POI_CATEGORY_GROUPS.items()
    for category in categories
}

# ------------------------------------------------------------
# Backward compatibility.
#
# Before the full 42-category taxonomy, this service exposed 6
# broader categories. "schools", "restaurants" and "parks" are
# unchanged 1:1 leaf categories, so they keep working automatically.
# "shopping" and "public_transport" were coarser than any single leaf
# below (they covered several of the new categories at once) and no
# longer exist as leaves - they're now semantic groups - so they are
# kept as derived aliases: the union of their member leaves, re-sorted
# and re-truncated, computed for free from data already fetched (no
# extra Geoapify requests).
#
# "hospitals" is NOT aliased: it remains a real leaf category, just
# narrower than before (it used to silently include clinics). See the
# Phase 2 extension report for why that's an intentional accuracy fix
# rather than a compatibility gap.
# ------------------------------------------------------------

LEGACY_CATEGORY_ALIASES = {
    "shopping": ["supermarkets", "convenience_stores", "shopping_malls"],
    "public_transport": ["bus", "train", "subway", "tram"],
}


DEFAULT_RADIUS_METERS = 5000
DEFAULT_MAX_RESULTS_PER_CATEGORY = 10


# ============================================================
# DISTANCE
# ============================================================

def haversine_distance_km(lat1, lon1, lat2, lon2):
    """Great-circle distance between two lat/lon points, in kilometres."""

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )

    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_KM * c


def _is_valid_coordinate(latitude, longitude):

    try:
        latitude = float(latitude)
        longitude = float(longitude)

    except (TypeError, ValueError):
        return False

    return -90 <= latitude <= 90 and -180 <= longitude <= 180


# ============================================================
# NORMALIZATION
# ============================================================

def _normalize_feature(
    feature,
    category,
    category_group,
    origin_lat,
    origin_lon,
    source_categories=None
):
    """Convert one raw Geoapify feature into our internal POI shape."""

    properties = feature.get("properties") or {}

    try:
        lat = float(properties.get("lat"))
        lon = float(properties.get("lon"))

    except (TypeError, ValueError):
        return None

    if source_categories is None:
        source_categories = properties.get("categories")

    if not isinstance(source_categories, list):
        source_categories = []

    return {
        "name": properties.get("name") or "Unnamed",
        "category": category,
        "category_group": category_group,
        "latitude": lat,
        "longitude": lon,
        "distance_km": round(
            haversine_distance_km(origin_lat, origin_lon, lat, lon),
            3
        ),
        "address": (
            properties.get("formatted")
            or properties.get("address_line1")
            or "Address unavailable"
        ),
        "city": properties.get("city"),
        "state": properties.get("state"),
        "postcode": properties.get("postcode"),
        "place_id": properties.get("place_id"),
        "source_categories": source_categories,
    }


# ============================================================
# GEOAPIFY REQUEST (one semantic group -> many leaf categories)
# ============================================================

def _fetch_group(
    latitude,
    longitude,
    api_key,
    group,
    leaf_categories,
    radius_m,
    max_results
):
    """
    Fetch POIs for every leaf category in `leaf_categories` (all
    belonging to semantic group `group`) using a single Geoapify
    request, then classify each returned feature back into the
    individual leaf categories it actually matches.

    Returns (buckets, error) where buckets is
    {leaf_category: [poi, ...]}. `error`, if any, applies to every
    leaf in this group (the whole group request failed together);
    this function never raises.
    """

    leaf_code_sets = {
        leaf: set(POI_CATEGORIES[leaf])
        for leaf in leaf_categories
    }

    combined_codes = sorted({
        code
        for codes in leaf_code_sets.values()
        for code in codes
    })

    buckets = {leaf: [] for leaf in leaf_categories}

    fetch_limit = min(
        max_results * max(len(leaf_categories), 1),
        MAX_GROUP_FETCH_LIMIT
    )

    params = {
        "categories": ",".join(combined_codes),
        "filter": f"circle:{longitude},{latitude},{radius_m}",
        "bias": f"proximity:{longitude},{latitude}",
        "limit": fetch_limit,
        "apiKey": api_key,
    }

    try:

        response = requests.get(
            GEOAPIFY_PLACES_URL,
            params=params,
            timeout=REQUEST_TIMEOUT_SECONDS
        )

    except requests.RequestException:
        return buckets, "Location search request failed or timed out."

    if response.status_code == 429:
        return buckets, "Location data is temporarily rate-limited."

    if response.status_code != 200:
        return buckets, f"Location search failed (HTTP {response.status_code})."

    try:
        data = response.json()

    except ValueError:
        return buckets, "Location search returned an unreadable response."

    if not isinstance(data, dict):
        return buckets, "Location search returned an unexpected response."

    features = data.get("features")

    if not isinstance(features, list):
        return buckets, "Location search returned an unexpected response."

    for feature in features:

        if not isinstance(feature, dict):
            continue

        properties = feature.get("properties") or {}
        source_categories = properties.get("categories")

        if not isinstance(source_categories, list):
            source_categories = []

        matched_codes = set(source_categories)

        matched_leaves = [
            leaf
            for leaf in leaf_categories
            if leaf_code_sets[leaf] & matched_codes
        ]

        # Geoapify matched the combined OR-query but this particular
        # feature's own categories don't confirm any of our specific
        # leaves (e.g. only a broader parent category came through) -
        # skip rather than guess which leaf it belongs to.
        if not matched_leaves:
            continue

        for leaf in matched_leaves:

            normalized = _normalize_feature(
                feature,
                leaf,
                group,
                latitude,
                longitude,
                source_categories
            )

            if normalized is not None:
                buckets[leaf].append(normalized)

    for leaf in leaf_categories:
        buckets[leaf].sort(key=lambda poi: poi["distance_km"])
        buckets[leaf] = buckets[leaf][:max_results]

    return buckets, None


# ============================================================
# PUBLIC API
# ============================================================

def get_nearby_pois(
    latitude,
    longitude,
    api_key,
    categories=None,
    radius_m=None,
    max_results=None
):
    """
    Discover POIs near (latitude, longitude) across every SmartHomes
    category (or a caller-supplied subset), grouped by category and
    sorted nearest-first within each category.

    Never raises. On any failure (missing key, invalid coordinates,
    Geoapify errors) this returns the same shape with empty category
    lists and `error` / `category_errors` explaining what happened, so
    callers never need to wrap this in a try/except. A failure in one
    semantic group's request never affects the others.

    `categories` optionally overrides POI_CATEGORIES (e.g. to look up
    a handful of leaf categories) - defaults to all 42.
    """

    radius_m = radius_m or DEFAULT_RADIUS_METERS
    max_results = max_results or DEFAULT_MAX_RESULTS_PER_CATEGORY
    categories = categories or POI_CATEGORIES

    result = {
        "coordinates": {"latitude": None, "longitude": None},
        "radius_m": radius_m,
        "max_results_per_category": max_results,
        "categories": {key: [] for key in categories},
        "error": None,
        "category_errors": {},
    }

    if not api_key:
        result["error"] = "Location intelligence is not configured."
        return result

    if not _is_valid_coordinate(latitude, longitude):
        result["error"] = "Invalid property coordinates."
        return result

    latitude = float(latitude)
    longitude = float(longitude)

    result["coordinates"] = {"latitude": latitude, "longitude": longitude}

    # Bucket the requested leaf categories by their semantic group so
    # each group reaches Geoapify as a single request.
    leaves_by_group = {}

    for leaf in categories:

        group = CATEGORY_TO_GROUP.get(leaf, leaf)
        leaves_by_group.setdefault(group, []).append(leaf)

    for group, leaf_categories in leaves_by_group.items():

        buckets, error = _fetch_group(
            latitude,
            longitude,
            api_key,
            group,
            leaf_categories,
            radius_m,
            max_results
        )

        for leaf in leaf_categories:
            result["categories"][leaf] = buckets.get(leaf, [])

        if error:

            for leaf in leaf_categories:
                result["category_errors"][leaf] = error

    for legacy_key, member_leaves in LEGACY_CATEGORY_ALIASES.items():

        merged = []

        for member in member_leaves:
            merged.extend(result["categories"].get(member, []))

        merged.sort(key=lambda poi: poi["distance_km"])

        result["categories"][legacy_key] = merged[:max_results]

    return result
