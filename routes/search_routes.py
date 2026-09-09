from flask import (
    Blueprint,
    request,
    jsonify,
    current_app
)

from flask_login import login_required

from services.nlp.parser import parse as parse_nlp_query
from services import search_orchestration


search_bp = Blueprint(
    "search",
    __name__
)


# ============================================================
# PROPERTY SERVICE
# ============================================================

def get_property_service():

    return current_app.extensions[
        "property_service"
    ]


# ============================================================
# RESULT SERIALIZATION
#
# Extracted verbatim from the original inline loop (Phase 3) so both
# the existing ranked_search() path and the new natural-language
# search path (services/search_orchestration.py) share one
# serializer. No behavior change: filtered_search() results simply
# have no "_match_score" key, and .get("_match_score", 0) already
# handled that missing-key case before this extraction.
# ============================================================

def _serialize_property(property_item):

    listing = property_item.get(
        "listing",
        {}
    )


    property_data = property_item.get(
        "property",
        {}
    )


    location = property_item.get(
        "location",
        {}
    )


    description = property_item.get(
        "description",
        {}
    )


    contact = property_item.get(
        "contact",
        {}
    )


    media = property_item.get(
        "media",
        {}
    )


    source = property_item.get(
        "source",
        {}
    )


    # ============================================================
    # COORDINATES
    # ============================================================

    coordinates = location.get(
        "coordinates"
    )


    latitude = None

    longitude = None


    if coordinates:

        coordinate_values = (
            coordinates.get(
                "coordinates",
                []
            )
        )


        if len(
            coordinate_values
        ) == 2:

            longitude = (
                coordinate_values[0]
            )

            latitude = (
                coordinate_values[1]
            )


    # ============================================================
    # IMAGES
    # ============================================================

    images = media.get(
        "images",
        []
    )


    image_filename = (

        images[0]

        if images

        else None
    )


    # ============================================================
    # RESULT
    # ============================================================

    return {

        "id": str(
            property_item["_id"]
        ),

        "match_score":
            property_item.get(
                "_match_score",
                0
            ),

        "property_type":
            property_data.get(
                "type"
            ),

        "listing_type":
            listing.get(
                "type"
            ),

        "price":
            listing.get(
                "price"
            ),

        "bhk":
            property_data.get(
                "bhk"
            ),

        "area":
            property_data.get(
                "area_sqft"
            ),

        "description":
            description.get(
                "text"
            ),

        "contact_name":
            contact.get(
                "name"
            ),

        "contact_phone":
            contact.get(
                "phone"
            ),

        "address":
            location.get(
                "address"
            ),

        "city":
            location.get(
                "city"
            ),

        "locality":
            location.get(
                "locality"
            ),

        "latitude":
            latitude,

        "longitude":
            longitude,

        "amenities":
            property_item.get(
                "features",
                []
            ),

        "image_filename":
            image_filename,

        "images":
            images,

        "status":
            listing.get(
                "status"
            ),

        "source":
            source.get(
                "type"
            ),

        "source_url":
            source.get(
                "url"
            )
    }


# ============================================================
# SEARCH PROPERTIES
# ============================================================

@search_bp.route(
    "/search_rentals",
    methods=["POST"]
)
@login_required
def search_rentals():

    data = request.get_json()


    if not data:

        return jsonify({
            "error": "Invalid request."
        }), 400


    # ========================================================
    # BUDGET
    # ========================================================

    budget_value = data.get(
        "budget",
        0
    )


    try:

        budget = int(
            budget_value
        )


    except (
        TypeError,
        ValueError
    ):

        return jsonify({
            "error": "Budget must be a valid number."
        }), 400


    if budget < 0:

        return jsonify({
            "error": "Budget cannot be negative."
        }), 400


    # ========================================================
    # CITY
    # ========================================================

    city = data.get(
        "city",
        ""
    )


    if city:

        city = city.strip()


    # ========================================================
    # LOCALITY
    # ========================================================

    locality = data.get(
        "locality",
        ""
    )


    if locality:

        locality = locality.strip()


    # ========================================================
    # LISTING TYPE
    # ========================================================

    listing_type = data.get(
        "listing_type",
        ""
    )


    if listing_type:

        listing_type = (
            listing_type
            .strip()
            .lower()
        )


    # ========================================================
    # PROPERTY TYPE
    # ========================================================

    property_type = data.get(
        "property_type",
        ""
    )


    if property_type:

        property_type = (
            property_type
            .strip()
            .lower()
        )


    # ========================================================
    # BHK
    # ========================================================

    bhk_value = data.get(
        "bhk"
    )


    bhk = None


    if bhk_value not in [
        None,
        ""
    ]:

        try:

            bhk = int(
                bhk_value
            )


        except (
            TypeError,
            ValueError
        ):

            return jsonify({
                "error": "BHK must be a valid number."
            }), 400


        if bhk <= 0:

            return jsonify({
                "error": "BHK must be positive."
            }), 400


    # ========================================================
    # SEARCH PREFERENCES
    # ========================================================

    preferences = {

        "budget":
            budget,

        "city":
            city,

        "locality":
            locality,

        "listing_type":
            listing_type,

        "property_type":
            property_type,

        "bhk":
            bhk
    }


    # ========================================================
    # NATURAL-LANGUAGE QUERY (Phase 3 - optional, additive)
    #
    # A "query" field is entirely optional. When absent (every caller
    # before Phase 3, and any caller that keeps using only the
    # structured fields above), behavior below is byte-for-byte the
    # original ranked_search() path - see the else branch. Only when a
    # non-empty "query" is supplied does this route go through
    # services/search_orchestration.py's NLP + POI-resolution + real
    # MongoDB filter pipeline. Explicit structured fields already
    # parsed above (budget/city/locality/listing_type/property_type/
    # bhk) always take precedence over whatever the natural-language
    # query would have produced for that same field - see
    # search_orchestration.merge_structured_fields()'s docstring.
    # ========================================================

    query = (
        data.get("query") or ""
    ).strip()[:500]

    property_service = (
        get_property_service()
    )

    if query:

        osm_service = current_app.extensions.get(
            "osm_location_service"
        )

        mappls_key = current_app.config.get(
            "MAPPLS_API_KEY"
        )

        poi_radius_km = current_app.config.get(
            "SEARCH_POI_RADIUS_KM",
            search_orchestration.DEFAULT_POI_RADIUS_KM
        )

        location_bias = (
            data.get("location_bias") or ""
        ).strip() or None

        overrides = {
            "listing_type": listing_type,
            "property_type": property_type,
            "bhk": bhk,
            "budget": budget,
            "city": city,
            "locality": locality,
        }

        orchestration_result = search_orchestration.orchestrate_search(
            query,
            overrides,
            mappls_key,
            osm_service,
            property_service,
            poi_radius_km=poi_radius_km,
            location_bias=location_bias,
        )

        results = [
            _serialize_property(property_item)
            for property_item in orchestration_result["properties"]
        ]

        return jsonify({

            "properties":
                results,

            "parsed_query":
                orchestration_result["parsed_query"],

            "location_resolution":
                orchestration_result["location_resolution"],

            "applied_filters":
                orchestration_result["applied_filters"]

        })


    # ========================================================
    # RANKED MONGODB SEARCH (original structured-search path,
    # unchanged)
    # ========================================================

    properties = (
        property_service.ranked_search(
            preferences
        )
    )

    results = [
        _serialize_property(property_item)
        for property_item in properties
    ]

    return jsonify({

        "properties":
            results

    })


# ============================================================
# NLP QUERY PARSING (Phase 2 - standalone, testing only)
#
# Converts a natural-language search query into the structured
# representation defined in services/nlp/schema.py. Deliberately NOT
# connected to property retrieval yet - this endpoint exists so Phase 2
# can be exercised and verified independently before any later
# integration phase decides how (or whether) to feed its output into
# ranked_search()/Phase 1's POI resolver. Calling this endpoint never
# touches MongoDB, Mappls, or OSM - see services/nlp/parser.py's module
# docstring and test_nlp_parser.py's boundary tests.
# ============================================================

@search_bp.route(
    "/api/search/parse-query",
    methods=["POST"]
)
@login_required
def parse_query():

    data = request.get_json(silent=True) or {}

    query = (data.get("query") or "").strip()[:500]

    if not query:
        return jsonify({"error": "A 'query' field is required."}), 400

    structured = parse_nlp_query(query)

    return jsonify(structured.to_dict())