from datetime import datetime

from bson import ObjectId


class PropertyService:

    COLLECTION_NAME = "properties"


    def __init__(
        self,
        mongo_service
    ):

        self.collection = mongo_service.get_collection(
            self.COLLECTION_NAME
        )


    # ========================================================
    # CREATE
    # ========================================================

    def create_property(
        self,
        property_data
    ):

        now = datetime.utcnow()

        property_data["created_at"] = now

        property_data["updated_at"] = now

        result = self.collection.insert_one(
            property_data
        )

        return str(
            result.inserted_id
        )


    # ========================================================
    # GET ONE
    # ========================================================

    def get_property(
        self,
        property_id
    ):

        document = self.collection.find_one(
            {
                "_id": ObjectId(property_id)
            }
        )

        return document


    # ========================================================
    # GET ALL
    # ========================================================

    def get_all_properties(
        self
    ):

        return list(
            self.collection.find()
        )


    # ========================================================
    # GET ACTIVE PROPERTIES
    # ========================================================

    def get_active_properties(
        self
    ):

        return list(
            self.collection.find(
                {
                    "listing.status": "active"
                }
            )
        )


    # ========================================================
    # GET PROPERTIES BY SELLER
    # ========================================================

    def get_properties_by_seller(
        self,
        seller_id
    ):

        return list(
            self.collection.find(
                {
                    "seller.user_id": seller_id
                }
            )
        )


    # ========================================================
    # BASIC MONGODB SEARCH
    # ========================================================

    def search_properties(
        self,
        filters
    ):

        return list(
            self.collection.find(
                filters
            )
        )


    # ========================================================
    # RANKED PROPERTY SEARCH
    # ========================================================

    def ranked_search(
        self,
        preferences
    ):

        # ----------------------------------------------------
        # Get all active properties
        # ----------------------------------------------------

        properties = list(
            self.collection.find(
                {
                    "listing.status": "active"
                }
            )
        )


        ranked_properties = []


        # ----------------------------------------------------
        # User preferences
        # ----------------------------------------------------

        budget = preferences.get(
            "budget"
        )

        city = preferences.get(
            "city",
            ""
        ).strip().lower()

        locality = preferences.get(
            "locality",
            ""
        ).strip().lower()

        listing_type = preferences.get(
            "listing_type",
            ""
        ).strip().lower()

        property_type = preferences.get(
            "property_type",
            ""
        ).strip().lower()

        bhk = preferences.get(
            "bhk"
        )


        # ----------------------------------------------------
        # Score every property
        # ----------------------------------------------------

        for property_item in properties:

            score = 0


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


            # =================================================
            # LISTING TYPE
            # =================================================

            property_listing_type = str(
                listing.get(
                    "type",
                    ""
                )
            ).lower()


            if listing_type:

                if property_listing_type == listing_type:

                    score += 25

                else:

                    # Different rent/sell type should be
                    # strongly penalized.

                    score -= 30


            # =================================================
            # CITY
            # =================================================

            property_city = str(
                location.get(
                    "city",
                    ""
                )
            ).lower()


            if city:

                if property_city == city:

                    score += 25

                elif city in property_city:

                    score += 15

                elif property_city in city:

                    score += 10


            # =================================================
            # LOCALITY
            # =================================================

            property_locality = str(
                location.get(
                    "locality",
                    ""
                )
            ).lower()


            if locality:

                if property_locality == locality:

                    score += 25

                elif locality in property_locality:

                    score += 20

                elif property_locality in locality:

                    score += 15

                else:

                    # Check individual words.

                    search_words = set(
                        locality.split()
                    )

                    property_words = set(
                        property_locality.split()
                    )

                    common_words = (
                        search_words
                        & property_words
                    )

                    if common_words:

                        score += min(
                            15,
                            len(common_words) * 5
                        )


            # =================================================
            # PROPERTY TYPE
            # =================================================

            property_type_value = str(
                property_data.get(
                    "type",
                    ""
                )
            ).lower()


            if property_type:

                if property_type_value == property_type:

                    score += 15

                elif (
                    property_type in
                    property_type_value
                ):

                    score += 10

                elif (
                    property_type_value in
                    property_type
                ):

                    score += 8


            # =================================================
            # BHK
            # =================================================

            property_bhk = property_data.get(
                "bhk"
            )


            if bhk is not None:

                if property_bhk == bhk:

                    score += 15

                elif (
                    isinstance(
                        property_bhk,
                        (int, float)
                    )
                    and
                    abs(
                        property_bhk - bhk
                    ) == 1
                ):

                    # Nearby BHK is still relevant.

                    score += 7


            # =================================================
            # PRICE / BUDGET
            # =================================================

            property_price = listing.get(
                "price"
            )


            if (
                budget
                and
                property_price
                and
                budget > 0
            ):

                try:

                    property_price = float(
                        property_price
                    )

                    budget = float(
                        budget
                    )


                    # -----------------------------------------
                    # Within budget
                    # -----------------------------------------

                    if property_price <= budget:

                        difference = (
                            budget
                            - property_price
                        )

                        percentage = (
                            difference
                            / budget
                        )


                        if percentage >= 0.30:

                            score += 20

                        elif percentage >= 0.15:

                            score += 18

                        elif percentage >= 0.05:

                            score += 16

                        else:

                            score += 14


                    # -----------------------------------------
                    # Slightly above budget
                    # -----------------------------------------

                    else:

                        over_percentage = (
                            property_price
                            - budget
                        ) / budget


                        if over_percentage <= 0.05:

                            score += 8

                        elif over_percentage <= 0.10:

                            score += 4

                        elif over_percentage <= 0.20:

                            score -= 5

                        else:

                            score -= 15


                except (
                    TypeError,
                    ValueError
                ):

                    pass


            # =================================================
            # STORE SCORE
            # =================================================

            property_item["_match_score"] = score


            ranked_properties.append(
                property_item
            )


        # ====================================================
        # SORT
        # ====================================================

        ranked_properties.sort(
            key=lambda item:
                item.get(
                    "_match_score",
                    0
                ),
            reverse=True
        )


        return ranked_properties


    # ========================================================
    # UPDATE
    # ========================================================

    def update_property(
        self,
        property_id,
        updates
    ):

        updates["updated_at"] = (
            datetime.utcnow()
        )

        result = self.collection.update_one(

            {
                "_id": ObjectId(property_id)
            },

            {
                "$set": updates
            }
        )

        return (
            result.modified_count > 0
        )


    # ========================================================
    # DELETE
    # ========================================================

    def delete_property(
        self,
        property_id
    ):

        result = self.collection.delete_one(

            {
                "_id": ObjectId(property_id)
            }
        )

        return (
            result.deleted_count > 0
        )