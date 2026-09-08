from flask import (
    Blueprint,
    request,
    jsonify,
    current_app
)

from flask_login import login_required

from services.nlp.parser import parse as parse_nlp_query


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
    # RANKED MONGODB SEARCH
    # ========================================================

    property_service = (
        get_property_service()
    )


    properties = (
        property_service.ranked_search(
            preferences
        )
    )


    # ========================================================
    # SERIALIZE RESULTS
    # ========================================================

    results = []


    for property_item in properties:

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


        # ====================================================
        # COORDINATES
        # ====================================================

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


        # ====================================================
        # IMAGES
        # ====================================================

        images = media.get(
            "images",
            []
        )


        image_filename = (

            images[0]

            if images

            else None
        )


        # ====================================================
        # RESULT
        # ====================================================

        results.append({

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
        })


    # ========================================================
    # RESPONSE
    # ========================================================

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