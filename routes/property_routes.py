import os
from datetime import datetime

from flask import (
    Blueprint,
    render_template,
    request,
    redirect,
    url_for,
    flash,
    current_app
)

from flask_login import (
    login_required,
    current_user
)

from werkzeug.utils import secure_filename


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
# FILE CONFIGURATION
# ============================================================

IMAGE_EXTENSIONS = {
    "jpg",
    "jpeg",
    "png",
    "webp"
}


VIDEO_EXTENSIONS = {
    "mp4",
    "webm",
    "mov"
}


IMAGE_DIRECTORY = (
    "static/images/properties"
)


VIDEO_DIRECTORY = (
    "static/videos/properties"
)


# ============================================================
# FILE VALIDATION
# ============================================================

def allowed_file(
    filename,
    allowed_extensions
):

    if not filename:
        return False

    if "." not in filename:
        return False

    extension = (
        filename
        .rsplit(".", 1)[-1]
        .lower()
    )

    return extension in allowed_extensions


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
        listings=properties
    )


# ============================================================
# RENTALS / ACTIVE PROPERTIES
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
        listings=properties
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

    # --------------------------------------------------------
    # Property not found
    # --------------------------------------------------------

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

    # --------------------------------------------------------
    # Render details page
    # --------------------------------------------------------

    return render_template(
        "property_details.html",
        property=property_item
    )

# ============================================================
# SUBMIT PROPERTY
# ============================================================

@property_bp.route(
    "/submit_listing",
    methods=["POST"]
)
@login_required
def submit_listing():

    # ========================================================
    # BASIC LISTING INFORMATION
    # ========================================================

    listing_type = request.form.get(
        "listing_type",
        ""
    ).strip().lower()

    price = request.form.get(
        "price",
        ""
    ).strip()

    price_negotiable = (
        request.form.get(
            "price_negotiable"
        )
        == "on"
    )


    # ========================================================
    # PROPERTY INFORMATION
    # ========================================================

    property_type = request.form.get(
        "property_type",
        ""
    ).strip()

    bhk = request.form.get(
        "bhk",
        ""
    ).strip()

    area = request.form.get(
        "area_sqft",
        ""
    ).strip()

    carpet_area = request.form.get(
        "carpet_area_sqft",
        ""
    ).strip()

    bathrooms = request.form.get(
        "bathrooms",
        ""
    ).strip()

    balconies = request.form.get(
        "balconies",
        ""
    ).strip()

    furnishing = request.form.get(
        "furnishing",
        ""
    ).strip().lower()

    facing = request.form.get(
        "facing",
        ""
    ).strip().lower()

    property_age = request.form.get(
        "property_age",
        ""
    ).strip()

    floor_number = request.form.get(
        "floor_number",
        ""
    ).strip()

    total_floors = request.form.get(
        "total_floors",
        ""
    ).strip()


    # ========================================================
    # LOCATION
    # ========================================================

    address = request.form.get(
        "address",
        ""
    ).strip()

    city = request.form.get(
        "city",
        ""
    ).strip()

    locality = request.form.get(
        "locality",
        ""
    ).strip()

    pincode = request.form.get(
        "pincode",
        ""
    ).strip()

    latitude = request.form.get(
        "latitude",
        ""
    ).strip()

    longitude = request.form.get(
        "longitude",
        ""
    ).strip()


    # ========================================================
    # BUILDING
    # ========================================================

    project_name = request.form.get(
        "project_name",
        ""
    ).strip()

    gated_community = (
        request.form.get(
            "gated_community"
        )
        == "on"
    )

    amenities = request.form.getlist(
        "amenities"
    )


    # ========================================================
    # CONTACT
    # ========================================================

    contact_name = request.form.get(
        "contact_name",
        ""
    ).strip()

    contact_phone = request.form.get(
        "contact_phone",
        ""
    ).strip()


    # ========================================================
    # DESCRIPTION
    # ========================================================

    description_text = request.form.get(
        "description",
        ""
    ).strip()


    # ========================================================
    # RENTAL INFORMATION
    # ========================================================

    security_deposit = request.form.get(
        "security_deposit",
        ""
    ).strip()

    maintenance = request.form.get(
        "maintenance",
        ""
    ).strip()

    available_from = request.form.get(
        "available_from",
        ""
    ).strip()

    preferred_tenant = request.form.get(
        "preferred_tenant",
        ""
    ).strip()

    lease_type = request.form.get(
        "lease_type",
        ""
    ).strip()

    pets_allowed_value = request.form.get(
        "pets_allowed"
    )

    pets_allowed = None

    if pets_allowed_value == "yes":
        pets_allowed = True

    elif pets_allowed_value == "no":
        pets_allowed = False


    # ========================================================
    # SALE INFORMATION
    # ========================================================

    transaction_type = request.form.get(
        "transaction_type",
        ""
    ).strip()

    ownership = request.form.get(
        "ownership",
        ""
    ).strip()

    possession_status = request.form.get(
        "possession_status",
        ""
    ).strip()

    rera_id = request.form.get(
        "rera_id",
        ""
    ).strip()


    # ========================================================
    # REQUIRED VALIDATION
    # ========================================================

    if listing_type not in [
        "rent",
        "sell"
    ]:

        flash(
            "Please select rent or sell.",
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    if not property_type:

        flash(
            "Property type is required.",
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    if not price:

        flash(
            "Price is required.",
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    if not contact_name or not contact_phone:

        flash(
            "Contact information is required.",
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    # ========================================================
    # PRICE
    # ========================================================

    try:

        price_value = int(price)

        if price_value <= 0:
            raise ValueError

    except ValueError:

        flash(
            "Price must be a valid positive number.",
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    # ========================================================
    # NUMERIC PROPERTY VALUES
    # ========================================================

    def parse_positive_int(
        value,
        field_name
    ):

        if not value:
            return None, None

        try:

            number = int(value)

            if number <= 0:
                raise ValueError

            return number, None

        except ValueError:

            return (
                None,
                f"{field_name} must be a valid positive number."
            )


    def parse_positive_float(
        value,
        field_name
    ):

        if not value:
            return None, None

        try:

            number = float(value)

            if number <= 0:
                raise ValueError

            return number, None

        except ValueError:

            return (
                None,
                f"{field_name} must be a valid positive number."
            )


    bhk_value, error = parse_positive_int(
        bhk,
        "BHK"
    )

    if error:

        flash(
            error,
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    bathrooms_value, error = parse_positive_int(
        bathrooms,
        "Bathrooms"
    )

    if error:

        flash(
            error,
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    balconies_value, error = parse_positive_int(
        balconies,
        "Balconies"
    )

    if error:

        flash(
            error,
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    property_age_value, error = parse_positive_int(
        property_age,
        "Property age"
    )

    if error:

        flash(
            error,
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    floor_number_value, error = parse_positive_int(
        floor_number,
        "Floor number"
    )

    if error:

        flash(
            error,
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    total_floors_value, error = parse_positive_int(
        total_floors,
        "Total floors"
    )

    if error:

        flash(
            error,
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    area_value, error = parse_positive_float(
        area,
        "Area"
    )

    if error:

        flash(
            error,
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    carpet_area_value, error = parse_positive_float(
        carpet_area,
        "Carpet area"
    )

    if error:

        flash(
            error,
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    # ========================================================
    # LOCATION VALIDATION
    # ========================================================

    if not latitude or not longitude:

        flash(
            "Please select the property location on the map.",
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    try:

        latitude_value = float(
            latitude
        )

        longitude_value = float(
            longitude
        )

        if not -90 <= latitude_value <= 90:
            raise ValueError

        if not -180 <= longitude_value <= 180:
            raise ValueError

    except ValueError:

        flash(
            "Invalid map coordinates.",
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    # ========================================================
    # IMAGE UPLOAD
    # ========================================================

    image_files = request.files.getlist(
        "images"
    )

    image_files = [
        image
        for image in image_files
        if image and image.filename
    ]


    # At least one image is compulsory

    if not image_files:

        flash(
            "At least one property image is required.",
            "danger"
        )

        return redirect(
            url_for(
                "property.profile"
            )
        )


    # ========================================================
    # VIDEO UPLOAD
    # ========================================================

    video_files = request.files.getlist(
        "videos"
    )

    video_files = [
        video
        for video in video_files
        if video and video.filename
    ]


    # ========================================================
    # CREATE DIRECTORIES
    # ========================================================

    os.makedirs(
        IMAGE_DIRECTORY,
        exist_ok=True
    )

    os.makedirs(
        VIDEO_DIRECTORY,
        exist_ok=True
    )


    # ========================================================
    # SAVE IMAGES
    # ========================================================

    image_filenames = []


    for image_file in image_files:

        filename = secure_filename(
            image_file.filename
        )


        if not allowed_file(
            filename,
            IMAGE_EXTENSIONS
        ):

            flash(
                "Only JPG, JPEG, PNG and WEBP "
                "images are allowed.",
                "danger"
            )

            return redirect(
                url_for(
                    "property.profile"
                )
            )


        image_file.save(
            os.path.join(
                IMAGE_DIRECTORY,
                filename
            )
        )


        image_filenames.append(
            filename
        )


    # ========================================================
    # SAVE VIDEOS
    # ========================================================

    video_filenames = []


    for video_file in video_files:

        filename = secure_filename(
            video_file.filename
        )


        if not allowed_file(
            filename,
            VIDEO_EXTENSIONS
        ):

            flash(
                "Only MP4, WEBM and MOV "
                "videos are allowed.",
                "danger"
            )

            return redirect(
                url_for(
                    "property.profile"
                )
            )


        video_file.save(
            os.path.join(
                VIDEO_DIRECTORY,
                filename
            )
        )


        video_filenames.append(
            filename
        )


    # ========================================================
    # BUILD RENTAL DATA
    # ========================================================

    rental_data = None


    if listing_type == "rent":

        rental_data = {

            "security_deposit":
                int(security_deposit)
                if security_deposit
                else None,

            "maintenance":
                int(maintenance)
                if maintenance
                else None,

            "available_from":
                available_from
                if available_from
                else None,

            "preferred_tenant":
                preferred_tenant
                if preferred_tenant
                else None,

            "lease_type":
                lease_type
                if lease_type
                else None,

            "pets_allowed":
                pets_allowed
        }


    # ========================================================
    # BUILD SALE DATA
    # ========================================================

    sale_data = None


    if listing_type == "sell":

        sale_data = {

            "transaction_type":
                transaction_type
                if transaction_type
                else None,

            "ownership":
                ownership
                if ownership
                else None,

            "possession_status":
                possession_status
                if possession_status
                else None,

            "rera_id":
                rera_id
                if rera_id
                else None
        }


    # ========================================================
    # BUILD MONGODB DOCUMENT
    # ========================================================

    property_data = {

        "seller": {

            "user_id":
                current_user.id,

            "username":
                current_user.username
        },


        "listing": {

            "type":
                listing_type,

            "price":
                price_value,

            "currency":
                "INR",

            "status":
                "active",

            "price_negotiable":
                price_negotiable
        },


        "property": {

            "type":
                property_type,

            "bhk":
                bhk_value,

            "area_sqft":
                area_value,

            "carpet_area_sqft":
                carpet_area_value,

            "bathrooms":
                bathrooms_value,

            "balconies":
                balconies_value,

            "furnishing":
                furnishing
                if furnishing
                else None,

            "facing":
                facing
                if facing
                else None,

            "property_age":
                property_age_value,

            "floor_number":
                floor_number_value,

            "total_floors":
                total_floors_value
        },


        "location": {

            "address":
                address,

            "city":
                city,

            "locality":
                locality,

            "pincode":
                pincode,

            "coordinates": {

                "type":
                    "Point",

                "coordinates": [

                    longitude_value,

                    latitude_value
                ]
            }
        },


        "building": {

            "project_name":
                project_name
                if project_name
                else None,

            "gated_community":
                gated_community,

            "amenities":
                amenities
        },


        "rental":
            rental_data,


        "sale":
            sale_data,


        "contact": {

            "name":
                contact_name,

            "phone":
                contact_phone
        },


        "description": {

            "text":
                description_text,

            "language":
                "en"
        },


        "media": {

            "images":
                image_filenames,

            "videos":
                video_filenames
        },


        "source": {

            "type":
                "owner",

            "url":
                None
        },


        "search": {

            "keywords":
                [],

            "embedding":
                None
        }
    }


    # ========================================================
    # SAVE PROPERTY
    # ========================================================

    property_service = (
        get_property_service()
    )


    property_id = (
        property_service.create_property(
            property_data
        )
    )


    # ========================================================
    # SUCCESS
    # ========================================================

    flash(
        "Property listed successfully!",
        "success"
    )


    return redirect(
        url_for(
            "property.profile"
        )
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