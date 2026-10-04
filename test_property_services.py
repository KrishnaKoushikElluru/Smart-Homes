"""
Unit tests for services/property_services.py's
claim_nearby_facilities_enrichment() (Stage 1 - the atomic guard that
prevents two enrichment workers from ever running concurrently for the
same property).

Only this one method is tested here - the rest of PropertyService
(create_property, get_property, ranked_search, filtered_search, etc.)
is exercised indirectly throughout the existing suite via its real
callers and is unchanged by this phase.

A minimal FakeCollection simulates just the two conditions this method
actually filters on (_id match, nearby_facilities_metadata.status !=
"pending") - matching this project's established convention of small,
purpose-built fakes rather than a full in-memory MongoDB (see
test_osm_location_service.py's FakeCollection).
"""

import unittest
from datetime import datetime
from types import SimpleNamespace

from bson import ObjectId

from services.property_services import PropertyService


class FakeUpdateResult:

    def __init__(self, modified_count):
        self.modified_count = modified_count


class FakeCollection:
    """Simulates just enough of pymongo.Collection.update_one() to
    exercise claim_nearby_facilities_enrichment()'s real filter logic:
    an exact _id match, AND nearby_facilities_metadata.status being
    either absent or not equal to "pending" (the actual condition that
    method sends to Mongo)."""

    def __init__(self, docs=None):
        self.docs = docs or {}  # str(_id) -> document dict

    def update_one(self, filt, update):

        doc_id = str(filt["_id"])
        doc = self.docs.get(doc_id)

        if doc is None:
            return FakeUpdateResult(0)

        status_filter = filt.get("nearby_facilities_metadata.status")
        current_status = (doc.get("nearby_facilities_metadata") or {}).get("status")

        if status_filter is not None:
            not_equal_to = status_filter.get("$ne")
            if current_status == not_equal_to:
                return FakeUpdateResult(0)  # current status IS "pending" - claim fails

        doc.update(update["$set"])
        return FakeUpdateResult(1)


def make_property_service(docs=None):
    service = PropertyService.__new__(PropertyService)  # bypass __init__ (no real Mongo)
    service.collection = FakeCollection(docs)
    return service


class ClaimNearbyFacilitiesEnrichmentTests(unittest.TestCase):

    def test_claim_succeeds_for_property_with_no_metadata_yet(self):
        property_id = str(ObjectId())
        service = make_property_service({property_id: {"_id": property_id}})

        claimed = service.claim_nearby_facilities_enrichment(
            property_id, {"status": "pending"}
        )

        self.assertTrue(claimed)
        self.assertEqual(service.collection.docs[property_id]["nearby_facilities_metadata"]["status"], "pending")

    def test_claim_succeeds_for_property_previously_completed(self):
        property_id = str(ObjectId())
        service = make_property_service({
            property_id: {"_id": property_id, "nearby_facilities_metadata": {"status": "completed"}}
        })

        claimed = service.claim_nearby_facilities_enrichment(
            property_id, {"status": "pending"}
        )

        self.assertTrue(claimed)

    def test_claim_succeeds_for_property_previously_failed(self):
        property_id = str(ObjectId())
        service = make_property_service({
            property_id: {"_id": property_id, "nearby_facilities_metadata": {"status": "failed"}}
        })

        claimed = service.claim_nearby_facilities_enrichment(
            property_id, {"status": "pending"}
        )

        self.assertTrue(claimed)

    def test_claim_fails_when_already_pending(self):
        # This is the core guarantee: a second caller must never be
        # able to claim a property that's already being worked on.
        property_id = str(ObjectId())
        service = make_property_service({
            property_id: {"_id": property_id, "nearby_facilities_metadata": {"status": "pending"}}
        })

        claimed = service.claim_nearby_facilities_enrichment(
            property_id, {"status": "pending", "attempt": 2}
        )

        self.assertFalse(claimed)
        # The original pending record must be left untouched by the failed claim.
        self.assertNotIn("attempt", service.collection.docs[property_id]["nearby_facilities_metadata"])

    def test_claim_fails_for_nonexistent_property(self):
        service = make_property_service({})

        claimed = service.claim_nearby_facilities_enrichment(
            str(ObjectId()), {"status": "pending"}
        )

        self.assertFalse(claimed)

    def test_only_one_of_two_sequential_claims_succeeds(self):
        # Simulates two callers racing to claim the same property - only
        # the first should win; this test drives them sequentially
        # (the underlying atomicity guarantee is MongoDB's own, not
        # something a single-process unit test can prove under real
        # concurrency) but confirms the STATE TRANSITION logic that
        # atomicity depends on is correct.
        property_id = str(ObjectId())
        service = make_property_service({property_id: {"_id": property_id}})

        first_claim = service.claim_nearby_facilities_enrichment(property_id, {"status": "pending", "who": "first"})
        second_claim = service.claim_nearby_facilities_enrichment(property_id, {"status": "pending", "who": "second"})

        self.assertTrue(first_claim)
        self.assertFalse(second_claim)
        self.assertEqual(service.collection.docs[property_id]["nearby_facilities_metadata"]["who"], "first")


class OwnerScopedFakeCollection(FakeCollection):
    """Extends FakeCollection with just enough real-Mongo-shaped
    behavior for update_property_for_owner()'s tests: (a) the
    "seller.user_id" equality condition the ownership check actually
    depends on, and (b) applying a dotted-path $set
    ("listing.price": 30000) into the nested document the same way
    real MongoDB does - FakeCollection's base update_one() only ever
    needed a flat $set before, so that part is new here rather than
    duplicated from it."""

    def update_one(self, filt, update):

        doc_id = str(filt["_id"])
        doc = self.docs.get(doc_id)

        if doc is None:
            return FakeUpdateResult(0)

        owner_filter = filt.get("seller.user_id")

        if owner_filter is not None:
            current_owner = (doc.get("seller") or {}).get("user_id")
            if current_owner != owner_filter:
                return FakeUpdateResult(0)  # the real security boundary

        for dotted_key, value in update["$set"].items():
            parts = dotted_key.split(".")
            target = doc
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value

        return FakeUpdateResult(1)


def make_owner_scoped_property_service(docs=None):
    service = PropertyService.__new__(PropertyService)
    service.collection = OwnerScopedFakeCollection(docs)
    return service


class UpdatePropertyForOwnerTests(unittest.TestCase):
    """Direct unit tests for services/property_services.py's
    update_property_for_owner() - the Edit Listing feature's actual
    security boundary (routes/property_routes.py's update_listing()
    also pre-checks ownership at the app level, but THIS is what makes
    that check non-bypassable: the MongoDB update filter itself
    requires both the correct _id AND the correct seller.user_id)."""

    OWNER_ID = "user-1"
    OTHER_USER_ID = "user-2"

    def _make_doc(self, property_id, owner_id):
        return {
            "_id": property_id,
            "seller": {"user_id": owner_id, "username": "owner"},
            "listing": {"status": "active", "price": 25000},
            "property": {"bhk": 2},
        }

    def test_owner_update_succeeds_and_is_reflected_in_the_document(self):
        property_id = str(ObjectId())
        service = make_owner_scoped_property_service(
            {property_id: self._make_doc(property_id, self.OWNER_ID)}
        )

        updated = service.update_property_for_owner(
            property_id, self.OWNER_ID,
            {"listing.price": 30000, "property.bhk": 3},
        )

        self.assertTrue(updated)
        doc = service.collection.docs[property_id]
        self.assertEqual(doc["listing"]["price"], 30000)
        self.assertEqual(doc["property"]["bhk"], 3)

    def test_update_by_a_different_user_is_rejected_at_the_mongo_filter(self):
        property_id = str(ObjectId())
        service = make_owner_scoped_property_service(
            {property_id: self._make_doc(property_id, self.OWNER_ID)}
        )

        updated = service.update_property_for_owner(
            property_id, self.OTHER_USER_ID,
            {"listing.price": 999999},
        )

        self.assertFalse(updated)
        # The document must be completely untouched by the rejected attempt.
        doc = service.collection.docs[property_id]
        self.assertEqual(doc["listing"]["price"], 25000)

    def test_update_for_a_nonexistent_property_is_rejected(self):
        service = make_owner_scoped_property_service({})

        updated = service.update_property_for_owner(
            str(ObjectId()), self.OWNER_ID, {"listing.price": 30000}
        )

        self.assertFalse(updated)

    def test_updated_at_is_refreshed_on_a_successful_update(self):
        property_id = str(ObjectId())
        service = make_owner_scoped_property_service(
            {property_id: self._make_doc(property_id, self.OWNER_ID)}
        )

        service.update_property_for_owner(
            property_id, self.OWNER_ID, {"listing.price": 30000}
        )

        self.assertIsInstance(
            service.collection.docs[property_id]["updated_at"], datetime
        )


class EditedPropertySearchConsistencyTests(unittest.TestCase):
    """Covers the spec's explicit search-consistency example: after
    editing BHK 2->3 and price 25000->30000, a hard-filter query for
    "3 BHK under 30000" must match the edited property and a query for
    "2 BHK under 25000" must not.

    Deliberately does NOT touch services/search_orchestration.py or
    the NLP parser (out of scope for this feature) - it calls
    PropertyService.filtered_search() directly with the exact
    mongo_filter shape orchestrate_search() builds from parsed hard
    requirements ({field: value} / {field: {"$lte": n}} plus the
    existing "listing.status": "active" filter), which is the real
    integration point between NLP filtering and the property
    documents update_listing() writes to. This proves the UPDATED
    DOCUMENT is what a hard-filter search actually sees, without
    re-testing NLP parsing itself."""

    def _make_find_collection(self, docs):

        class FindOnlyFakeCollection:
            def __init__(self, documents):
                self.documents = documents

            def find(self, mongo_filter):
                def matches(doc):
                    for key, condition in mongo_filter.items():
                        value = doc
                        for part in key.split("."):
                            value = (value or {}).get(part)
                        if isinstance(condition, dict) and "$lte" in condition:
                            if value is None or value > condition["$lte"]:
                                return False
                        elif value != condition:
                            return False
                    return True

                return [doc for doc in self.documents.values() if matches(doc)]

        return FindOnlyFakeCollection(docs)

    def _make_service_with_edited_property(self, property_id):
        # Represents the document AFTER update_listing() has applied
        # the owner's edit (BHK 2 -> 3, price 25000 -> 30000) - exactly
        # the "property.bhk" / "listing.price" fields
        # update_property_for_owner() actually writes.
        doc = {
            "_id": property_id,
            "listing": {"status": "active", "price": 30000},
            "property": {"bhk": 3},
        }
        service = PropertyService.__new__(PropertyService)
        service.collection = self._make_find_collection({property_id: doc})
        return service

    def test_search_for_new_bhk_and_price_finds_the_edited_property(self):
        property_id = str(ObjectId())
        service = self._make_service_with_edited_property(property_id)

        results = service.filtered_search({
            "listing.status": "active",
            "property.bhk": 3,
            "listing.price": {"$lte": 30000},
        })

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["_id"], property_id)

    def test_search_for_the_old_bhk_and_price_no_longer_finds_it(self):
        property_id = str(ObjectId())
        service = self._make_service_with_edited_property(property_id)

        results = service.filtered_search({
            "listing.status": "active",
            "property.bhk": 2,
            "listing.price": {"$lte": 25000},
        })

        self.assertEqual(results, [])


if __name__ == "__main__":
    unittest.main()
