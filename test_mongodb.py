import os

from dotenv import load_dotenv

from services.mongo_service import (
    MongoService
)

from services.property_services import (
    PropertyService
)


# ============================================================
# LOAD ENVIRONMENT
# ============================================================

load_dotenv("secret.env")


mongo_uri = os.getenv(
    "MONGO_URI"
)

if not mongo_uri:

    raise RuntimeError(
        "MONGO_URI is missing."
    )


# ============================================================
# CONNECT
# ============================================================

mongo_service = MongoService(
    mongo_uri
)

mongo_service.ping()

print(
    "[OK] MongoDB connection successful!"
)


# ============================================================
# PROPERTY SERVICE
# ============================================================

property_service = PropertyService(
    mongo_service
)


# ============================================================
# TEST PROPERTY
# ============================================================

test_property = {

    "property_id": 999999,

    "seller": {

        "user_id": 1,

        "username": "_krishna_koushik"
    },

    "listing": {

        "type": "rent",

        "price": 45000,

        "currency": "INR",

        "status": "active"
    },

    "property": {

        "type": "house",

        "bhk": 3,

        "area_sqft": None,

        "furnishing": "fully_furnished",

        "facing": "east"
    },

    "location": {

        "address": (
            "Kurnool, pandipadu, "
            "518002, near indus school"
        ),

        "city": "Kurnool",

        "locality": "pandipadu",

        "pincode": "518002",

        "coordinates": None
    },

    "features": [

        "garden",

        "east_facing"
    ],

    "description": {

        "text": (
            "Very spacious and wide "
            "garden area facing east side "
            "3BHK, fully furnished"
        ),

        "language": "en"
    },

    "media": {

        "images": [],

        "videos": [
            "sample_video_2.mp4"
        ]
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


# ============================================================
# INSERT
# ============================================================

property_id = (
    property_service.create_property(
        test_property
    )
)

print(
    "[OK] Property inserted!"
)

print(
    "MongoDB ID:",
    property_id
)


# ============================================================
# READ
# ============================================================

property_document = (
    property_service.get_property(
        property_id
    )
)

print(
    "[OK] Property retrieved!"
)

print(
    property_document
)


# ============================================================
# CLEANUP
# ============================================================

property_service.delete_property(
    property_id
)

print(
    "[OK] Test property deleted."
)


mongo_service.close()

print(
    "[OK] MongoDB test completed successfully!"
)