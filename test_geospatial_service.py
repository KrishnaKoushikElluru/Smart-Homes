"""
Unit tests for services/geospatial_service.py (GeoSpatial Phase 2 +
the 42-category taxonomy extension).

Run with:
    python -m unittest test_geospatial_service

Distance/normalization/taxonomy tests need no network access. The
Geoapify HTTP call itself is mocked via unittest.mock so these never
depend on a live API key or external connectivity.
"""

import unittest
from unittest.mock import patch, Mock

import requests as requests_module

from services import geospatial_service as geo


def feature(name, lat, lon, categories=None, **extra):
    """Build a fake Geoapify feature, close to what the real API returns."""

    properties = {
        "name": name,
        "lat": lat,
        "lon": lon,
        "formatted": name,
        "categories": categories or [],
    }

    properties.update(extra)

    return {"properties": properties}


# ============================================================
# TAXONOMY / CONFIGURATION
# ============================================================

class TaxonomyTests(unittest.TestCase):

    def test_all_42_categories_are_registered(self):

        self.assertEqual(len(geo.POI_CATEGORIES), 42)

    def test_every_category_has_a_valid_geoapify_mapping(self):

        for category, codes in geo.POI_CATEGORIES.items():

            self.assertIsInstance(codes, list, category)
            self.assertTrue(len(codes) >= 1, category)

            for code in codes:
                self.assertIsInstance(code, str)
                self.assertTrue(code)

    def test_every_category_belongs_to_exactly_one_group(self):

        self.assertEqual(
            set(geo.POI_CATEGORIES.keys()),
            set(geo.CATEGORY_TO_GROUP.keys())
        )

        seen = set()

        for group, members in geo.POI_CATEGORY_GROUPS.items():

            for member in members:

                self.assertNotIn(
                    member, seen,
                    f"{member} appears in more than one group"
                )

                seen.add(member)

                self.assertEqual(geo.CATEGORY_TO_GROUP[member], group)

        self.assertEqual(seen, set(geo.POI_CATEGORIES.keys()))

    def test_group_leaf_counts_match_taxonomy(self):

        expected_sizes = {
            "food": 4,
            "shopping": 3,
            "healthcare": 4,
            "education": 4,
            "parks_leisure": 3,
            "fitness_sports": 5,
            "entertainment": 3,
            "transport": 5,
            "financial_essential": 5,
            "vehicle_services": 3,
            "accommodation": 3,
        }

        actual_sizes = {
            group: len(members)
            for group, members in geo.POI_CATEGORY_GROUPS.items()
        }

        self.assertEqual(actual_sizes, expected_sizes)

    def test_original_six_categories_still_present_or_aliased(self):

        original_six = {
            "schools", "hospitals", "restaurants",
            "parks", "public_transport", "shopping"
        }

        available = (
            set(geo.POI_CATEGORIES.keys())
            | set(geo.LEGACY_CATEGORY_ALIASES.keys())
        )

        self.assertTrue(original_six.issubset(available))


# ============================================================
# DISTANCE
# ============================================================

class HaversineDistanceTests(unittest.TestCase):

    def test_same_point_is_zero(self):

        distance = geo.haversine_distance_km(
            12.8423, 80.1538,
            12.8423, 80.1538
        )

        self.assertAlmostEqual(distance, 0.0, places=6)

    def test_known_distance_chennai_to_bangalore(self):

        # Chennai Central ~ (13.0827, 80.2707)
        # Bangalore MG Road ~ (12.9716, 77.5946)
        # Straight-line geodesic distance is ~290 km.

        distance = geo.haversine_distance_km(
            13.0827, 80.2707,
            12.9716, 77.5946
        )

        self.assertTrue(
            280 <= distance <= 300,
            f"unexpected distance: {distance}"
        )


# ============================================================
# NORMALIZATION
# ============================================================

class NormalizeFeatureTests(unittest.TestCase):

    def test_normalizes_complete_feature(self):

        raw = feature(
            "Test School", 12.85, 80.16,
            categories=["education", "education.school"],
            city="Chennai", state="Tamil Nadu",
            postcode="600127", place_id="abc123"
        )

        poi = geo._normalize_feature(
            raw, "schools", "education", 12.8423, 80.1538
        )

        self.assertEqual(poi["name"], "Test School")
        self.assertEqual(poi["category"], "schools")
        self.assertEqual(poi["category_group"], "education")
        self.assertEqual(poi["latitude"], 12.85)
        self.assertEqual(poi["longitude"], 80.16)
        self.assertEqual(poi["address"], "Test School")
        self.assertEqual(poi["city"], "Chennai")
        self.assertEqual(poi["state"], "Tamil Nadu")
        self.assertEqual(poi["postcode"], "600127")
        self.assertEqual(poi["place_id"], "abc123")
        self.assertEqual(
            poi["source_categories"],
            ["education", "education.school"]
        )
        self.assertIsInstance(poi["latitude"], float)
        self.assertIsInstance(poi["longitude"], float)
        self.assertIsInstance(poi["distance_km"], float)
        self.assertGreater(poi["distance_km"], 0)

    def test_missing_name_and_address_fall_back(self):

        raw = {"properties": {"lat": 12.85, "lon": 80.16}}

        poi = geo._normalize_feature(raw, "parks", "parks_leisure", 12.8423, 80.1538)

        self.assertEqual(poi["name"], "Unnamed")
        self.assertEqual(poi["address"], "Address unavailable")

    def test_missing_optional_fields_do_not_crash(self):

        raw = {"properties": {"name": "Bare POI", "lat": 12.85, "lon": 80.16}}

        poi = geo._normalize_feature(raw, "parks", "parks_leisure", 12.8423, 80.1538)

        self.assertIsNone(poi["city"])
        self.assertIsNone(poi["state"])
        self.assertIsNone(poi["postcode"])
        self.assertIsNone(poi["place_id"])
        self.assertEqual(poi["source_categories"], [])

    def test_missing_coordinates_returns_none(self):

        raw = {"properties": {"name": "No location"}}

        poi = geo._normalize_feature(raw, "parks", "parks_leisure", 12.8423, 80.1538)

        self.assertIsNone(poi)

    def test_non_list_source_categories_are_normalized_to_empty_list(self):

        raw = {
            "properties": {
                "name": "Weird POI", "lat": 12.85, "lon": 80.16,
                "categories": "not-a-list"
            }
        }

        poi = geo._normalize_feature(raw, "parks", "parks_leisure", 12.8423, 80.1538)

        self.assertEqual(poi["source_categories"], [])


# ============================================================
# get_nearby_pois - error handling / safety
# ============================================================

class GetNearbyPoisSafetyTests(unittest.TestCase):

    def test_missing_api_key_returns_safe_empty_result(self):

        result = geo.get_nearby_pois(12.84, 80.15, api_key=None)

        self.assertEqual(
            result["error"],
            "Location intelligence is not configured."
        )

        self.assertTrue(
            all(len(pois) == 0 for pois in result["categories"].values())
        )

    def test_invalid_coordinates_returns_safe_empty_result(self):

        result = geo.get_nearby_pois(200, 80.15, api_key="fake-key")

        self.assertEqual(result["error"], "Invalid property coordinates.")

    @patch("services.geospatial_service.requests.get")
    def test_geoapify_request_exception_is_caught(self, mock_get):

        mock_get.side_effect = requests_module.exceptions.Timeout()

        result = geo.get_nearby_pois(
            12.84, 80.15,
            api_key="fake-key",
            categories={"schools": geo.POI_CATEGORIES["schools"]}
        )

        self.assertEqual(result["categories"]["schools"], [])
        self.assertIn("schools", result["category_errors"])

    @patch("services.geospatial_service.requests.get")
    def test_non_200_response_is_handled(self, mock_get):

        mock_response = Mock()
        mock_response.status_code = 500
        mock_get.return_value = mock_response

        result = geo.get_nearby_pois(
            12.84, 80.15,
            api_key="fake-key",
            categories={"schools": geo.POI_CATEGORIES["schools"]}
        )

        self.assertEqual(result["categories"]["schools"], [])
        self.assertIn("schools", result["category_errors"])

    @patch("services.geospatial_service.requests.get")
    def test_rate_limit_429_is_handled(self, mock_get):

        mock_response = Mock()
        mock_response.status_code = 429
        mock_get.return_value = mock_response

        result = geo.get_nearby_pois(
            12.84, 80.15,
            api_key="fake-key",
            categories={"restaurants": geo.POI_CATEGORIES["restaurants"]}
        )

        self.assertEqual(result["categories"]["restaurants"], [])
        self.assertIn("rate-limited", result["category_errors"]["restaurants"])

    @patch("services.geospatial_service.requests.get")
    def test_malformed_json_is_handled(self, mock_get):

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.side_effect = ValueError("bad json")
        mock_get.return_value = mock_response

        result = geo.get_nearby_pois(
            12.84, 80.15,
            api_key="fake-key",
            categories={"schools": geo.POI_CATEGORIES["schools"]}
        )

        self.assertEqual(result["categories"]["schools"], [])
        self.assertIn("schools", result["category_errors"])

    @patch("services.geospatial_service.requests.get")
    def test_features_not_a_list_is_handled(self, mock_get):

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"features": "not-a-list"}
        mock_get.return_value = mock_response

        result = geo.get_nearby_pois(
            12.84, 80.15,
            api_key="fake-key",
            categories={"schools": geo.POI_CATEGORIES["schools"]}
        )

        self.assertEqual(result["categories"]["schools"], [])
        self.assertIn("schools", result["category_errors"])

    @patch("services.geospatial_service.requests.get")
    def test_empty_results_is_not_an_error(self, mock_get):

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"features": []}
        mock_get.return_value = mock_response

        result = geo.get_nearby_pois(
            12.84, 80.15,
            api_key="fake-key",
            categories={"parks": geo.POI_CATEGORIES["parks"]}
        )

        self.assertEqual(result["categories"]["parks"], [])
        self.assertNotIn("parks", result["category_errors"])

    @patch("services.geospatial_service.requests.get")
    def test_one_group_failing_does_not_affect_others(self, mock_get):

        def side_effect(url, params=None, timeout=None):

            if "education.school" in params["categories"]:
                raise requests_module.exceptions.ConnectionError()

            response = Mock()
            response.status_code = 200
            response.json.return_value = {
                "features": [
                    feature(
                        "Some Park", 12.85, 80.16,
                        categories=["leisure", "leisure.park"]
                    )
                ]
            }
            return response

        mock_get.side_effect = side_effect

        result = geo.get_nearby_pois(
            12.8423, 80.1538,
            api_key="fake-key",
            categories={
                "schools": geo.POI_CATEGORIES["schools"],
                "parks": geo.POI_CATEGORIES["parks"],
            }
        )

        self.assertEqual(result["categories"]["schools"], [])
        self.assertIn("schools", result["category_errors"])

        self.assertEqual(len(result["categories"]["parks"]), 1)
        self.assertNotIn("parks", result["category_errors"])


# ============================================================
# get_nearby_pois - sorting / limits / radius
# ============================================================

class GetNearbyPoisBehaviorTests(unittest.TestCase):

    @patch("services.geospatial_service.requests.get")
    def test_results_sorted_by_distance_and_limited(self, mock_get):

        origin_lat, origin_lon = 12.8423, 80.1538

        far = feature("Far School", 13.50, 80.90, categories=["education.school"])
        near = feature("Near School", 12.8430, 80.1545, categories=["education.school"])
        mid = feature("Mid School", 12.90, 80.20, categories=["education.school"])

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"features": [far, near, mid]}
        mock_get.return_value = mock_response

        result = geo.get_nearby_pois(
            origin_lat, origin_lon,
            api_key="fake-key",
            categories={"schools": geo.POI_CATEGORIES["schools"]},
            max_results=2
        )

        schools = result["categories"]["schools"]

        self.assertEqual(len(schools), 2)
        self.assertEqual(schools[0]["name"], "Near School")
        self.assertEqual(schools[1]["name"], "Mid School")
        self.assertLess(schools[0]["distance_km"], schools[1]["distance_km"])

    @patch("services.geospatial_service.requests.get")
    def test_radius_and_limit_are_passed_to_geoapify(self, mock_get):

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"features": []}
        mock_get.return_value = mock_response

        geo.get_nearby_pois(
            12.8423, 80.1538,
            api_key="fake-key",
            categories={"schools": geo.POI_CATEGORIES["schools"]},
            radius_m=2000,
            max_results=3
        )

        _, kwargs = mock_get.call_args

        self.assertIn("circle:80.1538,12.8423,2000", kwargs["params"]["filter"])
        self.assertEqual(kwargs["params"]["limit"], 3)

    @patch("services.geospatial_service.requests.get")
    def test_group_fetch_limit_scales_with_leaf_count_and_is_capped(self, mock_get):

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"features": []}
        mock_get.return_value = mock_response

        # "food" has 4 leaves; with max_results=10 the raw fetch should
        # ask for 40 (4 x 10), not 10 and not an arbitrary flat number.
        geo.get_nearby_pois(
            12.8423, 80.1538,
            api_key="fake-key",
            categories={
                leaf: geo.POI_CATEGORIES[leaf]
                for leaf in geo.POI_CATEGORY_GROUPS["food"]
            },
            max_results=10
        )

        _, kwargs = mock_get.call_args

        self.assertEqual(kwargs["params"]["limit"], 40)


# ============================================================
# get_nearby_pois - grouped-query classification
# ============================================================

class GroupedQueryClassificationTests(unittest.TestCase):

    @patch("services.geospatial_service.requests.get")
    def test_different_categories_in_one_group_remain_distinguishable(self, mock_get):

        restaurant = feature(
            "Some Restaurant", 12.85, 80.16,
            categories=["catering", "catering.restaurant"]
        )

        cafe = feature(
            "Some Cafe", 12.86, 80.17,
            categories=["catering", "catering.cafe"]
        )

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"features": [restaurant, cafe]}
        mock_get.return_value = mock_response

        result = geo.get_nearby_pois(
            12.8423, 80.1538,
            api_key="fake-key",
            categories={
                leaf: geo.POI_CATEGORIES[leaf]
                for leaf in geo.POI_CATEGORY_GROUPS["food"]
            }
        )

        self.assertEqual(len(result["categories"]["restaurants"]), 1)
        self.assertEqual(result["categories"]["restaurants"][0]["name"], "Some Restaurant")
        self.assertEqual(result["categories"]["restaurants"][0]["category_group"], "food")

        self.assertEqual(len(result["categories"]["cafes"]), 1)
        self.assertEqual(result["categories"]["cafes"][0]["name"], "Some Cafe")

        self.assertEqual(result["categories"]["fast_food"], [])
        self.assertEqual(result["categories"]["food_courts"], [])

    @patch("services.geospatial_service.requests.get")
    def test_poi_matching_multiple_leaves_appears_in_both(self, mock_get):

        # A real-world fuel station that also offers EV charging.
        combo = feature(
            "Highway Fuel + EV", 12.85, 80.16,
            categories=[
                "service", "service.vehicle",
                "service.vehicle.fuel",
                "service.vehicle.charging_station"
            ]
        )

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"features": [combo]}
        mock_get.return_value = mock_response

        result = geo.get_nearby_pois(
            12.8423, 80.1538,
            api_key="fake-key",
            categories={
                leaf: geo.POI_CATEGORIES[leaf]
                for leaf in geo.POI_CATEGORY_GROUPS["vehicle_services"]
            }
        )

        self.assertEqual(len(result["categories"]["fuel_stations"]), 1)
        self.assertEqual(len(result["categories"]["ev_charging"]), 1)
        self.assertEqual(result["categories"]["car_wash"], [])

    @patch("services.geospatial_service.requests.get")
    def test_ambiguous_feature_without_a_matching_leaf_is_dropped(self, mock_get):

        # Matched the combined OR-query (e.g. via a broad parent tag)
        # but doesn't confirm any of our specific leaf codes.
        ambiguous = feature(
            "Mystery Place", 12.85, 80.16,
            categories=["commercial"]
        )

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"features": [ambiguous]}
        mock_get.return_value = mock_response

        result = geo.get_nearby_pois(
            12.8423, 80.1538,
            api_key="fake-key",
            categories={
                leaf: geo.POI_CATEGORIES[leaf]
                for leaf in geo.POI_CATEGORY_GROUPS["shopping"]
            }
        )

        for pois in result["categories"].values():
            self.assertEqual(pois, [])


# ============================================================
# Legacy alias backward compatibility
# ============================================================

class LegacyAliasTests(unittest.TestCase):

    @patch("services.geospatial_service.requests.get")
    def test_original_six_category_keys_present_in_default_response(self, mock_get):

        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"features": []}
        mock_get.return_value = mock_response

        result = geo.get_nearby_pois(12.8423, 80.1538, api_key="fake-key")

        for legacy_key in (
            "schools", "hospitals", "restaurants",
            "parks", "public_transport", "shopping"
        ):
            self.assertIn(legacy_key, result["categories"])

    @patch("services.geospatial_service.requests.get")
    def test_shopping_alias_merges_and_resorts_its_members(self, mock_get):

        def side_effect(url, params=None, timeout=None):

            response = Mock()
            response.status_code = 200

            if "commercial.supermarket" in params["categories"]:

                response.json.return_value = {
                    "features": [
                        feature(
                            "Far Supermarket", 12.90, 80.20,
                            categories=["commercial.supermarket"]
                        ),
                        feature(
                            "Near Mall", 12.8430, 80.1545,
                            categories=["commercial.shopping_mall"]
                        ),
                    ]
                }

            else:
                response.json.return_value = {"features": []}

            return response

        mock_get.side_effect = side_effect

        result = geo.get_nearby_pois(
            12.8423, 80.1538,
            api_key="fake-key",
            categories={
                leaf: geo.POI_CATEGORIES[leaf]
                for leaf in geo.POI_CATEGORY_GROUPS["shopping"]
            }
        )

        shopping = result["categories"]["shopping"]

        self.assertEqual(len(shopping), 2)
        self.assertEqual(shopping[0]["name"], "Near Mall")
        self.assertEqual(shopping[1]["name"], "Far Supermarket")

    def test_hospitals_is_not_in_legacy_aliases(self):

        # "hospitals" remains a real leaf category (narrower than
        # before - see module docstring) rather than an alias.
        self.assertNotIn("hospitals", geo.LEGACY_CATEGORY_ALIASES)
        self.assertIn("hospitals", geo.POI_CATEGORIES)
        self.assertEqual(geo.POI_CATEGORIES["hospitals"], ["healthcare.hospital"])


if __name__ == "__main__":
    unittest.main()
