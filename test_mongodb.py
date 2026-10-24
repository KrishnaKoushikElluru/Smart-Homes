import os

from dotenv import load_dotenv

from services.mongo_service import (
    MongoService
)

from services.property_services import (
    PropertyService
)


# ============================================================
# MANUAL SMOKE TEST - NOT a unittest.TestCase (no `def test_*`
# methods), so `unittest discover -p "test_*.py"` finds nothing to
# run here. Everything below is gated behind `if __name__ ==
# "__main__"` specifically so that DISCOVERY (which imports every
# matching file) never triggers it - this file's body used to run at
# IMPORT time, which meant every `unittest discover` invocation
# silently performed a real insert/read/delete against the live
# MongoDB configured in secret.env. This script is still fully usable
# exactly as before - run it directly:
#
#     .venv/Scripts/python.exe test_mongodb.py
#
# to manually verify the real Mongo connection end to end.
# ============================================================

def main():

    load_dotenv("secret.env")

    mongo_uri = os.getenv(
        "MONGO_URI"
    )

    if not mongo_uri:

        raise RuntimeError(
            "MONGO_URI is missing."
        )

    mongo_service = MongoService(
        mongo_uri
    )

    mongo_service.ping()

    print(
        "[OK] MongoDB connection successful!"
    )

    property_service = PropertyService(
        mongo_service
    )

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


if __name__ == "__main__":
    main()
