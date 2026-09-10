"""
Unit tests for services/mappls_service.py.

Run with:
    python -m unittest test_mappls_service

No network access needed - the Mappls HTTP call is mocked via
unittest.mock, matching test_geospatial_service.py's convention.
"""

import unittest
from unittest.mock import patch, Mock

import requests as requests_module

from services import mappls_service


def _mock_response(status_code=200, json_data=None):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    return response


class ResolvePlaceTests(unittest.TestCase):

    def test_empty_query_returns_error_without_network_call(self):

        with patch("services.mappls_service.requests.get") as mock_get:

            result = mappls_service.resolve_place("   ", api_key="key123")

            mock_get.assert_not_called()
            self.assertEqual(result["status"], "error")
            self.assertIn("Empty query", result["error"])

    def test_missing_api_key_returns_error_without_network_call(self):

        with patch("services.mappls_service.requests.get") as mock_get:

            result = mappls_service.resolve_place("VIT Chennai", api_key=None)

            mock_get.assert_not_called()
            self.assertEqual(result["status"], "error")

    def test_successful_match_returns_top_candidate(self):

        response = _mock_response(200, {
            "suggestedLocations": [
                {
                    "placeName": "VIT Chennai",
                    "placeAddress": "Vandalur Kelambakkam Road, Chennai, Tamil Nadu, 600127",
                    "eLoc": "2NB2R6",
                    "type": "POI",
                },
                {
                    "placeName": "VIT Chennai Gate",
                    "placeAddress": "Chennai, Tamil Nadu, 600127",
                    "eLoc": "UNQ5OS",
                    "type": "POI",
                },
            ]
        })

        with patch("services.mappls_service.requests.get", return_value=response):

            result = mappls_service.resolve_place("VIT Chennai", api_key="key123")

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["place_name"], "VIT Chennai")
        self.assertEqual(result["eloc"], "2NB2R6")
        # Mappls' own top-ranked candidate must be trusted, not re-ranked.
        self.assertNotEqual(result["place_name"], "VIT Chennai Gate")

    def test_no_candidates_returns_no_match(self):

        response = _mock_response(200, {"suggestedLocations": []})

        with patch("services.mappls_service.requests.get", return_value=response):

            result = mappls_service.resolve_place("asdkfjhaslkdfj", api_key="key123")

        self.assertEqual(result["status"], "no_match")

    def test_204_returns_no_match(self):

        response = _mock_response(204)

        with patch("services.mappls_service.requests.get", return_value=response):

            result = mappls_service.resolve_place("VIT Chennai", api_key="key123")

        self.assertEqual(result["status"], "no_match")

    def test_http_error_returns_error(self):

        response = _mock_response(401)

        with patch("services.mappls_service.requests.get", return_value=response):

            result = mappls_service.resolve_place("VIT Chennai", api_key="badkey")

        self.assertEqual(result["status"], "error")
        self.assertIn("401", result["error"])

    def test_network_failure_returns_error(self):

        with patch(
            "services.mappls_service.requests.get",
            side_effect=requests_module.ConnectionError("boom"),
        ):

            result = mappls_service.resolve_place("VIT Chennai", api_key="key123")

        self.assertEqual(result["status"], "error")

    def test_location_bias_is_passed_through(self):

        response = _mock_response(200, {"suggestedLocations": []})

        with patch("services.mappls_service.requests.get", return_value=response) as mock_get:

            mappls_service.resolve_place(
                "VIT Chennai", api_key="key123", location_bias="12.9716,80.2217"
            )

            _, kwargs = mock_get.call_args
            self.assertEqual(kwargs["params"]["location"], "12.9716,80.2217")


class FindNearbyPlacesTests(unittest.TestCase):

    def test_empty_keywords_returns_error_without_network_call(self):

        with patch("services.mappls_service.requests.get") as mock_get:

            result = mappls_service.find_nearby_places(
                "   ", ref_location="12.84,80.15", radius_m=3000, api_key="key123"
            )

            mock_get.assert_not_called()
            self.assertEqual(result["status"], "error")

    def test_missing_ref_location_returns_error_without_network_call(self):

        with patch("services.mappls_service.requests.get") as mock_get:

            result = mappls_service.find_nearby_places(
                "gym", ref_location="", radius_m=3000, api_key="key123"
            )

            mock_get.assert_not_called()
            self.assertEqual(result["status"], "error")

    def test_missing_api_key_returns_error_without_network_call(self):

        with patch("services.mappls_service.requests.get") as mock_get:

            result = mappls_service.find_nearby_places(
                "gym", ref_location="12.84,80.15", radius_m=3000, api_key=None
            )

            mock_get.assert_not_called()
            self.assertEqual(result["status"], "error")

    def test_successful_search_returns_places_with_provider_distance(self):

        response = _mock_response(200, {
            "suggestedLocations": [
                {
                    "placeName": "Infinite Lifestyle and Fitness Studio",
                    "placeAddress": "Melakottaiyur, Chennai, Tamil Nadu, 600127",
                    "eLoc": "HDIZ5V",
                    "type": "POI",
                    "distance": 781,
                    "orderIndex": 1,
                },
                {
                    "placeName": "Assisi Gym",
                    "placeAddress": "657, 8th Street Rajiv Gandhi Nagar, Chennai, Tamil Nadu, 600127",
                    "eLoc": "2FLCYM",
                    "type": "POI",
                    "distance": 1578,
                    "orderIndex": 2,
                },
            ],
            "pageInfo": {"pageCount": 1, "totalHits": 2},
        })

        with patch("services.mappls_service.requests.get", return_value=response):

            result = mappls_service.find_nearby_places(
                "gym", ref_location="12.8406,80.1538", radius_m=3000, api_key="key123"
            )

        self.assertEqual(result["status"], "matched")
        self.assertEqual(len(result["places"]), 2)
        self.assertEqual(result["places"][0]["place_name"], "Infinite Lifestyle and Fitness Studio")
        self.assertEqual(result["places"][0]["eloc"], "HDIZ5V")
        self.assertEqual(result["places"][0]["distance_m"], 781)
        # Never fabricates coordinates - this endpoint doesn't return them.
        self.assertNotIn("latitude", result["places"][0])
        self.assertNotIn("longitude", result["places"][0])

    def test_no_candidates_returns_no_match(self):

        response = _mock_response(200, {"suggestedLocations": []})

        with patch("services.mappls_service.requests.get", return_value=response):

            result = mappls_service.find_nearby_places(
                "gym", ref_location="0,0", radius_m=3000, api_key="key123"
            )

        self.assertEqual(result["status"], "no_match")

    def test_204_returns_no_match(self):

        response = _mock_response(204)

        with patch("services.mappls_service.requests.get", return_value=response):

            result = mappls_service.find_nearby_places(
                "gym", ref_location="12.84,80.15", radius_m=3000, api_key="key123"
            )

        self.assertEqual(result["status"], "no_match")

    def test_http_error_returns_error(self):

        response = _mock_response(401)

        with patch("services.mappls_service.requests.get", return_value=response):

            result = mappls_service.find_nearby_places(
                "gym", ref_location="12.84,80.15", radius_m=3000, api_key="badkey"
            )

        self.assertEqual(result["status"], "error")
        self.assertIn("401", result["error"])

    def test_network_failure_returns_error(self):

        with patch(
            "services.mappls_service.requests.get",
            side_effect=requests_module.ConnectionError("boom"),
        ):

            result = mappls_service.find_nearby_places(
                "gym", ref_location="12.84,80.15", radius_m=3000, api_key="key123"
            )

        self.assertEqual(result["status"], "error")

    def test_malformed_candidate_entries_are_skipped_not_fatal(self):

        response = _mock_response(200, {
            "suggestedLocations": [
                "not a dict",
                {"placeName": "Real Gym", "eLoc": "ABC123", "distance": 500},
            ]
        })

        with patch("services.mappls_service.requests.get", return_value=response):

            result = mappls_service.find_nearby_places(
                "gym", ref_location="12.84,80.15", radius_m=3000, api_key="key123"
            )

        self.assertEqual(result["status"], "matched")
        self.assertEqual(len(result["places"]), 1)
        self.assertEqual(result["places"][0]["place_name"], "Real Gym")

    def test_params_passed_through_correctly(self):

        response = _mock_response(200, {"suggestedLocations": []})

        with patch("services.mappls_service.requests.get", return_value=response) as mock_get:

            mappls_service.find_nearby_places(
                "hospital", ref_location="12.84,80.15", radius_m=2000, api_key="key123"
            )

            _, kwargs = mock_get.call_args
            self.assertEqual(kwargs["params"]["keywords"], "hospital")
            self.assertEqual(kwargs["params"]["refLocation"], "12.84,80.15")
            self.assertEqual(kwargs["params"]["radius"], 2000)
            self.assertEqual(kwargs["params"]["access_token"], "key123")

    def test_float_radius_is_sent_as_a_clean_integer(self):
        # Regression test: Mappls' Nearby API returns HTTP 400 for a
        # decimal radius (e.g. "2000.0") - confirmed live. Callers
        # naturally compute radius_km * 1000.0, a float; this function
        # must normalize it before it ever reaches the request.
        response = _mock_response(200, {"suggestedLocations": []})

        with patch("services.mappls_service.requests.get", return_value=response) as mock_get:

            mappls_service.find_nearby_places(
                "gym", ref_location="12.84,80.15", radius_m=2000.0, api_key="key123"
            )

            _, kwargs = mock_get.call_args
            self.assertEqual(kwargs["params"]["radius"], 2000)
            self.assertIsInstance(kwargs["params"]["radius"], int)

    def test_invalid_radius_returns_error_without_network_call(self):

        with patch("services.mappls_service.requests.get") as mock_get:

            result = mappls_service.find_nearby_places(
                "gym", ref_location="12.84,80.15", radius_m="not-a-number", api_key="key123"
            )

            mock_get.assert_not_called()
            self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
