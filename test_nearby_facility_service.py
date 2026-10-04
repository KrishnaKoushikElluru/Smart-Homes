"""
Unit tests for services/nearby_facility_service.py (Phase 4.0: nearby-
facility enrichment).

No network access needed - services.mappls_service.find_nearby_places
is patched. PropertyService is a fake in-memory store (no real
MongoDB), matching the FakeCollection pattern used across this
project's test suite.

Mappls is the SOLE discovery/distance provider - there is no OSM/
coordinate-resolution step (see services/nearby_facility_service.py's
module docstring for the architecture decision and why the OSM step
was removed). NoCoordinateResolutionTests below proves this directly.
"""

import unittest
from unittest.mock import patch

from services import nearby_facility_service as nfs


# ============================================================
# FAKES
# ============================================================

class FakePropertyService:
    """In-memory stand-in for services.property_services.PropertyService -
    only the methods enrich_property_nearby_facilities() and (Stage 1)
    start_background_enrichment() actually call."""

    def __init__(self, properties=None):
        self.properties = properties or {}
        self.update_calls = []
        self.get_calls = []
        self.claim_calls = []
        self.raise_on_get = None
        self.raise_on_update = None
        self.raise_on_claim = None

    def get_property(self, property_id):
        self.get_calls.append(property_id)
        if self.raise_on_get:
            raise self.raise_on_get
        return self.properties.get(property_id)

    def update_property(self, property_id, updates):
        self.update_calls.append((property_id, updates))
        if self.raise_on_update:
            raise self.raise_on_update
        self.properties.setdefault(property_id, {}).update(updates)
        return True

    def claim_nearby_facilities_enrichment(self, property_id, pending_metadata):
        """Mirrors the real atomic-claim semantics: succeeds unless the
        property is already marked "pending"."""
        self.claim_calls.append((property_id, pending_metadata))
        if self.raise_on_claim:
            raise self.raise_on_claim
        existing = self.properties.get(property_id, {})
        current_status = (existing.get("nearby_facilities_metadata") or {}).get("status")
        if current_status == "pending":
            return False
        self.properties.setdefault(property_id, {})["nearby_facilities_metadata"] = pending_metadata
        return True
        return True


def property_with_coordinates(lat=12.8406, lon=80.1538):
    return {
        "_id": "p1",
        "location": {
            "coordinates": {"type": "Point", "coordinates": [lon, lat]},
        },
    }


def mappls_matched(places):
    return {"status": "matched", "places": places, "error": None}


def mappls_no_match():
    return {"status": "no_match", "places": [], "error": None}


def mappls_error(msg="Mappls request failed or timed out."):
    return {"status": "error", "places": [], "error": msg}


def raw_place(name="Test Gym", eloc="ABC123", distance_m=500, address="Some Rd", place_type="POI"):
    return {
        "place_name": name, "place_address": address, "eloc": eloc,
        "type": place_type, "distance_m": distance_m, "order_index": 1,
    }


# ============================================================
# PROPERTY-LEVEL GATING: coordinates present/absent
# ============================================================

class PropertyGatingTests(unittest.TestCase):

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_property_with_valid_coordinates_triggers_enrichment(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_no_match()
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key",
        )

        self.assertTrue(mock_find_nearby.called)
        self.assertIn(result["status"], ("completed", "partial", "failed"))
        self.assertNotEqual(result["status"], "skipped")

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_property_without_coordinates_does_not_attempt_enrichment(self, mock_find_nearby):
        prop_service = FakePropertyService({"p1": {"_id": "p1", "location": {}}})

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key",
        )

        mock_find_nearby.assert_not_called()
        self.assertEqual(result["status"], "skipped")
        self.assertEqual(prop_service.update_calls, [])

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_property_with_invalid_coordinates_does_not_attempt_enrichment(self, mock_find_nearby):
        prop = {"_id": "p1", "location": {"coordinates": {"type": "Point", "coordinates": [999, 999]}}}
        prop_service = FakePropertyService({"p1": prop})

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key",
        )

        mock_find_nearby.assert_not_called()
        self.assertEqual(result["status"], "skipped")

    def test_nonexistent_property_is_skipped_not_failed(self):
        prop_service = FakePropertyService({})

        result = nfs.enrich_property_nearby_facilities(
            "missing", prop_service, "key",
        )

        self.assertEqual(result["status"], "skipped")

    def test_get_property_raising_produces_failed_not_a_crash(self):
        prop_service = FakePropertyService({})
        prop_service.raise_on_get = RuntimeError("mongo down")

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key",
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("mongo down", result["error"])


# ============================================================
# NORMALIZATION / CATEGORY PRESERVATION
# ============================================================

class NormalizationTests(unittest.TestCase):

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_facilities_are_normalized_and_category_is_preserved(self, mock_find_nearby):
        def side_effect(keyword, ref_location, radius_m, api_key):
            if keyword == "gym":
                return mappls_matched([raw_place(name="Test Gym", eloc="G1", distance_m=750)])
            return mappls_no_match()

        mock_find_nearby.side_effect = side_effect
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key",
            categories={"gym": "gym", "hospital": "hospital"},
        )

        self.assertEqual(result["status"], "completed")
        stored = prop_service.properties["p1"]["nearby_facilities"]
        gym_entries = [f for f in stored if f["category"] == "gym"]
        self.assertEqual(len(gym_entries), 1)
        self.assertEqual(gym_entries[0]["name"], "Test Gym")
        self.assertEqual(gym_entries[0]["distance_m"], 750.0)
        self.assertEqual(gym_entries[0]["provider_id"], "G1")
        self.assertEqual(gym_entries[0]["source"], "mappls")

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_malformed_place_without_name_is_skipped_not_fatal(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_matched([
            {"place_name": "", "eloc": "X1", "distance_m": 100},  # no usable name
            raw_place(name="Valid Place", eloc="X2", distance_m=200),
        ])
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key",
            categories={"gym": "gym"},
        )

        self.assertEqual(result["facility_count"], 1)
        stored = prop_service.properties["p1"]["nearby_facilities"]
        self.assertEqual(stored[0]["name"], "Valid Place")


# ============================================================
# NO COORDINATE RESOLUTION (architecture decision: Mappls is the sole
# discovery/distance provider - see services/nearby_facility_service.py's
# module docstring)
# ============================================================

class NoCoordinateResolutionTests(unittest.TestCase):

    def test_enrich_property_nearby_facilities_has_no_osm_parameter(self):
        import inspect
        params = inspect.signature(nfs.enrich_property_nearby_facilities).parameters
        self.assertNotIn("osm_service", params)
        self.assertNotIn("coordinate_resolution_limit_per_category", params)

    def test_start_background_enrichment_has_no_osm_parameter(self):
        import inspect
        params = inspect.signature(nfs.start_background_enrichment).parameters
        self.assertNotIn("osm_service", params)
        self.assertNotIn("coordinate_resolution_limit_per_category", params)

    def test_module_has_no_osm_location_service_dependency(self):
        import services.nearby_facility_service as module
        self.assertFalse(hasattr(module, "osm_location_service"))
        self.assertFalse(hasattr(module, "OSMLocationService"))
        self.assertFalse(hasattr(module, "_resolve_coordinates_for_place"))
        self.assertFalse(hasattr(module, "DEFAULT_COORDINATE_RESOLUTION_LIMIT_PER_CATEGORY"))

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_stored_facility_has_no_coordinate_fields(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_matched(
            [raw_place(name="Test Gym", eloc="G1", distance_m=750)]
        )
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key", categories={"gym": "gym"},
        )

        stored = prop_service.properties["p1"]["nearby_facilities"][0]
        for key in ("latitude", "longitude", "coordinates", "coordinate_source"):
            self.assertNotIn(key, stored)
        self.assertEqual(stored["distance_m"], 750.0)
        self.assertEqual(stored["name"], "Test Gym")
        self.assertEqual(stored["provider_id"], "G1")

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_only_mappls_is_ever_called_not_any_other_provider(self, mock_find_nearby):
        """Belt-and-braces: even with multiple facilities across
        multiple categories, mappls_service.find_nearby_places is the
        only external call this module ever makes - one call per
        category, nothing else."""
        mock_find_nearby.return_value = mappls_matched([
            raw_place(name="Gym A", eloc="A", distance_m=100),
            raw_place(name="Gym B", eloc="B", distance_m=200),
        ])
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key", categories={"gym": "gym", "hospital": "hospital"},
        )

        self.assertEqual(mock_find_nearby.call_count, 2)  # one per category, nothing more
        self.assertEqual(result["status"], "completed")
        stored = prop_service.properties["p1"]["nearby_facilities"]
        self.assertTrue(all("coordinates" not in f for f in stored))


# ============================================================
# DISTANCE / VALIDATION
# ============================================================

class DistanceAndValidationTests(unittest.TestCase):

    def test_is_valid_coordinate_accepts_real_values(self):
        self.assertTrue(nfs._is_valid_coordinate(12.84, 80.15))
        self.assertTrue(nfs._is_valid_coordinate(-90, -180))
        self.assertTrue(nfs._is_valid_coordinate(90, 180))

    def test_is_valid_coordinate_rejects_out_of_range(self):
        self.assertFalse(nfs._is_valid_coordinate(999, 80.15))
        self.assertFalse(nfs._is_valid_coordinate(12.84, -999))

    def test_is_valid_coordinate_rejects_non_numeric(self):
        self.assertFalse(nfs._is_valid_coordinate("abc", 80.15))
        self.assertFalse(nfs._is_valid_coordinate(None, None))

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_distance_m_matches_mappls_provider_distance_exactly(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_matched([raw_place(distance_m=1234.5)])
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key", categories={"gym": "gym"},
        )

        stored = prop_service.properties["p1"]["nearby_facilities"][0]
        self.assertEqual(stored["distance_m"], 1234.5)


# ============================================================
# DEDUPLICATION
# ============================================================

class DeduplicationTests(unittest.TestCase):

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_duplicate_eloc_within_a_category_is_removed(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_matched([
            raw_place(name="Gym A", eloc="SAME", distance_m=100),
            raw_place(name="Gym A Duplicate Listing", eloc="SAME", distance_m=100),
        ])
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key", categories={"gym": "gym"},
        )

        self.assertEqual(result["facility_count"], 1)

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_distinct_eloc_are_both_kept_even_with_similar_names(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_matched([
            raw_place(name="Gold's Gym", eloc="A1", distance_m=100),
            raw_place(name="Gold's Gym Annex", eloc="A2", distance_m=150),
        ])
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key", categories={"gym": "gym"},
        )

        # Different businesses (different eLoc) must never be merged
        # just because their names are similar.
        self.assertEqual(result["facility_count"], 2)

    def test_dedupe_falls_back_to_normalized_name_when_no_provider_id(self):
        places = [
            {"name": "Same Place", "category": "gym", "provider_id": None,
             "distance_m": 100, "address": None, "source": "mappls",
             "provider_type": None, "fetched_at": None, "search_radius_m": 2000},
            {"name": "same place", "category": "gym", "provider_id": None,
             "distance_m": 100, "address": None, "source": "mappls",
             "provider_type": None, "fetched_at": None, "search_radius_m": 2000},
        ]
        deduped = nfs._dedupe_places(places)
        self.assertEqual(len(deduped), 1)


# ============================================================
# EMPTY RESULTS
# ============================================================

class EmptyResultTests(unittest.TestCase):

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_no_match_category_stores_empty_list_not_an_error(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_no_match()
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key", categories={"gym": "gym"},
        )

        self.assertEqual(result["status"], "completed")
        self.assertEqual(result["facility_count"], 0)
        self.assertEqual(result["categories_failed"], {})
        stored = prop_service.properties["p1"]["nearby_facilities"]
        self.assertEqual(stored, [])


# ============================================================
# FAILURE HANDLING / ENRICHMENT STATUS
# ============================================================

class FailureHandlingTests(unittest.TestCase):

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_mappls_failure_for_all_categories_does_not_raise_and_marks_failed(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_error("Mappls request failed or timed out.")
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key",
            categories={"gym": "gym", "hospital": "hospital"},
        )

        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["facility_count"], 0)
        self.assertIn("gym", result["categories_failed"])
        self.assertIn("hospital", result["categories_failed"])
        # Property document is still written (empty facilities + failed
        # metadata) - registration itself never depends on this.
        self.assertIn("p1", prop_service.properties)

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_partial_failure_preserves_successful_categories(self, mock_find_nearby):
        def side_effect(keyword, ref_location, radius_m, api_key):
            if keyword == "gym":
                return mappls_matched([raw_place(name="Test Gym", eloc="G1")])
            return mappls_error("boom")

        mock_find_nearby.side_effect = side_effect
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key",
            categories={"gym": "gym", "hospital": "hospital"},
        )

        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["facility_count"], 1)
        self.assertIn("hospital", result["categories_failed"])
        self.assertNotIn("gym", result["categories_failed"])
        stored = prop_service.properties["p1"]["nearby_facilities"]
        self.assertEqual(len(stored), 1)
        self.assertEqual(stored[0]["category"], "gym")

    def test_enrichment_never_raises_even_on_unexpected_property_shape(self):
        prop_service = FakePropertyService({"p1": {"_id": "p1"}})  # no "location" key at all
        try:
            result = nfs.enrich_property_nearby_facilities(
                "p1", prop_service, "key",
            )
        except Exception as exc:  # pragma: no cover - the whole point is this must not happen
            self.fail(f"enrich_property_nearby_facilities raised: {exc}")
        self.assertEqual(result["status"], "skipped")

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_persistence_failure_is_reported_not_swallowed(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_no_match()
        prop_service = FakePropertyService({"p1": property_with_coordinates()})
        prop_service.raise_on_update = RuntimeError("mongo write failed")

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key", categories={"gym": "gym"},
        )

        self.assertEqual(result["status"], "failed")
        self.assertIn("mongo write failed", result["error"])


# ============================================================
# ENRICHMENT METADATA
# ============================================================

class MetadataTests(unittest.TestCase):

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_metadata_fields_are_correct_on_success(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_matched([raw_place(name="Test Gym", eloc="G1")])
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key",
            categories={"gym": "gym"}, radius_km=1.5,
        )

        self.assertEqual(result["source"], "mappls")
        self.assertEqual(result["radius_m"], 1500.0)
        self.assertEqual(result["facility_count"], 1)
        self.assertEqual(result["categories_requested"], ["gym"])
        self.assertIsNotNone(result["enriched_at"])

        stored_metadata = prop_service.properties["p1"]["nearby_facilities_metadata"]
        self.assertEqual(stored_metadata, result)

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_each_facility_records_its_own_search_radius(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_matched([raw_place(name="Test Gym", eloc="G1")])
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key",
            categories={"gym": "gym"}, radius_km=3.0,
        )

        stored = prop_service.properties["p1"]["nearby_facilities"][0]
        self.assertEqual(stored["search_radius_m"], 3000.0)


# ============================================================
# REPEATED ENRICHMENT (no uncontrolled duplication)
# ============================================================

class RepeatedEnrichmentTests(unittest.TestCase):

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_re_running_enrichment_replaces_rather_than_appends(self, mock_find_nearby):
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        mock_find_nearby.return_value = mappls_matched([raw_place(name="Gym A", eloc="A", distance_m=100)])
        nfs.enrich_property_nearby_facilities("p1", prop_service, "key", categories={"gym": "gym"})

        mock_find_nearby.return_value = mappls_matched([raw_place(name="Gym B", eloc="B", distance_m=200)])
        result = nfs.enrich_property_nearby_facilities("p1", prop_service, "key", categories={"gym": "gym"})

        stored = prop_service.properties["p1"]["nearby_facilities"]
        self.assertEqual(len(stored), 1)  # replaced, not appended to the first run's result
        self.assertEqual(stored[0]["name"], "Gym B")
        self.assertEqual(result["facility_count"], 1)


# ============================================================
# CONFIGURABLE RADIUS
# ============================================================

class RadiusConfigurationTests(unittest.TestCase):

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_configured_radius_is_passed_to_mappls_in_meters(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_no_match()
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key",
            categories={"gym": "gym"}, radius_km=4.0,
        )

        _, kwargs_or_args = mock_find_nearby.call_args
        # find_nearby_places(keyword, ref_location, radius_m, api_key)
        call_args = mock_find_nearby.call_args[0]
        self.assertEqual(call_args[2], 4000.0)

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_default_radius_used_when_not_specified(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_no_match()
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key", categories={"gym": "gym"},
        )

        self.assertEqual(result["radius_m"], nfs.DEFAULT_RADIUS_KM * 1000.0)


# ============================================================
# PROVIDER IDENTITY PRESERVATION
# ============================================================

class ProviderIdentityTests(unittest.TestCase):

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_eloc_and_type_are_preserved_when_available(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_matched([
            raw_place(name="Test Gym", eloc="XYZ789", place_type="POI", distance_m=100)
        ])
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key", categories={"gym": "gym"},
        )

        stored = prop_service.properties["p1"]["nearby_facilities"][0]
        self.assertEqual(stored["provider_id"], "XYZ789")
        self.assertEqual(stored["provider_type"], "POI")

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_missing_eloc_does_not_crash_and_produces_none(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_matched([
            {"place_name": "No Eloc Place", "place_address": None, "eloc": None,
             "type": None, "distance_m": 100, "order_index": 1}
        ])
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        result = nfs.enrich_property_nearby_facilities(
            "p1", prop_service, "key", categories={"gym": "gym"},
        )

        self.assertEqual(result["facility_count"], 1)
        stored = prop_service.properties["p1"]["nearby_facilities"][0]
        self.assertIsNone(stored["provider_id"])


# ============================================================
# STAGE 1: BACKGROUND EXECUTION
# ============================================================

class BuildPendingMetadataTests(unittest.TestCase):

    def test_pending_metadata_has_pending_status_and_null_enriched_at(self):
        metadata = nfs.build_pending_metadata()
        self.assertEqual(metadata["status"], "pending")
        self.assertIsNone(metadata["enriched_at"])
        self.assertIsNotNone(metadata["queued_at"])
        self.assertEqual(metadata["facility_count"], 0)

    def test_pending_metadata_reflects_requested_categories_and_radius(self):
        metadata = nfs.build_pending_metadata(categories={"gym": "gym"}, radius_km=1.5)
        self.assertEqual(metadata["categories_requested"], ["gym"])
        self.assertEqual(metadata["radius_m"], 1500.0)


class StartBackgroundEnrichmentTests(unittest.TestCase):

    def test_registration_does_not_wait_for_the_full_enrichment(self):
        # The core proof that this is non-blocking: enrich_property_nearby_facilities
        # is made to block on an Event that the test itself controls: if
        # start_background_enrichment() returned only after that
        # function finished, this test would hang and time out.
        import threading as threading_module

        release_worker = threading_module.Event()
        worker_started = threading_module.Event()

        def slow_enrichment(*args, **kwargs):
            worker_started.set()
            release_worker.wait(timeout=5)
            return {"status": "completed"}

        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        with patch("services.nearby_facility_service.enrich_property_nearby_facilities", side_effect=slow_enrichment):

            thread = nfs.start_background_enrichment(
                "p1", prop_service, "key",
            )

            # start_background_enrichment() must already have returned here,
            # BEFORE the worker function has been allowed to finish.
            self.assertIsNotNone(thread)
            worker_started.wait(timeout=2)  # give the thread a moment to actually start
            self.assertTrue(worker_started.is_set())

            release_worker.set()
            thread.join(timeout=5)

    def test_property_is_marked_pending_synchronously_before_thread_finishes(self):
        import threading as threading_module

        release_worker = threading_module.Event()

        def slow_enrichment(*args, **kwargs):
            release_worker.wait(timeout=5)
            return {"status": "completed"}

        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        with patch("services.nearby_facility_service.enrich_property_nearby_facilities", side_effect=slow_enrichment):

            thread = nfs.start_background_enrichment("p1", prop_service, "key")

            # Pending must already be visible - written by
            # start_background_enrichment() itself, synchronously,
            # before the thread was even started.
            self.assertEqual(
                prop_service.properties["p1"]["nearby_facilities_metadata"]["status"], "pending"
            )

            release_worker.set()
            thread.join(timeout=5)

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_worker_receives_the_required_dependencies_and_transitions_pending_to_completed(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_matched([raw_place(name="Test Gym", eloc="G1")])
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        thread = nfs.start_background_enrichment(
            "p1", prop_service, "real-key", categories={"gym": "gym"},
        )
        thread.join(timeout=5)

        final_metadata = prop_service.properties["p1"]["nearby_facilities_metadata"]
        self.assertEqual(final_metadata["status"], "completed")
        self.assertEqual(final_metadata["facility_count"], 1)
        # Confirms the real Mappls call actually received the key passed
        # into start_background_enrichment (i.e. the dependency really
        # reached the worker, not just a fake/default).
        mock_find_nearby.assert_called_with("gym", "12.8406,80.1538", 2000.0, "real-key")

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_worker_transitions_pending_to_partial_on_partial_failure(self, mock_find_nearby):
        def side_effect(keyword, ref_location, radius_m, api_key):
            if keyword == "gym":
                return mappls_matched([raw_place(name="Test Gym", eloc="G1")])
            return mappls_error("boom")

        mock_find_nearby.side_effect = side_effect
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        thread = nfs.start_background_enrichment(
            "p1", prop_service, "key",
            categories={"gym": "gym", "hospital": "hospital"},
        )
        thread.join(timeout=5)

        final_metadata = prop_service.properties["p1"]["nearby_facilities_metadata"]
        self.assertEqual(final_metadata["status"], "partial")

    @patch("services.nearby_facility_service.mappls_service.find_nearby_places")
    def test_worker_transitions_pending_to_failed_when_all_categories_fail(self, mock_find_nearby):
        mock_find_nearby.return_value = mappls_error("boom")
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        thread = nfs.start_background_enrichment(
            "p1", prop_service, "key", categories={"gym": "gym"},
        )
        thread.join(timeout=5)

        final_metadata = prop_service.properties["p1"]["nearby_facilities_metadata"]
        self.assertEqual(final_metadata["status"], "failed")

    def test_worker_exception_is_contained_and_recorded_as_failed(self):
        # A raw, unexpected exception from inside enrich_property_nearby_facilities
        # itself (which is documented never to raise, but this proves the
        # background thread's own last-resort safety net works even if
        # that contract is ever violated).
        prop_service = FakePropertyService({"p1": property_with_coordinates()})

        with patch(
            "services.nearby_facility_service.enrich_property_nearby_facilities",
            side_effect=RuntimeError("boom - totally unexpected crash"),
        ):
            thread = nfs.start_background_enrichment("p1", prop_service, "key")
            # The exception must not propagate out of thread.join() / crash the test process.
            thread.join(timeout=5)

        final_metadata = prop_service.properties["p1"]["nearby_facilities_metadata"]
        self.assertEqual(final_metadata["status"], "failed")
        self.assertIn("boom - totally unexpected crash", final_metadata["error"])

    def test_second_call_for_an_already_pending_property_does_not_start_a_second_worker(self):
        prop = property_with_coordinates()
        prop["nearby_facilities_metadata"] = {"status": "pending"}
        prop_service = FakePropertyService({"p1": prop})

        with patch("services.nearby_facility_service.enrich_property_nearby_facilities") as mock_enrich:

            thread = nfs.start_background_enrichment("p1", prop_service, "key")

            self.assertIsNone(thread)
            mock_enrich.assert_not_called()

    def test_claim_failure_due_to_exception_does_not_start_a_worker_or_raise(self):
        prop_service = FakePropertyService({"p1": property_with_coordinates()})
        prop_service.raise_on_claim = RuntimeError("mongo down")

        with patch("services.nearby_facility_service.enrich_property_nearby_facilities") as mock_enrich:

            thread = nfs.start_background_enrichment("p1", prop_service, "key")

            self.assertIsNone(thread)
            mock_enrich.assert_not_called()


# ============================================================
# PROPERTY-DETAILS "NEARBY AMENITIES" DISPLAY
# ============================================================

def stored_facility(name="Tiger Gym", category="gym", distance_m=134.0, address="Gandhi Road, Chennai", **overrides):
    """A realistic stored nearby_facilities[] entry - matches
    _normalize_place()'s actual output shape (no coordinate fields,
    confirmed by NoCoordinateResolutionTests above)."""
    facility = {
        "name": name, "category": category, "address": address, "distance_m": distance_m,
        "source": "mappls", "provider_id": "ABC123", "provider_type": "POI",
        "fetched_at": None, "search_radius_m": 2000.0,
    }
    facility.update(overrides)
    return facility


class FormatDistanceTests(unittest.TestCase):

    def test_meters_shown_for_sub_kilometer_distances(self):
        self.assertEqual(nfs._format_distance(134), "134 m")
        self.assertEqual(nfs._format_distance(780), "780 m")

    def test_kilometers_shown_at_or_above_one_thousand_meters(self):
        self.assertEqual(nfs._format_distance(1200), "1.2 km")
        self.assertEqual(nfs._format_distance(2000), "2 km")  # never "2.0 km"

    def test_missing_or_invalid_distance_returns_none(self):
        self.assertIsNone(nfs._format_distance(None))
        self.assertIsNone(nfs._format_distance("not a number"))
        self.assertIsNone(nfs._format_distance(-50))


class BuildNearbyFacilitiesDisplayTests(unittest.TestCase):

    def _property(self, nearby_facilities=None, metadata_status="completed", **metadata_overrides):
        metadata = {"status": metadata_status, "source": "mappls", "radius_m": 2000.0}
        metadata.update(metadata_overrides)
        return {
            "_id": "p1",
            "nearby_facilities": nearby_facilities if nearby_facilities is not None else [],
            "nearby_facilities_metadata": metadata,
        }

    # ---- Case 1: multiple facilities in one category ----

    def test_multiple_facilities_in_one_category_are_all_returned(self):
        prop = self._property([
            stored_facility(name="Tiger Gym", distance_m=134),
            stored_facility(name="Gold's Gym", distance_m=600),
            stored_facility(name="Cult Fit", distance_m=1200),
        ])

        result = nfs.build_nearby_facilities_display(prop)

        self.assertEqual(result["status"], "ready")
        self.assertEqual(len(result["groups"]), 1)
        gym_group = result["groups"][0]
        self.assertEqual(gym_group["category"], "gym")
        self.assertEqual(len(gym_group["facilities"]), 3)
        # closest first
        self.assertEqual([f["name"] for f in gym_group["facilities"]], ["Tiger Gym", "Gold's Gym", "Cult Fit"])

    # ---- Case 2: multiple categories grouped correctly ----

    def test_multiple_categories_are_grouped_separately_in_canonical_order(self):
        prop = self._property([
            stored_facility(name="ABC Hospital", category="hospital", distance_m=700),
            stored_facility(name="Tiger Gym", category="gym", distance_m=134),
            stored_facility(name="XYZ School", category="school", distance_m=1100),
        ])

        result = nfs.build_nearby_facilities_display(prop)

        self.assertEqual(result["status"], "ready")
        categories = [g["category"] for g in result["groups"]]
        self.assertEqual(set(categories), {"gym", "hospital", "school"})
        # FACILITY_CATEGORIES' own declared order, not insertion order
        expected_order = [c for c in nfs.FACILITY_CATEGORIES if c in categories]
        self.assertEqual(categories, expected_order)
        for group in result["groups"]:
            self.assertEqual(len(group["facilities"]), 1)

    def test_a_category_with_zero_facilities_is_never_rendered(self):
        prop = self._property([stored_facility(name="Tiger Gym", category="gym")])
        result = nfs.build_nearby_facilities_display(prop)
        categories = [g["category"] for g in result["groups"]]
        self.assertNotIn("hospital", categories)
        self.assertEqual(categories, ["gym"])

    # ---- Case 3: no nearby facilities ----

    def test_no_metadata_at_all_is_unavailable_not_broken(self):
        prop = {"_id": "p1"}  # legacy property, never enriched
        result = nfs.build_nearby_facilities_display(prop)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["groups"], [])

    def test_completed_with_zero_facilities_is_empty_not_unavailable(self):
        prop = self._property([], metadata_status="completed")
        result = nfs.build_nearby_facilities_display(prop)
        self.assertEqual(result["status"], "empty")
        self.assertEqual(result["groups"], [])

    def test_none_property_item_is_unavailable(self):
        result = nfs.build_nearby_facilities_display(None)
        self.assertEqual(result["status"], "unavailable")

    # ---- Case 4: missing address ----

    def test_facility_with_missing_address_still_renders_with_name_and_distance(self):
        prop = self._property([stored_facility(name="Tiger Gym", address=None, distance_m=134)])
        result = nfs.build_nearby_facilities_display(prop)
        facility = result["groups"][0]["facilities"][0]
        self.assertEqual(facility["name"], "Tiger Gym")
        self.assertIsNone(facility["address"])
        self.assertEqual(facility["distance_label"], "134 m")

    # ---- Case 5: missing distance ----

    def test_facility_with_missing_distance_has_no_distance_label_but_still_renders(self):
        prop = self._property([stored_facility(name="Tiger Gym", distance_m=None)])
        result = nfs.build_nearby_facilities_display(prop)
        facility = result["groups"][0]["facilities"][0]
        self.assertEqual(facility["name"], "Tiger Gym")
        self.assertIsNone(facility["distance_m"])
        self.assertIsNone(facility["distance_label"])

    def test_facilities_with_missing_distance_sort_after_resolved_ones(self):
        prop = self._property([
            stored_facility(name="No Distance Gym", distance_m=None),
            stored_facility(name="Tiger Gym", distance_m=134),
        ])
        result = nfs.build_nearby_facilities_display(prop)
        names = [f["name"] for f in result["groups"][0]["facilities"]]
        self.assertEqual(names, ["Tiger Gym", "No Distance Gym"])

    # ---- pending / failed / skipped enrichment status ----

    def test_pending_status_is_reported_not_treated_as_empty(self):
        prop = self._property([], metadata_status="pending")
        result = nfs.build_nearby_facilities_display(prop)
        self.assertEqual(result["status"], "pending")
        self.assertEqual(result["groups"], [])

    def test_failed_status_is_reported_not_shown_as_fake_empty_success(self):
        prop = self._property([], metadata_status="failed")
        result = nfs.build_nearby_facilities_display(prop)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["groups"], [])

    def test_skipped_status_is_reported_distinctly(self):
        prop = self._property([], metadata_status="skipped")
        result = nfs.build_nearby_facilities_display(prop)
        self.assertEqual(result["status"], "skipped")

    def test_partial_status_still_shows_the_successful_facilities(self):
        prop = self._property(
            [stored_facility(name="Tiger Gym", category="gym")],
            metadata_status="partial",
        )
        result = nfs.build_nearby_facilities_display(prop)
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["groups"][0]["category"], "gym")

    # ---- defensive / malformed-data handling ----

    def test_facility_with_missing_name_is_skipped_not_fatal(self):
        prop = self._property([
            {"name": "", "category": "gym", "distance_m": 100},
            stored_facility(name="Valid Gym"),
        ])
        result = nfs.build_nearby_facilities_display(prop)
        names = [f["name"] for f in result["groups"][0]["facilities"]]
        self.assertEqual(names, ["Valid Gym"])

    def test_facility_with_unknown_category_is_skipped_not_fatal(self):
        prop = self._property([
            stored_facility(name="Mystery Place", category="not_a_real_category"),
            stored_facility(name="Tiger Gym", category="gym"),
        ])
        result = nfs.build_nearby_facilities_display(prop)
        categories = [g["category"] for g in result["groups"]]
        self.assertEqual(categories, ["gym"])

    def test_non_list_nearby_facilities_does_not_crash(self):
        prop = self._property(None, metadata_status="completed")
        prop["nearby_facilities"] = "not a list"
        result = nfs.build_nearby_facilities_display(prop)
        self.assertEqual(result["status"], "empty")

    def test_internal_fields_never_appear_in_the_display_output(self):
        """The display layer must never leak source/provider_id/
        provider_type/fetched_at/search_radius_m - only what the
        frontend needs."""
        prop = self._property([stored_facility(name="Tiger Gym")])
        result = nfs.build_nearby_facilities_display(prop)
        facility = result["groups"][0]["facilities"][0]
        self.assertEqual(
            set(facility.keys()), {"name", "address", "distance_m", "distance_label"}
        )


if __name__ == "__main__":
    unittest.main()
