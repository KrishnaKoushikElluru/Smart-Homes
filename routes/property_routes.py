from urllib.parse import urlparse

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

from extensions import require_csrf

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
from services import ola_maps_service
from services import location_provider_service
from services import nearby_facility_service


property_bp = Blueprint(
    "property",
    __name__
)


# ============================================================
# EDIT LISTING - field pre-fill helper
#
# Flattens a stored property document back into the SAME flat
# {field_name: value} shape parse_fields()/parse_group_for_type()
# produce from a submitted form - the exact inverse of how
# submit_listing() below builds the document in the first place, so
# templates/edit_listing.html can pre-fill every input via
# _field_macros.html's render_field(field, value) with no special
# cases per field.
# ============================================================

_SUB_DOCUMENT_FIELD_GROUPS = [
    ("rooms", ROOMS_FIELDS),
    ("area", AREA_FIELDS),
    ("building", BUILDING_FIELDS),
    ("project", PROJECT_FIELDS),
    ("parking", PARKING_FIELDS),
    ("type_details", EXTRA_FIELDS),
    ("legal", LEGAL_FIELDS),
    ("pg_details", PG_FIELDS),
    ("rental", RENT_FIELDS),
    ("sale", SALE_FIELDS),
]


def _property_field_values(property_item):
    """Returns {field_name: current_value} for every editable field
    services/property_fields.py knows about, read from `property_item`
    (a real MongoDB property document). Only ever READS the document -
    never mutates it."""

    values = {}

    listing = property_item.get("listing") or {}
    values["title"] = listing.get("title")
    values["price"] = listing.get("price")
    values["price_negotiable"] = listing.get("price_negotiable")
    values["posted_by"] = listing.get("posted_by")

    description = property_item.get("description") or {}
    values["description"] = description.get("text")

    location = property_item.get("location") or {}
    for key in ("address", "state", "city", "locality", "sub_locality", "landmark", "pincode"):
        values[key] = location.get(key)

    for doc_key, fields in _SUB_DOCUMENT_FIELD_GROUPS:
        sub_doc = property_item.get(doc_key) or {}
        for field in fields:
            if sub_doc.get(field["name"]) is not None:
                values[field["name"]] = sub_doc[field["name"]]

    # Backward-compat fallback: a property saved before the rooms/area/
    # building split (or any field that - for whatever reason - only
    # ever made it into the flat "property" summary) still needs to
    # pre-fill correctly. "property.*" is the oldest, always-populated
    # summary shape (see submit_listing()'s own "BACKWARD-COMPATIBLE
    # SUMMARY VALUES" section), so it is the safest final fallback.
    property_data = property_item.get("property") or {}
    for key in ("bhk", "furnishing", "facing", "property_age",
                "floor_number", "total_floors", "bathrooms", "balconies"):
        if values.get(key) is None and property_data.get(key) is not None:
            values[key] = property_data[key]

    return values


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
        # Phase 5: property-registration location search no longer uses
        # Geoapify (see routes for /api/location/autocomplete etc.
        # below) - Ola is primary, Mappls+OSM the fallback, so this
        # flag now reflects whether EITHER is configured, not Geoapify.
        location_search_enabled=bool(
            current_app.config.get("OLA_MAPS_API_KEY")
            or current_app.config.get("MAPPLS_API_KEY")
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
        amenity_labels=build_amenity_label_lookup(),
        nearby_facilities_display=nearby_facility_service.build_nearby_facilities_display(
            property_item
        ),
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
# LOCATION AUTOCOMPLETE / REVERSE GEOCODING PROXY (Phase 5)
#
# Ola Maps PRIMARY, Mappls FALLBACK for autocomplete; Ola only for
# reverse geocoding (the manual map click/drag convenience fill - see
# services/ola_maps_service.py's module docstring). Geoapify is no
# longer used anywhere in this file - see docs/PHASE_5_OLA_MAPS_LOCATION_PROVIDER.md
# for the full architecture and why. Every provider API key lives only
# on the server (read from the environment); the frontend calls these
# same-origin endpoints instead of talking to any provider directly.
# ============================================================

@property_bp.route(
    "/api/location/autocomplete",
    methods=["GET"]
)
@login_required
def location_autocomplete():

    ola_api_key = current_app.config.get("OLA_MAPS_API_KEY")
    mappls_api_key = current_app.config.get("MAPPLS_API_KEY")

    if not ola_api_key and not mappls_api_key:

        return jsonify({
            "error": "Location search is not configured.",
            "results": []
        })

    query = (
        request.args.get("text") or ""
    ).strip()[:200]

    if len(query) < 3:
        return jsonify({"results": []})

    location_bias = None

    latitude = request.args.get("lat")
    longitude = request.args.get("lon")

    if latitude and longitude:

        try:
            location_bias = f"{float(latitude)},{float(longitude)}"
        except ValueError:
            location_bias = None

    ola_result = ola_maps_service.autocomplete(
        query, ola_api_key, location_bias=location_bias
    )

    if ola_result["status"] == "matched":
        return jsonify({"results": ola_result["candidates"]})

    if ola_result["status"] == "no_match":
        # A real, confident "Ola has nothing for this text" - falling
        # back to Mappls here would just be guessing on Ola's behalf;
        # an empty result list is the honest answer.
        return jsonify({"results": []})

    # Ola errored or isn't configured - Mappls remains available as
    # fallback (single top candidate, wrapped in the same list shape so
    # the frontend's rendering code doesn't need a second code path).
    mappls_result = mappls_service.resolve_place(
        query, mappls_api_key, location_bias=location_bias
    )

    if mappls_result["status"] != "matched":
        return jsonify({"results": []})

    return jsonify({
        "results": [{
            "provider": "mappls",
            "place_id": None,
            "name": mappls_result["place_name"],
            "address": mappls_result["place_address"],
            "latitude": None,
            "longitude": None,
            "types": [mappls_result["type"]] if mappls_result["type"] else [],
        }]
    })


@property_bp.route(
    "/api/location/resolve-candidate",
    methods=["POST"]
)
@login_required
def location_resolve_candidate():
    """
    Resolves ONE user-selected autocomplete candidate (from either
    provider - see location_autocomplete() above) to final coordinates
    + a structured address breakdown, via
    services/location_provider_service.py's resolve_selected_candidate().
    This is the "Ola Place Details" / "Mappls+OSM fallback" step of the
    registration flow: Autocomplete -> user selects -> THIS endpoint ->
    lat/lng -> map marker.
    """

    data = request.get_json(silent=True) or {}

    provider = data.get("provider")

    if provider not in ("ola", "mappls"):
        return jsonify({"error": "A valid candidate 'provider' is required."}), 400

    candidate = {
        "provider": provider,
        "place_id": data.get("place_id"),
        "name": (data.get("name") or "").strip(),
        "address": (data.get("address") or "").strip(),
    }

    ola_api_key = current_app.config.get("OLA_MAPS_API_KEY")
    osm_service = current_app.extensions.get("osm_location_service")

    result = location_provider_service.resolve_selected_candidate(
        candidate, ola_api_key=ola_api_key, osm_service=osm_service
    )

    return jsonify(result)


@property_bp.route(
    "/api/location/reverse",
    methods=["GET"]
)
@login_required
def location_reverse():

    api_key = current_app.config.get("OLA_MAPS_API_KEY")

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

    result = ola_maps_service.reverse_geocode(latitude, longitude, api_key)

    if result["status"] != "matched":

        return jsonify({
            "error": result["error"] or "Reverse geocoding is temporarily unavailable."
        })

    return jsonify({
        "formatted": result["formatted_address"],
        "city": result["city"],
        "state": result["state"],
        "locality": result["locality"],
        "sub_locality": result["sub_locality"],
        "postcode": result["postcode"]
    })


# ============================================================
# POI COORDINATE RESOLUTION (Ola -> Mappls -> OSM)
#
# Development/testing endpoint for this project's full location-
# resolution pipeline (see services/location_provider_service.py,
# services/ola_maps_service.py, services/mappls_service.py and
# services/osm_location_service.py). NOT yet wired into property
# search - this only resolves a named place into coordinates so the
# pipeline can be exercised and verified on its own. Ola is tried
# first; Mappls+OSM (Phase 1, unchanged) only run at all when Ola does
# NOT produce a safe "matched" result - see
# services/search_orchestration.py's resolve_poi_location_via_best_provider()
# for the same composition this endpoint exercises.
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

    ola_key = current_app.config.get("OLA_MAPS_API_KEY")
    mappls_key = current_app.config.get("MAPPLS_API_KEY")

    # Mappls' (and Ola's) own ambiguity resolution depends heavily on
    # this: without a location bias, a short/generic query (e.g. "SRM")
    # can resolve to an unrelated place anywhere in India (confirmed
    # during manual testing - see the implementation report). Callers
    # may pass their own "lat,lon" (e.g. the city the user is currently
    # searching in); SmartHomes' current listings are Chennai-only, so
    # that's the fallback default - NOT a hard-coded assumption once
    # other cities are onboarded, just today's sensible default.
    location_bias = (data.get("location_bias") or "").strip() or "12.9716,80.2217"

    ola_result = location_provider_service.resolve_location_via_ola(
        query, ola_key, location_bias=location_bias
    )

    response = {
        "query": query,
        "ola": {
            "status": ola_result["status"],
            "place_name": ola_result["place_name"],
            "formatted_address": ola_result["formatted_address"],
            "latitude": ola_result["latitude"],
            "longitude": ola_result["longitude"],
            "confidence": ola_result["confidence"],
            "alternates": ola_result["alternates"],
            "error": ola_result["error"],
        },
        "mappls": None,
        "osm": None,
        "provider": None,
    }

    if ola_result["status"] == "matched":
        response["provider"] = "ola"
        return jsonify(response)

    mappls_result = mappls_service.resolve_place(
        query, mappls_key, location_bias=location_bias
    )

    response["mappls"] = {
        "status": mappls_result["status"],
        "place_name": mappls_result["place_name"],
        "place_address": mappls_result["place_address"],
        "eloc": mappls_result["eloc"],
        "type": mappls_result["type"],
        "error": mappls_result["error"],
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

    if osm_result["status"] == "matched":
        response["provider"] = "mappls"

    return jsonify(response)


# ============================================================
# SUBMIT PROPERTY
# ============================================================

@property_bp.route(
    "/submit_listing",
    methods=["POST"]
)
@login_required
@require_csrf
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

    property_id = property_service.create_property(
        property_data
    )


    # ========================================================
    # NEARBY FACILITY ENRICHMENT (Phase 4.0 - best-effort, Stage 1:
    # runs in the background - see services/nearby_facility_service.py)
    #
    # Property creation above is the operation that matters. This call
    # returns IMMEDIATELY - it only (a) atomically marks the property
    # "pending" and (b) starts a background thread; it never waits for
    # Mappls/MongoDB itself. Everything the background thread needs
    # (property_service, the Mappls key) is passed in explicitly here,
    # while a real Flask request context still exists - the thread
    # itself never touches current_app/request/g (see
    # start_background_enrichment()'s own docstring for why that
    # matters). Coordinates are guaranteed valid at this point
    # (parse_latitude_longitude() already required them earlier in this
    # function).
    # ========================================================

    nearby_facility_service.start_background_enrichment(
        property_id,
        property_service,
        current_app.config.get("MAPPLS_API_KEY"),
        radius_km=current_app.config.get("NEARBY_FACILITY_RADIUS_KM"),
    )


    # ========================================================
    # PRODUCTION IMAGE-SIMILARITY EMBEDDING (Phase 6 - best-effort,
    # background - see services/image_similarity/production_indexer.py)
    #
    # Mirrors the nearby-facility background call immediately above:
    # returns IMMEDIATELY, never blocks this response. Embeds each
    # saved image with the SAME SigLIP2 encoder already used by the
    # 21-house benchmark and the MongoDB smoke test, tagging every
    # record source="mongodb_production" - a completely separate index
    # from the smoke test's (source="mongodb_smoke_test"), never mixed
    # into production retrieval. Lazily imported here (not at module
    # load time) so torch/transformers are never loaded at Flask
    # startup or on any other request path - only the first time a
    # property with images is actually registered. A property with no
    # images is a no-op inside start_background_embedding() itself.
    # ========================================================

    from services.image_similarity import production_indexer

    production_indexer.start_background_embedding(
        property_id,
        image_filenames,
        static_root,
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
@require_csrf
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

    if property_item.get("listing", {}).get("status") == "inactive":

        flash(
            "This property is already unlisted.",
            "info"
        )

    else:

        property_service.update_status(
            property_id,
            "inactive"
        )

        flash(
            "Property has been unlisted. It no longer appears in "
            "search results or Find Similar Homes.",
            "success"
        )

    return redirect(
        url_for(
            "property.profile"
        )
    )


# ============================================================
# RELIST PROPERTY
#
# Symmetric counterpart to delete_listing() above - the application's
# "delete" was always a reversible status change (listing.status:
# "active" <-> "inactive"), never a permanent deletion (see
# PropertyService.delete_property(), which exists but is intentionally
# never called from any route) - so relisting is just setting the
# status back, using the exact same ownership check as unlisting.
# ============================================================

@property_bp.route(
    "/relist_listing/<property_id>",
    methods=["POST"]
)
@login_required
@require_csrf
def relist_listing(
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

    if property_item.get("listing", {}).get("status") == "active":

        flash(
            "This property is already listed.",
            "info"
        )

    else:

        property_service.update_status(
            property_id,
            "active"
        )

        flash(
            "Property has been relisted and is active again.",
            "success"
        )

    return redirect(
        url_for(
            "property.profile"
        )
    )


# ============================================================
# EDIT LISTING
#
# GET renders the SAME registration form components (field_config,
# render_field(), property_form.css/js) submit_listing() already uses,
# pre-filled with the property's current values (_property_field_values()
# above) - no second property-edit system, just the existing one with
# values supplied. POST (update_listing() below) reuses the exact same
# parsing/validation functions submit_listing() does.
# ============================================================

@property_bp.route(
    "/edit_listing/<property_id>",
    methods=["GET"]
)
@login_required
def edit_listing(
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

    field_values = _property_field_values(property_item)

    known_amenity_values = {
        value
        for options in AMENITY_CATEGORIES.values()
        for value, _ in options
    }

    current_features = property_item.get("features") or []

    selected_amenities = [
        value for value in current_features if value in known_amenity_values
    ]

    custom_amenities_text = ", ".join(
        value for value in current_features if value not in known_amenity_values
    )

    media = property_item.get("media") or {}
    existing_images = media.get("images") or []
    image_meta_by_filename = {
        item.get("filename"): item
        for item in (media.get("image_meta") or [])
    }

    coordinates_field = (property_item.get("location") or {}).get("coordinates") or {}
    coordinate_values = coordinates_field.get("coordinates") or []

    initial_coords = None
    if len(coordinate_values) == 2:
        initial_coords = {
            "lat": coordinate_values[1],
            "lon": coordinate_values[0],
        }

    return render_template(
        "edit_listing.html",
        listing=property_item,
        field_config=build_field_config(),
        image_categories=IMAGE_CATEGORIES,
        field_values=field_values,
        selected_amenities=selected_amenities,
        custom_amenities_text=custom_amenities_text,
        existing_images=existing_images,
        image_meta_by_filename=image_meta_by_filename,
        initial_coords=initial_coords,
        location_search_enabled=bool(
            current_app.config.get("OLA_MAPS_API_KEY")
            or current_app.config.get("MAPPLS_API_KEY")
        ),
    )


# ============================================================
# UPDATE LISTING
#
# Mirrors submit_listing() field-for-field (same parse_fields() /
# parse_group_for_type() / parse_latitude_longitude() / parse_phone()
# calls, same validation order, same document shape) - the
# differences are exactly the ones Edit actually needs: images are
# optional (existing ones may be kept), the update is scoped to BOTH
# property_id AND the authenticated owner at the MongoDB layer
# (PropertyService.update_property_for_owner()), and _id/seller/
# created_at/source/search are never touched. See the module docstring
# comment above _property_field_values() for the pre-fill half of this
# feature.
# ============================================================

@property_bp.route(
    "/update_listing/<property_id>",
    methods=["POST"]
)
@login_required
@require_csrf
def update_listing(
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

    if errors:

        for message in errors:
            flash(message, "danger")

        return redirect(
            url_for("property.edit_listing", property_id=property_id)
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
    # MEDIA - IMAGES (the one real departure from submit_listing():
    # existing images may be kept, individually removed, and/or
    # supplemented with new uploads - at least one image must remain
    # across the two, but neither existing nor new images are
    # individually required)
    # ========================================================

    media = property_item.get("media") or {}
    existing_images = media.get("images") or []
    existing_image_meta_by_filename = {
        item.get("filename"): item
        for item in (media.get("image_meta") or [])
    }

    requested_removals = set(form.getlist("remove_images"))
    # Only filenames that actually belong to THIS property can ever be
    # removed - a tampered/unrelated filename in the request is simply
    # ignored, never acted on.
    remove_filenames = {
        filename for filename in requested_removals
        if filename in existing_images
    }

    kept_filenames = [
        filename for filename in existing_images
        if filename not in remove_filenames
    ]

    new_image_files = [
        image
        for image in request.files.getlist("images")
        if image and image.filename
    ]

    if new_image_files:

        try:
            media_service.validate_images(new_image_files)

        except MediaValidationError as exc:
            errors.append(str(exc))

    if not kept_filenames and not new_image_files:
        errors.append("At least one property image is required.")


    # ========================================================
    # MEDIA - VIDEOS / DOCUMENTS / VIRTUAL TOUR (same "keep existing
    # unless a new file/value is actually supplied" rule as images)
    # ========================================================

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
        media_service.validate_videos(video_files)

    except MediaValidationError as exc:
        errors.append(str(exc))

    if floor_plan_file is not None and floor_plan_file.filename:

        try:

            media_service.validate_single_document(
                floor_plan_file,
                media_service.FLOOR_PLAN_EXTENSIONS,
                media_service.MAX_DOCUMENT_BYTES,
                "Floor plan"
            )

        except MediaValidationError as exc:
            errors.append(str(exc))

    if brochure_file is not None and brochure_file.filename:

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
    # STOP HERE IF ANYTHING FAILED - validated fully before any file
    # touches disk, and before any existing file is removed.
    # ========================================================

    if errors:

        for message in errors:
            flash(message, "danger")

        return redirect(
            url_for("property.edit_listing", property_id=property_id)
        )


    # ========================================================
    # SAVE / REMOVE MEDIA
    # ========================================================

    static_root = current_app.static_folder

    new_filenames = []
    new_image_meta = []

    if new_image_files:

        new_categories = [
            form.get(f"image_category_{index}", "other")
            for index in range(len(new_image_files))
        ]

        new_filenames, new_image_meta = media_service.save_images(
            new_image_files,
            new_categories,
            0,
            static_root
        )

    if remove_filenames:

        for filename in remove_filenames:
            media_service.delete_image_file(filename, static_root)

        from services.image_similarity import production_indexer

        production_indexer.remove_property_image_embeddings(
            property_id,
            list(remove_filenames)
        )

    # Kept existing images: allow re-categorizing without re-uploading
    # (a cheap, natural extension of "edit this image's metadata" -
    # the file itself, and therefore its similarity embedding, is
    # completely untouched).
    kept_meta = []

    for filename in kept_filenames:

        original = existing_image_meta_by_filename.get(filename, {})
        category = form.get(f"existing_image_category_{filename}", original.get("category", "other"))

        if category not in media_service.IMAGE_CATEGORY_VALUES:
            category = "other"

        kept_meta.append({
            "filename": filename,
            "category": category,
            "is_cover": False,  # resolved below, once, across kept + new
        })

    final_images = kept_filenames + new_filenames
    final_meta = kept_meta + new_image_meta

    cover_selection = form.get("cover_image", "")
    cover_filename = None

    if cover_selection.startswith("existing:"):
        cover_filename = cover_selection[len("existing:"):]
    else:
        try:
            new_index = int(cover_selection)
            if 0 <= new_index < len(new_filenames):
                cover_filename = new_filenames[new_index]
        except (TypeError, ValueError):
            pass

    if cover_filename and cover_filename in final_images:

        for item in final_meta:
            item["is_cover"] = (item["filename"] == cover_filename)

    if final_meta and not any(item.get("is_cover") for item in final_meta):
        final_meta[0]["is_cover"] = True

    if video_files:
        video_filenames = media_service.save_videos(video_files, static_root)
    else:
        video_filenames = media.get("videos") or []

    if floor_plan_file is not None and floor_plan_file.filename:
        floor_plan_filename = media_service.save_single_document(floor_plan_file, static_root)
    else:
        floor_plan_filename = media.get("floor_plan")

    if brochure_file is not None and brochure_file.filename:
        brochure_filename = media_service.save_single_document(brochure_file, static_root)
    else:
        brochure_filename = media.get("brochure")


    # ========================================================
    # BACKWARD-COMPATIBLE SUMMARY VALUES (identical derivation to
    # submit_listing() - property.bhk / property.area_sqft stay
    # consistent for the existing search + ranking code)
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
    # BUILD UPDATE DOCUMENT
    #
    # Everything a listing owner can actually edit - and NOTHING else.
    # _id, seller, created_at, source, search.embedding, and
    # listing.status are never part of this dict (status is owned
    # exclusively by delete_listing()/relist_listing() above).
    # ========================================================

    updates = {

        "listing.type": listing_type,
        "listing.price": listing_values["price"],
        "listing.price_negotiable": listing_values.get("price_negotiable", False),
        "listing.title": listing_values.get("title"),
        "listing.posted_by": listing_values.get("posted_by", "owner"),

        "property.type": property_type,
        "property.bhk": bhk_numeric,
        "property.area_sqft": area_summary,
        "property.carpet_area_sqft": area_values.get("carpet_sqft"),
        "property.bathrooms": rooms_values.get("bathrooms"),
        "property.balconies": rooms_values.get("balconies"),
        "property.furnishing": building_values.get("furnishing"),
        "property.facing": building_values.get("facing"),
        "property.property_age": building_values.get("property_age"),
        "property.floor_number": building_values.get("floor_number"),
        "property.total_floors": building_values.get("total_floors"),

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

        "location.address": location_values.get("address"),
        "location.state": location_values.get("state"),
        "location.city": location_values.get("city"),
        "location.locality": location_values.get("locality"),
        "location.sub_locality": location_values.get("sub_locality"),
        "location.landmark": location_values.get("landmark"),
        "location.pincode": location_values.get("pincode"),
        "location.coordinates": {
            "type": "Point",
            "coordinates": [longitude, latitude]
        },

        "contact.name": contact_name,
        "contact.phone": contact_phone,
        "contact.whatsapp": contact_whatsapp,
        "contact.preferred_contact_method": preferred_contact_method,

        "description.text": listing_values.get("description", ""),

        "media.images": final_images,
        "media.image_meta": final_meta,
        "media.videos": video_filenames,
        "media.floor_plan": floor_plan_filename,
        "media.brochure": brochure_filename,
        "media.virtual_tour_url": virtual_tour_url or None,
    }

    # Captured BEFORE update_property_for_owner() runs, and as a
    # plain copied list rather than a live reference into
    # property_item - update_property_for_owner()'s contract says
    # nothing about whether it may mutate the document it was handed
    # (the real PropertyService fetches a fresh dict per call so this
    # never arises there, but nothing should depend on that). Computing
    # "did the location change" from a value that could have already
    # been overwritten by the update itself would silently defeat this
    # whole re-enrichment check.
    old_coordinates = list(
        (
            (property_item.get("location") or {}).get("coordinates") or {}
        ).get("coordinates") or []
    )

    updated = property_service.update_property_for_owner(
        property_id,
        current_user.id,
        updates
    )

    if not updated:

        flash(
            "Property could not be updated. Please try again.",
            "danger"
        )

        return redirect(
            url_for("property.profile")
        )


    # ========================================================
    # LOCATION CHANGE -> RE-ENRICH NEARBY FACILITIES (Step 10)
    #
    # Only re-triggers the EXISTING background enrichment mechanism
    # (services/nearby_facility_service.py, unchanged) when the
    # coordinates actually moved - an edit that only touches price/
    # BHK/furnishing/etc. must never re-call Mappls or touch
    # nearby_facilities at all. claim_nearby_facilities_enrichment()
    # already allows re-claiming once the previous run is no longer
    # "pending", so a second real location change later works too.
    # ========================================================

    location_changed = (
        len(old_coordinates) != 2
        or abs(old_coordinates[0] - longitude) > 1e-6
        or abs(old_coordinates[1] - latitude) > 1e-6
    )

    if location_changed:

        nearby_facility_service.start_background_enrichment(
            property_id,
            property_service,
            current_app.config.get("MAPPLS_API_KEY"),
            radius_km=current_app.config.get("NEARBY_FACILITY_RADIUS_KM"),
        )


    # ========================================================
    # NEW IMAGES -> BACKGROUND SIGLIP2 EMBEDDING (Step 6/7/9/13)
    #
    # Only the NEW filenames - unchanged kept images are never
    # re-embedded (their existing production-index records, and the
    # background worker/thread pattern itself, are both reused
    # completely unchanged; see production_indexer.py). Metadata-only
    # edits (no new_filenames) never reach this at all, so SigLIP2 is
    # never invoked for them.
    # ========================================================

    if new_filenames:

        from services.image_similarity import production_indexer

        production_indexer.start_background_embedding(
            property_id,
            new_filenames,
            static_root,
        )

    flash(
        "Property updated successfully!",
        "success"
    )

    return redirect(
        url_for(
            "property.profile"
        )
    )
