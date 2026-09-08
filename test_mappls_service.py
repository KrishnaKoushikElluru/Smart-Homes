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


if __name__ == "__main__":
    unittest.main()
