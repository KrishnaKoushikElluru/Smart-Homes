"""
Unit tests for services/search_orchestration.py (Phase 3: NLP + POI
resolution -> real MongoDB filter -> property retrieval).

No network access needed - Mappls/OSM calls are mocked (osm_service is
a fake with a scripted resolve_coordinates(); mappls_service.resolve_place
is patched), matching test_osm_location_service.py's convention.
services.nlp.parser.parse() runs for real (pure text processing, no
network) since Phase 2 must stay untouched and its real behavior is
exactly what this layer needs to be tested against.
"""

import unittest
from unittest.mock import patch

from services import search_orchestration as orch


# ============================================================
# FAKES
# ============================================================

class FakeOSMService:
    """Scripted resolve_coordinates() - the test sets .next_result."""

    def __init__(self):
        self.next_result = None
        self.calls = []

    def resolve_coordinates(self, mappls_poi):
        self.calls.append(mappls_poi)
        return self.next_result


class FakePropertyService:
    """Records every filter passed to filtered_search() and returns a
    scripted list."""

    def __init__(self, results=None):
        self.results = results if results is not None else []
        self.calls = []

    def filtered_search(self, mongo_filter):
        self.calls.append(mongo_filter)
        return self.results


def osm_matched(lat=12.99, lon=80.23, confidence=0.8):
    return {
        "status": "matched", "latitude": lat, "longitude": lon,
        "confidence": confidence, "error": None,
    }


def osm_status(status, error="reason"):
    return {
        "status": status, "latitude": None, "longitude": None,
        "confidence": 0.3 if status != "error" else None, "error": error,
    }


def mappls_matched(name="VIT Chennai", address="Vandalur, Chennai", eloc="ABC123", place_type="poi"):
    return {
        "status": "matched", "place_name": name, "place_address": address,
        "eloc": eloc, "type": place_type, "error": None,
    }


def mappls_no_match():
    return {"status": "no_match", "place_name": None, "place_address": None,
            "eloc": None, "type": None, "error": None}


NO_OVERRIDES = {"listing_type": "", "property_type": "", "bhk": None, "budget": 0, "city": "", "locality": ""}


# ============================================================
# MERGE PRECEDENCE
# ============================================================

class MergeFieldsTests(unittest.TestCase):

    def test_parsed_fields_used_when_no_override(self):
        structured = {"listing_type": {"value": "rent"}, "property_type": {"value": "apartment"},
                      "bedrooms": {"value": 2.0}, "price": None, "area": None, "amenities": [], "location": None}
        merged = orch.merge_structured_fields(structured, NO_OVERRIDES)
        self.assertEqual(merged["listing_type"], "rent")
        self.assertEqual(merged["property_type"], "apartment")
        self.assertEqual(merged["bhk"], 2.0)

    def test_explicit_override_wins_over_parsed(self):
        structured = {"listing_type": {"value": "rent"}, "property_type": None,
                      "bedrooms": None, "price": None, "area": None, "amenities": [], "location": None}
        overrides = dict(NO_OVERRIDES, listing_type="sell")
        merged = orch.merge_structured_fields(structured, overrides)
        self.assertEqual(merged["listing_type"], "sell")

    def test_explicit_budget_wins_over_parsed_price(self):
        structured = {"listing_type": None, "property_type": None, "bedrooms": None,
                      "price": {"operator": "lte", "value": 20000.0}, "area": None,
                      "amenities": [], "location": None}
        overrides = dict(NO_OVERRIDES, budget=15000)
        merged = orch.merge_structured_fields(structured, overrides)
        self.assertEqual(merged["price"], {"operator": "lte", "value": 15000.0})

    def test_zero_budget_is_not_specified(self):
        structured = {"listing_type": None, "property_type": None, "bedrooms": None,
                      "price": {"operator": "lte", "value": 20000.0}, "area": None,
                      "amenities": [], "location": None}
        merged = orch.merge_structured_fields(structured, NO_OVERRIDES)
        self.assertEqual(merged["price"], {"operator": "lte", "value": 20000.0})

    def test_area_or_city_location_maps_to_both_city_and_locality(self):
        structured = {"listing_type": None, "property_type": None, "bedrooms": None,
                      "price": None, "area": None, "amenities": [],
                      "location": {"type": "area_or_city", "query": "Tambaram"}}
        merged = orch.merge_structured_fields(structured, NO_OVERRIDES)
        self.assertEqual(merged["city"], "Tambaram")
        self.assertEqual(merged["locality"], "Tambaram")
        self.assertNotIn("poi_query", merged)

    def test_poi_location_produces_poi_query_not_city(self):
        structured = {"listing_type": None, "property_type": None, "bedrooms": None,
                      "price": None, "area": None, "amenities": [],
                      "location": {"type": "poi", "query": "VIT Chennai"}}
        merged = orch.merge_structured_fields(structured, NO_OVERRIDES)
        self.assertEqual(merged["poi_query"], "VIT Chennai")
        self.assertNotIn("city", merged)

    def test_explicit_city_wins_over_parsed_poi(self):
        # Explicit city/locality fields must never be silently discarded
        # even if the query also mentions a POI.
        structured = {"listing_type": None, "property_type": None, "bedrooms": None,
                      "price": None, "area": None, "amenities": [],
                      "location": {"type": "poi", "query": "VIT Chennai"}}
        overrides = dict(NO_OVERRIDES, city="Bengaluru")
        merged = orch.merge_structured_fields(structured, overrides)
        self.assertEqual(merged["city"], "Bengaluru")
        self.assertNotIn("poi_query", merged)

    def test_amenities_collected_from_parsed_query(self):
        structured = {"listing_type": None, "property_type": None, "bedrooms": None,
                      "price": None, "area": None,
                      "amenities": [{"value": "parking"}, {"value": "gym"}], "location": None}
        merged = orch.merge_structured_fields(structured, NO_OVERRIDES)
        self.assertEqual(merged["amenities"], ["parking", "gym"])


# ============================================================
# MONGO FILTER CONSTRUCTION - operator semantics preserved
# ============================================================

class BuildMongoFilterTests(unittest.TestCase):

    def test_lte_is_not_collapsed_to_equality(self):
        merged = {"price": {"operator": "lte", "value": 5000000.0}}
        mongo_filter, applied = orch.build_mongo_filter(merged)
        self.assertEqual(mongo_filter["listing.price"], {"$lte": 5000000.0})

    def test_gte_preserved(self):
        merged = {"price": {"operator": "gte", "value": 8000000.0}}
        mongo_filter, _ = orch.build_mongo_filter(merged)
        self.assertEqual(mongo_filter["listing.price"], {"$gte": 8000000.0})

    def test_between_keeps_both_bounds(self):
        merged = {"price": {"operator": "between", "value_min": 5000000.0, "value_max": 7000000.0}}
        mongo_filter, _ = orch.build_mongo_filter(merged)
        self.assertEqual(mongo_filter["listing.price"], {"$gte": 5000000.0, "$lte": 7000000.0})

    def test_approx_produces_symmetric_tolerance_band(self):
        merged = {"price": {"operator": "approx", "value": 10000000.0}}
        mongo_filter, _ = orch.build_mongo_filter(merged)
        band = mongo_filter["listing.price"]
        self.assertAlmostEqual(band["$gte"], 9000000.0)
        self.assertAlmostEqual(band["$lte"], 11000000.0)

    def test_area_under_1500_sqft(self):
        merged = {"area": {"operator": "lte", "value": 1500.0}}
        mongo_filter, _ = orch.build_mongo_filter(merged)
        self.assertEqual(mongo_filter["property.area_sqft"], {"$lte": 1500.0})

    def test_listing_type_property_type_bhk_furnishing_filters(self):
        merged = {"listing_type": "rent", "property_type": "apartment", "bhk": 2.0, "furnishing": "fully_furnished"}
        mongo_filter, _ = orch.build_mongo_filter(merged)
        self.assertEqual(mongo_filter["listing.type"], "rent")
        self.assertEqual(mongo_filter["property.type"], "apartment")
        self.assertEqual(mongo_filter["property.bhk"], 2.0)
        self.assertEqual(mongo_filter["property.furnishing"], "fully_furnished")

    def test_always_filters_active_status(self):
        mongo_filter, _ = orch.build_mongo_filter({})
        self.assertEqual(mongo_filter["listing.status"], "active")

    def test_generic_parking_matches_any_parking_subtype(self):
        merged = {"amenities": ["parking"]}
        mongo_filter, applied = orch.build_mongo_filter(merged)
        self.assertIn({"features": {"$in": orch.PARKING_SUBTYPE_FEATURE_CODES}}, mongo_filter["$and"])

    def test_specific_amenity_matches_exact_feature_code(self):
        merged = {"amenities": ["gym"]}
        mongo_filter, _ = orch.build_mongo_filter(merged)
        self.assertIn({"features": "gym"}, mongo_filter["$and"])

    def test_city_or_locality_text_uses_case_insensitive_regex_on_both_fields(self):
        merged = {"city": "Tambaram", "locality": "Tambaram"}
        mongo_filter, _ = orch.build_mongo_filter(merged)
        or_clause = mongo_filter["$and"][0]["$or"]
        self.assertIn({"location.city": {"$regex": "Tambaram", "$options": "i"}}, or_clause)
        self.assertIn({"location.locality": {"$regex": "Tambaram", "$options": "i"}}, or_clause)

    def test_no_filters_still_returns_active_only_filter(self):
        mongo_filter, applied = orch.build_mongo_filter({})
        self.assertEqual(mongo_filter, {"listing.status": "active"})
        self.assertEqual(applied, {})


# ============================================================
# POI RESOLUTION STATUS HANDLING
# ============================================================

class ResolvePoiLocationTests(unittest.TestCase):

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_matched_returns_coordinates(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_matched()
        osm = FakeOSMService()
        osm.next_result = osm_matched(lat=12.9, lon=80.2)

        result = orch.resolve_poi_location("VIT Chennai", "key", osm)

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["latitude"], 12.9)
        self.assertEqual(result["longitude"], 80.2)

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_mappls_no_match_short_circuits_before_osm(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_no_match()
        osm = FakeOSMService()

        result = orch.resolve_poi_location("Nonexistent Place Xyz", "key", osm)

        self.assertEqual(result["status"], "no_match")
        self.assertEqual(osm.calls, [])  # OSM never called - nothing for it to look for

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_osm_ambiguous_is_not_silently_resolved(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_matched()
        osm = FakeOSMService()
        osm.next_result = osm_status("ambiguous")

        result = orch.resolve_poi_location("SRM", "key", osm)

        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["latitude"])
        self.assertIsNone(result["longitude"])

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_osm_rejected_produces_no_coordinates(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_matched()
        osm = FakeOSMService()
        osm.next_result = osm_status("rejected")

        result = orch.resolve_poi_location("Some Place", "key", osm)

        self.assertEqual(result["status"], "rejected")
        self.assertIsNone(result["latitude"])

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_osm_error_produces_no_coordinates(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_matched()
        osm = FakeOSMService()
        osm.next_result = osm_status("error", error="OSM request failed.")

        result = orch.resolve_poi_location("Some Place", "key", osm)

        self.assertEqual(result["status"], "error")
        self.assertIsNone(result["latitude"])


# ============================================================
# FULL ORCHESTRATION
# ============================================================

class OrchestrateSearchTests(unittest.TestCase):

    def test_no_location_runs_plain_filtered_search(self):
        prop_service = FakePropertyService(results=[{"_id": "p1"}])

        result = orch.orchestrate_search(
            "2 bhk apartment for rent under 25000", NO_OVERRIDES,
            "key", FakeOSMService(), prop_service,
        )

        self.assertIsNone(result["location_resolution"])
        self.assertEqual(result["properties"], [{"_id": "p1"}])
        mongo_filter = prop_service.calls[0]
        self.assertEqual(mongo_filter["property.type"], "apartment")
        self.assertEqual(mongo_filter["property.bhk"], 2.0)
        self.assertEqual(mongo_filter["listing.price"], {"$lte": 25000.0})
        self.assertNotIn("location.coordinates", mongo_filter)

    def test_area_or_city_query_filters_without_geospatial(self):
        prop_service = FakePropertyService(results=[])

        result = orch.orchestrate_search(
            "2 bhk flat in Chennai", NO_OVERRIDES, "key", FakeOSMService(), prop_service,
        )

        self.assertIsNone(result["location_resolution"])
        mongo_filter = prop_service.calls[0]
        self.assertNotIn("location.coordinates", mongo_filter)
        self.assertIn("$and", mongo_filter)

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_matched_poi_adds_near_query_on_existing_2dsphere_index(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_matched()
        osm = FakeOSMService()
        osm.next_result = osm_matched(lat=12.9, lon=80.2)
        prop_service = FakePropertyService(results=[{"_id": "p1"}])

        result = orch.orchestrate_search(
            "2 bhk flat near VIT Chennai", NO_OVERRIDES, "key", osm, prop_service,
        )

        self.assertEqual(result["location_resolution"]["status"], "matched")
        self.assertEqual(result["properties"], [{"_id": "p1"}])
        mongo_filter = prop_service.calls[0]
        near = mongo_filter["location.coordinates"]["$near"]
        self.assertEqual(near["$geometry"]["coordinates"], [80.2, 12.9])
        self.assertEqual(near["$maxDistance"], orch.DEFAULT_POI_RADIUS_KM * 1000.0)

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_ambiguous_poi_returns_empty_results_without_querying_mongo(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_matched()
        osm = FakeOSMService()
        osm.next_result = osm_status("ambiguous")
        prop_service = FakePropertyService(results=[{"_id": "should_not_be_returned"}])

        result = orch.orchestrate_search(
            "2 bhk flat near SRM", NO_OVERRIDES, "key", osm, prop_service,
        )

        self.assertEqual(result["location_resolution"]["status"], "ambiguous")
        self.assertEqual(result["properties"], [])
        self.assertEqual(prop_service.calls, [])  # Mongo never queried - no silent fallback

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_no_match_poi_returns_empty_results_without_querying_mongo(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_no_match()
        prop_service = FakePropertyService(results=[{"_id": "should_not_be_returned"}])

        result = orch.orchestrate_search(
            "2 bhk flat near Nonexistent Place Xyz", NO_OVERRIDES, "key", FakeOSMService(), prop_service,
        )

        self.assertEqual(result["location_resolution"]["status"], "no_match")
        self.assertEqual(result["properties"], [])
        self.assertEqual(prop_service.calls, [])

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_rejected_poi_returns_empty_results_without_querying_mongo(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_matched()
        osm = FakeOSMService()
        osm.next_result = osm_status("rejected")
        prop_service = FakePropertyService(results=[{"_id": "should_not_be_returned"}])

        result = orch.orchestrate_search(
            "2 bhk flat near Somewhere", NO_OVERRIDES, "key", osm, prop_service,
        )

        self.assertEqual(result["location_resolution"]["status"], "rejected")
        self.assertEqual(result["properties"], [])
        self.assertEqual(prop_service.calls, [])

    def test_malformed_unsupported_query_does_not_crash(self):
        prop_service = FakePropertyService(results=[])

        result = orch.orchestrate_search(
            "what's the weather today", NO_OVERRIDES, "key", FakeOSMService(), prop_service,
        )

        self.assertEqual(result["parsed_query"]["intent"], "unknown")
        self.assertEqual(result["properties"], [])

    def test_empty_query_does_not_crash(self):
        prop_service = FakePropertyService(results=[])

        result = orch.orchestrate_search(
            "", NO_OVERRIDES, "key", FakeOSMService(), prop_service,
        )

        self.assertEqual(result["parsed_query"]["intent"], "unknown")


# ============================================================
# BOUNDARY: this module must never fabricate coordinates itself
# ============================================================

class NoFabricatedCoordinatesTests(unittest.TestCase):

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_only_osm_matched_result_ever_supplies_coordinates(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_matched()
        for status in ("ambiguous", "no_match", "rejected", "error"):
            with self.subTest(status=status):
                osm = FakeOSMService()
                osm.next_result = osm_status(status)
                result = orch.resolve_poi_location("X", "key", osm)
                self.assertIsNone(result["latitude"])
                self.assertIsNone(result["longitude"])


if __name__ == "__main__":
    unittest.main()
