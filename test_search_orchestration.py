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
    scripted list. count() (Stage 2) is scripted separately via
    .count_result and records its own filter calls."""

    def __init__(self, results=None, count_result=0):
        self.results = results if results is not None else []
        self.calls = []
        self.count_result = count_result
        self.count_calls = []

    def filtered_search(self, mongo_filter):
        self.calls.append(mongo_filter)
        return self.results

    def count(self, mongo_filter):
        self.count_calls.append(mongo_filter)
        return self.count_result


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

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_ambiguous_alternates_are_passed_through_for_a_picker(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_matched()
        osm = FakeOSMService()
        alternates = [
            {"matched_name": "VIT Chennai Administrative Block", "matched_address": "...",
             "latitude": 12.8406, "longitude": 80.1539, "score": 0.4866},
            {"matched_name": "VIT Academic Block 1", "matched_address": "...",
             "latitude": 12.8436, "longitude": 80.1534, "score": 0.4647},
        ]
        osm.next_result = {**osm_status("ambiguous"), "alternates": alternates}

        result = orch.resolve_poi_location("VIT Chennai", "key", osm)

        self.assertEqual(result["status"], "ambiguous")
        self.assertEqual(result["alternates"], alternates)

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_matched_with_no_alternates_key_defaults_to_empty_list(self, mock_resolve_place):
        # osm_matched() (the shared fixture) doesn't include an
        # "alternates" key at all - resolve_poi_location() must not
        # crash on a missing key, just default to [].
        mock_resolve_place.return_value = mappls_matched()
        osm = FakeOSMService()
        osm.next_result = osm_matched()

        result = orch.resolve_poi_location("VIT Chennai", "key", osm)

        self.assertEqual(result["alternates"], [])


# ============================================================
# PROVIDER ORCHESTRATION (Ola primary, Mappls+OSM fallback)
# ============================================================

class ResolvePoiLocationViaBestProviderTests(unittest.TestCase):

    def test_ola_success_means_mappls_is_never_called(self):
        with patch(
            "services.search_orchestration.location_provider_service.resolve_location_via_ola",
            return_value={
                "status": "matched", "latitude": 12.8358, "longitude": 80.1561,
                "place_name": "TaTa New Haven Ribbon Walk", "formatted_address": "...",
                "confidence": 0.95, "error": None, "alternates": [], "provider": "ola",
            },
        ), patch("services.search_orchestration.mappls_service.resolve_place") as mock_mappls:

            result = orch.resolve_poi_location_via_best_provider(
                "Tata New Haven Ribbon Walk", "ola-key", "mappls-key", FakeOSMService(),
            )

        mock_mappls.assert_not_called()
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["provider"], "ola")
        self.assertEqual(result["latitude"], 12.8358)

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_ola_no_safe_result_falls_back_to_mappls(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_matched()
        osm = FakeOSMService()
        osm.next_result = osm_matched(lat=12.9, lon=80.2)

        with patch(
            "services.search_orchestration.location_provider_service.resolve_location_via_ola",
            return_value={
                "status": "no_match", "latitude": None, "longitude": None,
                "place_name": None, "formatted_address": None, "confidence": None,
                "error": "No Ola Maps candidates.", "alternates": [], "provider": "ola",
            },
        ):
            result = orch.resolve_poi_location_via_best_provider(
                "Obscure Local Place", "ola-key", "mappls-key", osm,
            )

        mock_resolve_place.assert_called_once()
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["provider"], "mappls")
        self.assertEqual(result["latitude"], 12.9)

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_ola_error_falls_back_to_mappls(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_matched()
        osm = FakeOSMService()
        osm.next_result = osm_matched()

        with patch(
            "services.search_orchestration.location_provider_service.resolve_location_via_ola",
            return_value={
                "status": "error", "latitude": None, "longitude": None,
                "place_name": None, "formatted_address": None, "confidence": None,
                "error": "Ola Maps request failed or timed out.", "alternates": [], "provider": "ola",
            },
        ):
            result = orch.resolve_poi_location_via_best_provider(
                "VIT Chennai", "ola-key", "mappls-key", osm,
            )

        mock_resolve_place.assert_called_once()
        self.assertEqual(result["provider"], "mappls")

    def test_mappls_failure_after_ola_failure_preserves_existing_osm_behavior(self):
        osm = FakeOSMService()

        with patch(
            "services.search_orchestration.location_provider_service.resolve_location_via_ola",
            return_value={
                "status": "no_match", "latitude": None, "longitude": None,
                "place_name": None, "formatted_address": None, "confidence": None,
                "error": None, "alternates": [], "provider": "ola",
            },
        ), patch(
            "services.search_orchestration.mappls_service.resolve_place",
            return_value=mappls_no_match(),
        ):
            result = orch.resolve_poi_location_via_best_provider(
                "Nonexistent Place Xyz", "ola-key", "mappls-key", osm,
            )

        self.assertEqual(result["status"], "no_match")
        self.assertIsNone(result["provider"])
        self.assertEqual(osm.calls, [])  # Mappls no_match -> OSM never attempted, same as before

    def test_ambiguous_ola_result_does_not_silently_choose_a_location(self):
        with patch(
            "services.search_orchestration.location_provider_service.resolve_location_via_ola",
            return_value={
                "status": "ambiguous", "latitude": None, "longitude": None,
                "place_name": None, "formatted_address": None, "confidence": 0.76,
                "error": "Top Ola candidates were too close to distinguish confidently.",
                "alternates": [
                    {"matched_name": "Mambakkam", "matched_address": "Chennai, 600127",
                     "latitude": 12.836, "longitude": 80.167, "score": None},
                ],
                "provider": "ola",
            },
        ), patch(
            "services.search_orchestration.mappls_service.resolve_place",
            return_value=mappls_no_match(),
        ):
            result = orch.resolve_poi_location_via_best_provider(
                "Mambakkam", "ola-key", "mappls-key", FakeOSMService(),
            )

        # Ola's own ambiguity is not surfaced as final - Mappls gets a
        # full independent attempt (see this function's docstring).
        self.assertIsNone(result["latitude"])
        self.assertIsNone(result["longitude"])
        self.assertIsNone(result["provider"])

    def test_no_ola_key_skips_straight_to_mappls(self):
        # ola_api_key=None (the default) must never attempt a network
        # call - services/ola_maps_service.py's own missing-key guard
        # makes this safe without any special-casing here.
        with patch(
            "services.search_orchestration.mappls_service.resolve_place",
            return_value=mappls_matched(),
        ) as mock_resolve_place:
            osm = FakeOSMService()
            osm.next_result = osm_matched()

            result = orch.resolve_poi_location_via_best_provider(
                "VIT Chennai", None, "mappls-key", osm,
            )

        mock_resolve_place.assert_called_once()
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["provider"], "mappls")


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

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_explicit_coordinates_bypass_poi_resolution_entirely(self, mock_resolve_place):
        # Simulates a user picking one option from a previous "ambiguous"
        # result's alternates - re-resolving the same POI text via
        # Mappls/OSM would just be ambiguous again, so it must not be
        # attempted at all.
        prop_service = FakePropertyService(results=[{"_id": "p1"}])
        osm = FakeOSMService()

        result = orch.orchestrate_search(
            "2 bhk flat near VIT Chennai", NO_OVERRIDES, "key", osm, prop_service,
            explicit_coordinates=(12.8406, 80.1539),
        )

        mock_resolve_place.assert_not_called()
        self.assertEqual(osm.calls, [])
        self.assertEqual(result["location_resolution"]["status"], "matched")
        self.assertEqual(result["location_resolution"]["latitude"], 12.8406)
        self.assertEqual(result["location_resolution"]["longitude"], 80.1539)
        self.assertEqual(result["location_resolution"]["alternates"], [])
        self.assertEqual(result["properties"], [{"_id": "p1"}])

        mongo_filter = prop_service.calls[0]
        near = mongo_filter["location.coordinates"]["$near"]
        self.assertEqual(near["$geometry"]["coordinates"], [80.1539, 12.8406])
        self.assertEqual(near["$maxDistance"], orch.DEFAULT_POI_RADIUS_KM * 1000.0)

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_explicit_coordinates_still_applies_other_parsed_filters(self, mock_resolve_place):
        prop_service = FakePropertyService(results=[])

        result = orch.orchestrate_search(
            "2 bhk furnished apartment for rent near VIT Chennai under 25000 with gym",
            NO_OVERRIDES, "key", FakeOSMService(), prop_service,
            explicit_coordinates=(12.8406, 80.1539),
        )

        mock_resolve_place.assert_not_called()
        mongo_filter = prop_service.calls[0]
        self.assertEqual(mongo_filter["property.bhk"], 2.0)
        self.assertEqual(mongo_filter["property.type"], "apartment")
        self.assertEqual(mongo_filter["listing.type"], "rent")
        self.assertEqual(mongo_filter["listing.price"], {"$lte": 25000.0})
        self.assertIn({"features": "gym"}, mongo_filter["$and"])

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


# ============================================================
# STAGE 2: NEARBY-FACILITY SEARCH
# ============================================================

class MergeNearbyFacilitiesTests(unittest.TestCase):

    def test_nearby_facility_requirement_is_threaded_through(self):
        structured = {"listing_type": None, "property_type": None, "bedrooms": None,
                      "price": None, "area": None, "amenities": [], "location": None,
                      "nearby_facilities": [{"category": "gym", "radius_m": None, "raw_text": "near a gym", "confidence": 0.8}]}
        merged = orch.merge_structured_fields(structured, NO_OVERRIDES)
        self.assertEqual(merged["nearby_facility_requirements"], [{"category": "gym", "radius_m": None}])

    def test_multiple_nearby_facilities_are_all_threaded_through(self):
        structured = {"listing_type": None, "property_type": None, "bedrooms": None,
                      "price": None, "area": None, "amenities": [], "location": None,
                      "nearby_facilities": [
                          {"category": "gym", "radius_m": None, "raw_text": "x", "confidence": 0.8},
                          {"category": "hospital", "radius_m": 1000.0, "raw_text": "y", "confidence": 0.85},
                      ]}
        merged = orch.merge_structured_fields(structured, NO_OVERRIDES)
        self.assertEqual(len(merged["nearby_facility_requirements"]), 2)

    def test_no_nearby_facility_mention_produces_no_key(self):
        structured = {"listing_type": None, "property_type": None, "bedrooms": None,
                      "price": None, "area": None, "amenities": [], "location": None,
                      "nearby_facilities": []}
        merged = orch.merge_structured_fields(structured, NO_OVERRIDES)
        self.assertNotIn("nearby_facility_requirements", merged)

    def test_nearby_facility_coexists_with_property_amenity(self):
        # "flat with a gym, near a hospital" - the property HAS a gym
        # (amenity) AND wants to be near a hospital (nearby facility) -
        # these must never collide or overwrite each other.
        structured = {"listing_type": None, "property_type": None, "bedrooms": None,
                      "price": None, "area": None,
                      "amenities": [{"value": "gym", "confidence": 0.9, "source": "x"}],
                      "location": None,
                      "nearby_facilities": [{"category": "hospital", "radius_m": None, "raw_text": "x", "confidence": 0.8}]}
        merged = orch.merge_structured_fields(structured, NO_OVERRIDES)
        self.assertEqual(merged["amenities"], ["gym"])
        self.assertEqual(merged["nearby_facility_requirements"], [{"category": "hospital", "radius_m": None}])


class BuildMongoFilterNearbyFacilitiesTests(unittest.TestCase):

    def test_no_radius_matches_category_only(self):
        merged = {"nearby_facility_requirements": [{"category": "gym", "radius_m": None}]}
        mongo_filter, applied = orch.build_mongo_filter(merged)
        self.assertIn({"nearby_facilities": {"$elemMatch": {"category": "gym"}}}, mongo_filter["$and"])
        self.assertEqual(applied["nearby_facilities"], [{"category": "gym", "radius_m": None}])

    def test_radius_adds_lte_distance_constraint(self):
        merged = {"nearby_facility_requirements": [{"category": "hospital", "radius_m": 1000.0}]}
        mongo_filter, _ = orch.build_mongo_filter(merged)
        self.assertIn(
            {"nearby_facilities": {"$elemMatch": {"category": "hospital", "distance_m": {"$lte": 1000.0}}}},
            mongo_filter["$and"],
        )

    def test_multiple_categories_produce_separate_elem_match_clauses(self):
        # A single $elemMatch cannot require two different array
        # elements to both exist - this must be two AND'd clauses, not
        # one $elemMatch with both categories (which would require ONE
        # facility to somehow be both categories at once).
        merged = {"nearby_facility_requirements": [
            {"category": "gym", "radius_m": None},
            {"category": "hospital", "radius_m": 1000.0},
        ]}
        mongo_filter, _ = orch.build_mongo_filter(merged)
        self.assertEqual(len(mongo_filter["$and"]), 2)
        gym_clause = {"nearby_facilities": {"$elemMatch": {"category": "gym"}}}
        hospital_clause = {"nearby_facilities": {"$elemMatch": {"category": "hospital", "distance_m": {"$lte": 1000.0}}}}
        self.assertIn(gym_clause, mongo_filter["$and"])
        self.assertIn(hospital_clause, mongo_filter["$and"])

    def test_nearby_facility_combines_with_price_and_furnishing(self):
        merged = {
            "nearby_facility_requirements": [{"category": "gym", "radius_m": None}],
            "price": {"operator": "lte", "value": 30000.0},
            "furnishing": "semi_furnished",
        }
        mongo_filter, _ = orch.build_mongo_filter(merged)
        self.assertEqual(mongo_filter["listing.price"], {"$lte": 30000.0})
        self.assertEqual(mongo_filter["property.furnishing"], "semi_furnished")
        self.assertIn({"nearby_facilities": {"$elemMatch": {"category": "gym"}}}, mongo_filter["$and"])

    def test_no_nearby_facility_requirement_adds_no_and_clause_for_it(self):
        mongo_filter, applied = orch.build_mongo_filter({})
        self.assertNotIn("nearby_facilities", applied)


class NearbyFacilityEnrichmentCaveatTests(unittest.TestCase):

    def test_no_requirements_skips_the_count_call_entirely(self):
        prop_service = FakePropertyService(count_result=5)
        caveat = orch._nearby_facility_enrichment_caveat(prop_service, [])
        self.assertIsNone(caveat)
        self.assertEqual(prop_service.count_calls, [])

    def test_requirements_trigger_a_count_and_report_it(self):
        prop_service = FakePropertyService(count_result=3)
        caveat = orch._nearby_facility_enrichment_caveat(prop_service, [{"category": "gym", "radius_m": None}])
        self.assertEqual(caveat["unenriched_active_listings"], 3)
        self.assertIsNotNone(caveat["note"])
        self.assertEqual(len(prop_service.count_calls), 1)

    def test_zero_unenriched_produces_no_note(self):
        prop_service = FakePropertyService(count_result=0)
        caveat = orch._nearby_facility_enrichment_caveat(prop_service, [{"category": "gym", "radius_m": None}])
        self.assertEqual(caveat["unenriched_active_listings"], 0)
        self.assertIsNone(caveat["note"])


class OrchestrateSearchNearbyFacilityTests(unittest.TestCase):

    def test_nearby_gym_no_location_filters_by_category(self):
        prop_service = FakePropertyService(results=[{"_id": "p1"}], count_result=0)

        result = orch.orchestrate_search(
            "flat near a gym", NO_OVERRIDES, "key", FakeOSMService(), prop_service,
        )

        self.assertEqual(result["properties"][0]["_id"], "p1")
        mongo_filter = prop_service.calls[0]
        self.assertIn({"nearby_facilities": {"$elemMatch": {"category": "gym"}}}, mongo_filter["$and"])
        self.assertIsNotNone(result["nearby_facility_enrichment_caveat"])

    def test_nearby_hospital_with_radius(self):
        prop_service = FakePropertyService(results=[], count_result=0)

        result = orch.orchestrate_search(
            "2 BHK near hospital within 1 km", NO_OVERRIDES, "key", FakeOSMService(), prop_service,
        )

        mongo_filter = prop_service.calls[0]
        self.assertIn(
            {"nearby_facilities": {"$elemMatch": {"category": "hospital", "distance_m": {"$lte": 1000.0}}}},
            mongo_filter["$and"],
        )
        self.assertEqual(mongo_filter["property.bhk"], 2.0)

    def test_property_amenity_gym_is_not_treated_as_nearby_facility(self):
        prop_service = FakePropertyService(results=[], count_result=0)

        result = orch.orchestrate_search(
            "flat with a gym", NO_OVERRIDES, "key", FakeOSMService(), prop_service,
        )

        mongo_filter = prop_service.calls[0]
        self.assertIn({"features": "gym"}, mongo_filter.get("$and", []))
        self.assertNotIn(
            {"nearby_facilities": {"$elemMatch": {"category": "gym"}}}, mongo_filter.get("$and", [])
        )
        self.assertIsNone(result["nearby_facility_enrichment_caveat"])

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_vit_chennai_matched_plus_nearby_gym_together(self, mock_resolve_place):
        # This phase's own worked example: primary POI = VIT Chennai,
        # nearby facility = gym - both must reach the final Mongo filter.
        mock_resolve_place.return_value = mappls_matched(name="VIT Chennai")
        osm = FakeOSMService()
        osm.next_result = osm_matched(lat=12.84, lon=80.15)
        prop_service = FakePropertyService(results=[{"_id": "p1"}], count_result=0)

        result = orch.orchestrate_search(
            "flat near VIT Chennai with a gym nearby", NO_OVERRIDES, "key", osm, prop_service,
        )

        self.assertEqual(result["location_resolution"]["status"], "matched")
        mongo_filter = prop_service.calls[0]
        self.assertIn("$near", mongo_filter["location.coordinates"])
        self.assertIn({"nearby_facilities": {"$elemMatch": {"category": "gym"}}}, mongo_filter["$and"])

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_ambiguous_poi_does_not_discard_the_nearby_facility_requirement(self, mock_resolve_place):
        # The gym requirement must still be visible in applied_filters
        # even when the POI itself couldn't be resolved - so that once
        # the user picks an alternate (a SEPARATE, later request - see
        # test_explicit_coordinates_still_applies_other_parsed_filters
        # for that mechanism, which re-parses the same raw_query text
        # and therefore re-extracts the same gym requirement
        # automatically), nothing about the gym constraint was ever lost.
        mock_resolve_place.return_value = mappls_matched(name="VIT Chennai")
        osm = FakeOSMService()
        osm.next_result = osm_status("ambiguous")
        prop_service = FakePropertyService(results=[{"_id": "should_not_appear"}], count_result=0)

        result = orch.orchestrate_search(
            "flat near VIT Chennai with a gym nearby", NO_OVERRIDES, "key", osm, prop_service,
        )

        self.assertEqual(result["location_resolution"]["status"], "ambiguous")
        self.assertEqual(result["properties"], [])  # no silent fallback
        self.assertEqual(result["applied_filters"]["nearby_facilities"], [{"category": "gym", "radius_m": None}])

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_picking_an_alternate_after_ambiguous_preserves_the_gym_requirement(self, mock_resolve_place):
        # Simulates the full two-request picker flow end to end: the
        # SAME raw_query is re-sent with explicit_coordinates (exactly
        # what routes/search_routes.py does when the frontend sends
        # location_lat/location_lon - see test_search_routes_integration.py) -
        # the gym requirement must reappear because it's re-parsed from
        # the same text, never carried over as hidden state.
        prop_service = FakePropertyService(results=[{"_id": "p1"}], count_result=0)

        result = orch.orchestrate_search(
            "flat near VIT Chennai with a gym nearby", NO_OVERRIDES, "key", FakeOSMService(), prop_service,
            explicit_coordinates=(12.8406, 80.1539),
        )

        mock_resolve_place.assert_not_called()  # no re-resolution attempted
        mongo_filter = prop_service.calls[0]
        self.assertIn("$near", mongo_filter["location.coordinates"])
        self.assertIn({"nearby_facilities": {"$elemMatch": {"category": "gym"}}}, mongo_filter["$and"])


# ============================================================
# MATCHED NEARBY FACILITY NAMES (Phase 5, Part 7/8/9)
# ============================================================

class AttachMatchedNearbyFacilitiesTests(unittest.TestCase):
    """Unit-level tests for orch._attach_matched_nearby_facilities()
    directly - the function that lets the UI show "Gold's Gym - 780 m
    away" instead of just "Gym - 780 m away"."""

    def test_no_requirements_does_not_attach_the_key_at_all(self):
        properties = [{"_id": "p1", "nearby_facilities": [
            {"category": "gym", "name": "Gold's Gym", "distance_m": 780},
        ]}]
        orch._attach_matched_nearby_facilities(properties, [])
        self.assertNotIn("_matched_nearby_facilities", properties[0])

    def test_single_matching_facility_is_surfaced_with_its_real_name(self):
        properties = [{"_id": "p1", "nearby_facilities": [
            {"category": "gym", "name": "Gold's Gym", "distance_m": 780},
        ]}]
        orch._attach_matched_nearby_facilities(
            properties, [{"category": "gym", "radius_m": None}]
        )
        self.assertEqual(
            properties[0]["_matched_nearby_facilities"],
            [{"category": "gym", "name": "Gold's Gym", "distance_m": 780}],
        )

    def test_multiple_requirements_each_get_their_own_facility(self):
        # "2 bhk near a gym and hospital within 2 km"
        properties = [{"_id": "p1", "nearby_facilities": [
            {"category": "gym", "name": "Gold's Gym", "distance_m": 780},
            {"category": "hospital", "name": "ABC Hospital", "distance_m": 1400},
        ]}]
        orch._attach_matched_nearby_facilities(
            properties,
            [{"category": "gym", "radius_m": 2000}, {"category": "hospital", "radius_m": 2000}],
        )
        matched = properties[0]["_matched_nearby_facilities"]
        self.assertEqual(len(matched), 2)
        by_category = {m["category"]: m for m in matched}
        self.assertEqual(by_category["gym"]["name"], "Gold's Gym")
        self.assertEqual(by_category["gym"]["distance_m"], 780)
        self.assertEqual(by_category["hospital"]["name"], "ABC Hospital")
        self.assertEqual(by_category["hospital"]["distance_m"], 1400)

    def test_multiple_stored_facilities_for_one_category_picks_the_closest(self):
        properties = [{"_id": "p1", "nearby_facilities": [
            {"category": "gym", "name": "Far Gym", "distance_m": 1900},
            {"category": "gym", "name": "Gold's Gym", "distance_m": 780},
        ]}]
        orch._attach_matched_nearby_facilities(
            properties, [{"category": "gym", "radius_m": 2000}]
        )
        self.assertEqual(properties[0]["_matched_nearby_facilities"][0]["name"], "Gold's Gym")

    def test_requirement_outside_stored_radius_is_not_matched(self):
        properties = [{"_id": "p1", "nearby_facilities": [
            {"category": "gym", "name": "Gold's Gym", "distance_m": 1900},
        ]}]
        orch._attach_matched_nearby_facilities(
            properties, [{"category": "gym", "radius_m": 1000}]
        )
        self.assertEqual(properties[0]["_matched_nearby_facilities"], [])

    def test_property_with_no_stored_facility_for_requested_category_gets_empty_list(self):
        properties = [{"_id": "p1", "nearby_facilities": [
            {"category": "hospital", "name": "ABC Hospital", "distance_m": 500},
        ]}]
        orch._attach_matched_nearby_facilities(
            properties, [{"category": "gym", "radius_m": None}]
        )
        self.assertEqual(properties[0]["_matched_nearby_facilities"], [])

    def test_property_with_no_nearby_facilities_field_at_all(self):
        properties = [{"_id": "p1"}]
        orch._attach_matched_nearby_facilities(
            properties, [{"category": "gym", "radius_m": None}]
        )
        self.assertEqual(properties[0]["_matched_nearby_facilities"], [])


class OrchestrateSearchMatchedNearbyFacilitiesIntegrationTests(unittest.TestCase):
    """End-to-end through orchestrate_search() with realistic stored
    property data, proving the property document flows all the way
    through to the attached field."""

    def test_gym_search_result_includes_the_real_gym_name(self):
        prop_service = FakePropertyService(
            results=[{
                "_id": "p1",
                "nearby_facilities": [
                    {"category": "gym", "name": "Gold's Gym", "distance_m": 780},
                ],
            }],
            count_result=0,
        )

        result = orch.orchestrate_search(
            "2 bhk flat near a gym within 1 km in Chennai", NO_OVERRIDES, "key", FakeOSMService(), prop_service,
        )

        self.assertEqual(
            result["properties"][0]["_matched_nearby_facilities"],
            [{"category": "gym", "name": "Gold's Gym", "distance_m": 780}],
        )

    def test_multi_facility_search_surfaces_both_names(self):
        prop_service = FakePropertyService(
            results=[{
                "_id": "p1",
                "nearby_facilities": [
                    {"category": "gym", "name": "Gold's Gym", "distance_m": 780},
                    {"category": "hospital", "name": "ABC Hospital", "distance_m": 1400},
                ],
            }],
            count_result=0,
        )

        result = orch.orchestrate_search(
            "2 bhk near a gym and hospital within 2 km", NO_OVERRIDES, "key", FakeOSMService(), prop_service,
        )

        matched = result["properties"][0]["_matched_nearby_facilities"]
        categories = {m["category"] for m in matched}
        self.assertEqual(categories, {"gym", "hospital"})

    def test_ordinary_search_without_nearby_facility_never_attaches_the_key(self):
        prop_service = FakePropertyService(results=[{"_id": "p1"}], count_result=0)

        result = orch.orchestrate_search(
            "2 bhk apartment for rent under 25000", NO_OVERRIDES, "key", FakeOSMService(), prop_service,
        )

        self.assertNotIn("_matched_nearby_facilities", result["properties"][0])


if __name__ == "__main__":
    unittest.main()
