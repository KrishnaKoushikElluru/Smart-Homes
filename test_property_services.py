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


if __name__ == "__main__":
    unittest.main()
