from urllib.parse import urlparse

import requests

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app,
    jsonify
)

from flask_login import (
    login_required,
    current_user
)

from services.property_fields import (
    PROPERTY_TYPE_VALUES,
    LISTING_TYPE_VALUES,
    RENT_ONLY_PROPERTY_TYPES,
    COMMON_LISTING_FIELDS,
    LOCATION_FIELDS,
    ROOMS_FIELDS,
    AREA_FIELDS,
    BUILDING_FIELDS,
    PROJECT_FIELDS,
    PARKING_FIELDS,
    EXTRA_FIELDS,
    LEGAL_FIELDS,
    PG_FIELDS,
    RENT_FIELDS,
    SALE_FIELDS,
    AMENITY_CATEGORIES,
    build_field_config,
    build_label_lookup,
    build_amenity_label_lookup
)

from services.property_validation import (
    parse_fields,
    parse_group_for_type,
    parse_latitude_longitude,
    parse_phone
)

from services import media_service
from services.media_service import (
    MediaValidationError,
    IMAGE_CATEGORIES
)

from services import geospatial_service
from services import mappls_service


property_bp = Blueprint(
    "property",
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
# PROFILE
# ============================================================

@property_bp.route(
    "/profile"
)
@login_required
def profile():

    property_service = (
        get_property_service()
    )

    properties = (
        property_service
        .get_properties_by_seller(
            current_user.id
        )
    )

    return render_template(
        "profile.html",
        user=current_user,
        listings=properties,
        field_labels=build_label_lookup(),
        amenity_labels=build_amenity_label_lookup()
    )


# ============================================================
# RENTALS / ACTIVE PROPERTIES + SUBMISSION FORM
# ============================================================

@property_bp.route(
    "/rentals",
    methods=["GET"]
)
@login_required
def rentals():

    property_service = (
        get_property_service()
    )

    properties = (
        property_service
        .get_active_properties()
    )

    return render_template(
        "rentals.html",
        listings=properties,
        field_config=build_field_config(),
        image_categories=IMAGE_CATEGORIES,
        geoapify_enabled=bool(
            current_app.config.get("GEOAPIFY_API_KEY")
        )
    )


# ============================================================
# VIEW PROPERTY DETAILS
# ============================================================

@property_bp.route(
    "/property/<property_id>",
    methods=["GET"]
)
@login_required
def property_details(property_id):

    property_service = (
        get_property_service()
    )

    property_item = (
        property_service.get_property(
            property_id
        )
    )

    if property_item is None:

        flash(
            "Property not found.",
            "danger"
        )

        return redirect(
            url_for(
                "property.rentals"
            )
        )

    return render_template(
        "property_details.html",
        property=property_item,
        field_labels=build_label_lookup(),
        amenity_labels=build_amenity_label_lookup()
    )


# ============================================================
# NEARBY POINTS OF INTEREST (GeoSpatial Phase 2)
#
# Read-only lookup: derives POIs on demand from a property's already
# -stored coordinates via services/geospatial_service.py. Nothing
# here is persisted on the property document - see that module's
# docstring for why.
# ============================================================

@property_bp.route(
    "/api/property/<property_id>/nearby-poi",
    methods=["GET"]
)
@login_required
def property_nearby_poi(property_id):

    property_service = get_property_service()

    property_item = property_service.get_property(property_id)

    if property_item is None:
        return jsonify({"error": "Property not found."}), 404

    location = property_item.get("location") or {}

    coordinates = (
        (location.get("coordinates") or {}).get("coordinates")
    )

    if not coordinates or len(coordinates) != 2:

        empty_categories = {
            key: [] for key in geospatial_service.POI_CATEGORIES
        }

        empty_categories.update({
            key: [] for key in geospatial_service.LEGACY_CATEGORY_ALIASES
        })

        return jsonify({
            "error": "This property has no location coordinates.",
            "categories": empty_categories
        })

    longitude, latitude = coordinates[0], coordinates[1]

    api_key = current_app.config.get("GEOAPIFY_API_KEY")

    result = geospatial_service.get_nearby_pois(
        latitude,
        longitude,
        api_key
    )

    return jsonify(result)


# ============================================================
# LOCATION AUTOCOMPLETE / REVERSE GEOCODING PROXY
#
# The Geoapify API key lives only on the server (read from the
# environment). The frontend calls these same-origin endpoints
# instead of talking to Geoapify directly.
# ============================================================

GEOAPIFY_GEOCODE_URL = "https://api.geoapify.com/v1/geocode"


@property_bp.route(
    "/api/location/autocomplete",
    methods=["GET"]
)
@login_required
def location_autocomplete():

    api_key = current_app.config.get(
        "GEOAPIFY_API_KEY"
    )

    if not api_key:

        return jsonify({
            "error": "Location search is not configured.",
            "results": []
        })

    query = (
        request.args.get("text") or ""
    ).strip()[:200]

    if len(query) < 3:
        return jsonify({"results": []})

    params = {
        "text": query,
        "apiKey": api_key,
        "filter": "countrycode:in",
        "format": "json",
        "limit": 6
    }

    latitude = request.args.get("lat")
    longitude = request.args.get("lon")

    if latitude and longitude:

        try:

            params["bias"] = (
                f"proximity:{float(longitude)},{float(latitude)}"
            )

        except ValueError:
            pass

    try:

        response = requests.get(
            f"{GEOAPIFY_GEOCODE_URL}/autocomplete",
            params=params,
            timeout=6
        )

        response.raise_for_status()

        data = response.json()

    except (requests.RequestException, ValueError):

        return jsonify({
            "error": "Location search is temporarily unavailable.",
            "results": []
        })

    results = []

    for item in data.get("results", []):

        results.append({
            "formatted": item.get("formatted"),
            "address_line1": item.get("address_line1"),
            "city": (
                item.get("city")
                or item.get("county")
            ),
            "state": item.get("state"),
            "locality": (
                item.get("suburb")
                or item.get("district")
            ),
            "sub_locality": (
                item.get("neighbourhood")
                or item.get("quarter")
            ),
            "postcode": item.get("postcode"),
            "lat": item.get("lat"),
            "lon": item.get("lon")
        })

    return jsonify({"results": results})


@property_bp.route(
    "/api/location/reverse",
    methods=["GET"]
)
@login_required
def location_reverse():

    api_key = current_app.config.get(
        "GEOAPIFY_API_KEY"
    )

    if not api_key:

        return jsonify({
            "error": "Location search is not configured."
        })

    try:

        latitude = float(request.args.get("lat", ""))
        longitude = float(request.args.get("lon", ""))

    except (TypeError, ValueError):

        return jsonify({
            "error": "Invalid coordinates."
        }), 400

    params = {
        "lat": latitude,
        "lon": longitude,
        "apiKey": api_key,
        "format": "json"
    }

    try:

        response = requests.get(
            f"{GEOAPIFY_GEOCODE_URL}/reverse",
            params=params,
            timeout=6
        )

        response.raise_for_status()

        data = response.json()

    except (requests.RequestException, ValueError):

        return jsonify({
            "error": "Reverse geocoding is temporarily unavailable."
        })

    results = data.get("results", [])
    item = results[0] if results else {}

    return jsonify({
        "formatted": item.get("formatted"),
        "city": (
            item.get("city")
            or item.get("county")
        ),
        "state": item.get("state"),
        "locality": (
            item.get("suburb")
            or item.get("district")
        ),
        "sub_locality": (
            item.get("neighbourhood")
            or item.get("quarter")
        ),
        "postcode": item.get("postcode")
    })


# ============================================================
# POI COORDINATE RESOLUTION (Mappls -> OSM)
#
# Development/testing endpoint for the new Mappls -> OSM coordinate
# -resolution pipeline (see services/mappls_service.py and
# services/osm_location_service.py). NOT yet wired into property
# search - this only resolves a named place into coordinates so the
# pipeline can be exercised and verified on its own before any search
# flow depends on it. Mappls decides WHICH entity a query means; OSM
# only ever tries to locate the SAME entity Mappls already selected -
# it never re-ranks or second-guesses Mappls' choice.
# ============================================================

@property_bp.route(
    "/api/location/resolve-poi",
    methods=["POST"]
)
@login_required
def resolve_poi():

    data = request.get_json(silent=True) or {}

    query = (data.get("query") or "").strip()[:200]

    if not query:
        return jsonify({"error": "A 'query' field is required."}), 400

    mappls_key = current_app.config.get("MAPPLS_API_KEY")

    # Mappls' own ambiguity resolution depends heavily on this: without a
    # location bias, a short/generic query (e.g. "SRM") can resolve to an
    # unrelated place anywhere in India (confirmed during manual testing -
    # see the implementation report). Callers may pass their own
    # "lat,lon" (e.g. the city the user is currently searching in);
    # SmartHomes' current listings are Chennai-only, so that's the
    # fallback default - NOT a hard-coded assumption once other cities
    # are onboarded, just today's sensible default.
    location_bias = (data.get("location_bias") or "").strip() or "12.9716,80.2217"

    mappls_result = mappls_service.resolve_place(
        query, mappls_key, location_bias=location_bias
    )

    response = {
        "query": query,
        "mappls": {
            "status": mappls_result["status"],
            "place_name": mappls_result["place_name"],
            "place_address": mappls_result["place_address"],
            "eloc": mappls_result["eloc"],
            "type": mappls_result["type"],
            "error": mappls_result["error"],
        },
        "osm": None,
    }

    if mappls_result["status"] != "matched":
        # Nothing for OSM to look for - Mappls itself didn't resolve an
        # entity. Do not fabricate an OSM attempt.
        return jsonify(response)

    osm_service = current_app.extensions.get("osm_location_service")

    osm_result = osm_service.resolve_coordinates({
        "place_name": mappls_result["place_name"],
        "address": mappls_result["place_address"],
        "eloc": mappls_result["eloc"],
        "type": mappls_result["type"],
    })

    response["osm"] = {
        "status": osm_result["status"],
        "latitude": osm_result["latitude"],
        "longitude": osm_result["longitude"],
        "display_name": osm_result["display_name"],
        "confidence": osm_result["confidence"],
        "match_method": osm_result["match_method"],
        "matched_name": osm_result["matched_name"],
        "matched_address": osm_result["matched_address"],
        "osm_id": osm_result["osm_id"],
        "osm_type": osm_result["osm_type"],
        "osm_category": osm_result["osm_category"],
        "candidate_count": osm_result["candidate_count"],
        "alternates": osm_result["alternates"],
        "error": osm_result["error"],
    }

    return jsonify(response)


# ============================================================
# SUBMIT PROPERTY
# ============================================================

@property_bp.route(
    "/submit_listing",
    methods=["POST"]
)
@login_required
def submit_listing():

    form = request.form
    errors = []


    # ========================================================
    # LISTING TYPE / PROPERTY TYPE
    # ========================================================

    listing_type = (
        form.get("listing_type") or ""
    ).strip().lower()

    property_type = (
        form.get("property_type") or ""
    ).strip().lower()

    if listing_type not in LISTING_TYPE_VALUES:
        errors.append("Please select a valid listing type (Rent or Sell).")

    if property_type not in PROPERTY_TYPE_VALUES:
        errors.append("Please select a valid property type.")

    if (
        property_type in RENT_ONLY_PROPERTY_TYPES
        and listing_type == "sell"
    ):
        errors.append(
            "PG / Hostel listings can only be listed for rent."
        )

    # Every field below depends on knowing a valid type, so stop here.

    if errors:

        for message in errors:
            flash(message, "danger")

        return redirect(
            url_for("property.rentals")
        )


    # ========================================================
    # COMMON LISTING FIELDS
    # ========================================================

    listing_values, listing_errors = parse_fields(
        form,
        COMMON_LISTING_FIELDS
    )

    errors.extend(listing_errors)


    # ========================================================
    # LOCATION
    # ========================================================

    location_values, location_errors = parse_fields(
        form,
        LOCATION_FIELDS
    )

    errors.extend(location_errors)

    latitude, longitude, coordinate_error = (
        parse_latitude_longitude(form)
    )

    if coordinate_error:
        errors.append(coordinate_error)


    # ========================================================
    # CONTACT
    # ========================================================

    contact_name = (
        form.get("contact_name") or ""
    ).strip()

    if not contact_name:
        errors.append("Contact name is required.")

    contact_phone, phone_error = parse_phone(
        form,
        "contact_phone",
        "Contact phone",
        required=True
    )

    if phone_error:
        errors.append(phone_error)

    contact_whatsapp, whatsapp_error = parse_phone(
        form,
        "contact_whatsapp",
        "WhatsApp number",
        required=False
    )

    if whatsapp_error:
        errors.append(whatsapp_error)

    preferred_contact_method = (
        form.get("preferred_contact_method") or "phone"
    ).strip().lower()

    if preferred_contact_method not in {"phone", "whatsapp", "email"}:
        preferred_contact_method = "phone"


    # ========================================================
    # TYPE-DEPENDENT GROUPS
    # ========================================================

    rooms_values, rooms_errors = parse_group_for_type(
        form, ROOMS_FIELDS, property_type
    )
    errors.extend(rooms_errors)

    area_values, area_errors = parse_group_for_type(
        form, AREA_FIELDS, property_type
    )
    errors.extend(area_errors)

    building_values, building_errors = parse_group_for_type(
        form, BUILDING_FIELDS, property_type
    )
    errors.extend(building_errors)

    project_values, project_errors = parse_group_for_type(
        form, PROJECT_FIELDS, property_type
    )
    errors.extend(project_errors)

    parking_values, parking_errors = parse_group_for_type(
        form, PARKING_FIELDS, property_type
    )
    errors.extend(parking_errors)

    extra_values, extra_errors = parse_group_for_type(
        form, EXTRA_FIELDS, property_type
    )
    errors.extend(extra_errors)

    legal_values, legal_errors = parse_group_for_type(
        form, LEGAL_FIELDS, property_type
    )
    errors.extend(legal_errors)

    pg_values = {}

    if property_type == "pg_hostel":

        pg_values, pg_errors = parse_group_for_type(
            form, PG_FIELDS, property_type
        )
        errors.extend(pg_errors)


    # ========================================================
    # RENT / SALE (mutually exclusive — never both stored)
    # ========================================================

    rental_values = {}
    sale_values = {}

    if listing_type == "rent" and property_type != "pg_hostel":

        rental_values, rent_errors = parse_fields(
            form, RENT_FIELDS
        )
        errors.extend(rent_errors)

    if listing_type == "sell":

        sale_values, sale_errors = parse_fields(
            form, SALE_FIELDS
        )
        errors.extend(sale_errors)


    # ========================================================
    # AMENITIES
    # ========================================================

    known_amenity_values = {
        value
        for options in AMENITY_CATEGORIES.values()
        for value, _ in options
    }

    selected_amenities = [
        value
        for value in form.getlist("amenities")
        if value in known_amenity_values
    ]

    custom_amenities_raw = (
        form.get("custom_amenities") or ""
    ).strip()

    custom_amenities = []

    if custom_amenities_raw:

        for item in custom_amenities_raw.split(","):

            item = item.strip()[:40]

            if item:
                custom_amenities.append(item)

    custom_amenities = custom_amenities[:20]

    amenities_by_category = {}

    for category, options in AMENITY_CATEGORIES.items():

        option_values = {value for value, _ in options}

        amenities_by_category[category] = [
            value
            for value in selected_amenities
            if value in option_values
        ]

    amenities_by_category["custom"] = custom_amenities

    flat_amenities = selected_amenities + custom_amenities


    # ========================================================
    # MEDIA
    # ========================================================

    image_files = [
        image
        for image in request.files.getlist("images")
        if image and image.filename
    ]

    video_files = [
        video
        for video in request.files.getlist("videos")
        if video and video.filename
    ]

    floor_plan_file = request.files.get("floor_plan")

    brochure_file = request.files.get("brochure")

    virtual_tour_url = (
        form.get("virtual_tour_url") or ""
    ).strip()

    if virtual_tour_url:

        parsed_url = urlparse(virtual_tour_url)

        if (
            parsed_url.scheme not in ("http", "https")
            or not parsed_url.netloc
        ):

            errors.append(
                "Virtual tour URL must be a valid http/https link."
            )

    try:
        media_service.validate_images(image_files)

    except MediaValidationError as exc:
        errors.append(str(exc))

    try:
        media_service.validate_videos(video_files)

    except MediaValidationError as exc:
        errors.append(str(exc))

    try:

        media_service.validate_single_document(
            floor_plan_file,
            media_service.FLOOR_PLAN_EXTENSIONS,
            media_service.MAX_DOCUMENT_BYTES,
            "Floor plan"
        )

    except MediaValidationError as exc:
        errors.append(str(exc))

    try:

        media_service.validate_single_document(
            brochure_file,
            media_service.DOCUMENT_EXTENSIONS,
            media_service.MAX_DOCUMENT_BYTES,
            "Brochure"
        )

    except MediaValidationError as exc:
        errors.append(str(exc))


    # ========================================================
    # STOP HERE IF ANYTHING FAILED
    #
    # Validated fully before any file touches disk.
    # ========================================================

    if errors:

        for message in errors:
            flash(message, "danger")

        return redirect(
            url_for("property.rentals")
        )


    # ========================================================
    # SAVE MEDIA
    # ========================================================

    static_root = current_app.static_folder

    try:
        cover_index = int(form.get("cover_image", "0"))

    except ValueError:
        cover_index = 0

    image_categories = [
        form.get(f"image_category_{index}", "other")
        for index in range(len(image_files))
    ]

    image_filenames, image_meta = media_service.save_images(
        image_files,
        image_categories,
        cover_index,
        static_root
    )

    video_filenames = media_service.save_videos(
        video_files,
        static_root
    )

    floor_plan_filename = media_service.save_single_document(
        floor_plan_file,
        static_root
    )

    brochure_filename = media_service.save_single_document(
        brochure_file,
        static_root
    )


    # ========================================================
    # BACKWARD-COMPATIBLE SUMMARY VALUES
    #
    # `property.bhk` / `property.area_sqft` are read by the
    # existing search + ranking code (out of scope for this
    # change), so they are always kept populated/consistent.
    # ========================================================

    bhk_numeric = None
    bhk_raw = rooms_values.get("bhk")

    if bhk_raw is not None:

        try:

            bhk_numeric = float(bhk_raw)

            if bhk_numeric.is_integer():
                bhk_numeric = int(bhk_numeric)

        except (TypeError, ValueError):
            bhk_numeric = None

    area_summary = (
        area_values.get("super_built_up_sqft")
        or area_values.get("built_up_sqft")
        or area_values.get("plot_sqft")
    )


    # ========================================================
    # BUILD MONGODB DOCUMENT
    # ========================================================

    property_data = {

        "seller": {
            "user_id": current_user.id,
            "username": current_user.username
        },

        "listing": {
            "type": listing_type,
            "status": "active",
            "price": listing_values["price"],
            "currency": "INR",
            "price_negotiable": listing_values.get("price_negotiable", False),
            "title": listing_values.get("title"),
            "posted_by": listing_values.get("posted_by", "owner")
        },

        "property": {
            "type": property_type,
            "bhk": bhk_numeric,
            "area_sqft": area_summary,
            "carpet_area_sqft": area_values.get("carpet_sqft"),
            "bathrooms": rooms_values.get("bathrooms"),
            "balconies": rooms_values.get("balconies"),
            "furnishing": building_values.get("furnishing"),
            "facing": building_values.get("facing"),
            "property_age": building_values.get("property_age"),
            "floor_number": building_values.get("floor_number"),
            "total_floors": building_values.get("total_floors")
        },

        "rooms": rooms_values or None,
        "area": area_values or None,
        "building": building_values or None,
        "project": project_values or None,
        "parking": parking_values or None,
        "type_details": extra_values or None,
        "legal": legal_values or None,
        "pg_details": pg_values or None,

        "amenities": amenities_by_category,
        "features": flat_amenities,

        "rental": rental_values or None,
        "sale": sale_values or None,

        "location": {
            "address": location_values.get("address"),
            "state": location_values.get("state"),
            "city": location_values.get("city"),
            "locality": location_values.get("locality"),
            "sub_locality": location_values.get("sub_locality"),
            "landmark": location_values.get("landmark"),
            "pincode": location_values.get("pincode"),
            "coordinates": {
                "type": "Point",
                "coordinates": [longitude, latitude]
            }
        },

        "contact": {
            "name": contact_name,
            "phone": contact_phone,
            "whatsapp": contact_whatsapp,
            "preferred_contact_method": preferred_contact_method
        },

        "description": {
            "text": listing_values.get("description", ""),
            "language": "en"
        },

        "media": {
            "images": image_filenames,
            "image_meta": image_meta,
            "videos": video_filenames,
            "floor_plan": floor_plan_filename,
            "brochure": brochure_filename,
            "virtual_tour_url": virtual_tour_url or None
        },

        "source": {
            "type": "owner",
            "url": None
        },

        "search": {
            "keywords": [],
            "embedding": None
        }
    }

    property_service = (
        get_property_service()
    )

    property_service.create_property(
        property_data
    )

    flash(
        "Property listed successfully!",
        "success"
    )

    return redirect(
        url_for("property.profile")
    )


# ============================================================
# UNLIST PROPERTY
# ============================================================

@property_bp.route(
    "/delete_listing/<property_id>",
    methods=["POST"]
)
@login_required
def delete_listing(
    property_id
):

    property_service = (
        get_property_service()
    )

    property_item = (
        property_service.get_property(
            property_id
        )
    )

    if property_item is None:

        flash(
            "Property not found.",
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )

    seller = property_item.get(
        "seller",
        {}
    )

    if seller.get(
        "user_id"
    ) != current_user.id:

        flash(
            "You do not have permission "
            "to modify this property.",
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )

    property_service.update_status(
        property_id,
        "inactive"
    )

    flash(
        "Property has been unlisted.",
        "success"
    )

    return redirect(
        url_for(
            "property.profile"
        )
    )
