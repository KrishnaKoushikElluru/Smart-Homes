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
    # INDEXES
    #
    # Idempotent: safe to call on every app startup. Supports the
    # listing phase's own lookups (owner's listings, active feed)
    # as well as the existing search/ranking queries, without
    # creating redundant indexes.
    # ========================================================

    def ensure_indexes(self):

        self.collection.create_index("seller.user_id")

        self.collection.create_index("listing.type")

        self.collection.create_index("listing.status")

        self.collection.create_index("property.type")

        self.collection.create_index("location.city")

        self.collection.create_index("location.locality")

        self.collection.create_index("listing.price")

        self.collection.create_index("property.bhk")

        self.collection.create_index(
            [("location.coordinates", "2dsphere")]
        )

        # Phase 4.0 (services/nearby_facility_service.py): a multikey
        # 2dsphere index over each embedded nearby_facilities[] entry's
        # "coordinates" field. Not queried by anything in this phase -
        # added now purely so the data model is ready for a future
        # "property within 1 km of a school" style search without a
        # migration. A facility whose coordinates couldn't be resolved
        # (coordinates: None - see nearby_facility_service.py) is
        # simply not included in this index; that's normal, not an
        # error, for a multikey geospatial index over an array.
        self.collection.create_index(
            [("nearby_facilities.coordinates", "2dsphere")]
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
    # FILTERED SEARCH (Phase 3 - real MongoDB filter query)
    #
    # Distinct from ranked_search() above: this issues a genuine
    # MongoDB find() with real operators ($gte/$lte/$near/etc, built by
    # services/search_orchestration.py from a parsed natural-language
    # query) instead of fetching every active property and scoring it
    # in Python. Kept as its own thin method - not a replacement for
    # ranked_search() and not used by the existing structured search
    # path - so the existing behavior stays completely unaffected.
    # Deliberately thin/unopinionated: the caller (see
    # services/search_orchestration.build_mongo_filter()) is
    # responsible for including "listing.status": "active" in the
    # filter it passes in - this method does not add it implicitly.
    # ========================================================

    def filtered_search(
        self,
        mongo_filter
    ):

        return list(
            self.collection.find(
                mongo_filter
            )
        )


    # ========================================================
    # COUNT (Stage 2 - services/search_orchestration.py uses this to
    # report an honest "how many active listings aren't enriched yet"
    # caveat when a nearby-facility search runs, rather than silently
    # implying a complete answer)
    # ========================================================

    def count(
        self,
        mongo_filter
    ):

        return self.collection.count_documents(
            mongo_filter
        )


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
    # CLAIM NEARBY-FACILITY ENRICHMENT (Stage 1 - thread safety)
    #
    # An atomic, single-document conditional update: sets
    # nearby_facilities_metadata to `pending_metadata` ONLY IF the
    # property is not ALREADY marked "pending" - guaranteeing at most
    # one enrichment worker is ever started for a given property, even
    # under concurrent/duplicate calls (e.g. a duplicate registration
    # request, or - in a future multi-process deployment - two
    # different worker processes racing). This guarantee comes from
    # MongoDB's own atomic single-document update, not from an
    # in-process lock, so it holds even across multiple app processes,
    # not just multiple threads within one.
    #
    # {"nearby_facilities_metadata.status": {"$ne": "pending"}} also
    # correctly matches a brand-new property with no
    # nearby_facilities_metadata field at all yet - a missing field is
    # never equal to "pending", so the very first claim always
    # succeeds.
    # ========================================================

    def claim_nearby_facilities_enrichment(
        self,
        property_id,
        pending_metadata
    ):
        """Returns True if this call successfully claimed enrichment for
        property_id (the caller should proceed to start a worker), False
        if another call already has it pending (the caller should skip
        starting a second one)."""

        result = self.collection.update_one(

            {
                "_id": ObjectId(property_id),
                "nearby_facilities_metadata.status": {"$ne": "pending"}
            },

            {
                "$set": {
                    "nearby_facilities_metadata": pending_metadata,
                    "updated_at": datetime.utcnow()
                }
            }
        )

        return (
            result.modified_count > 0
        )


    # ========================================================
    # UPDATE STATUS
    # ========================================================

    def update_status(
        self,
        property_id,
        status
    ):

        return self.update_property(
            property_id,
            {
                "listing.status": status
            }
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