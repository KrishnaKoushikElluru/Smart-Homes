"""
Unit tests for services/ola_maps_service.py.

Run with:
    python -m unittest test_ola_maps_service

No network access needed - the Ola Maps HTTP calls are mocked via
unittest.mock, matching test_mappls_service.py's convention.
"""

import unittest
from unittest.mock import patch, Mock

import requests as requests_module

from services import ola_maps_service


def _mock_response(status_code=200, json_data=None):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data or {}
    return response


class AutocompleteTests(unittest.TestCase):

    def test_empty_query_returns_error_without_network_call(self):

        with patch("services.ola_maps_service.requests.get") as mock_get:

            result = ola_maps_service.autocomplete("   ", api_key="key123")

            mock_get.assert_not_called()
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["candidates"], [])

    def test_missing_api_key_returns_error_without_network_call(self):

        with patch("services.ola_maps_service.requests.get") as mock_get:

            result = ola_maps_service.autocomplete("VIT Chennai", api_key=None)

            mock_get.assert_not_called()
            self.assertEqual(result["status"], "error")

    def test_successful_autocomplete_returns_candidates_with_coordinates(self):

        response = _mock_response(200, {
            "predictions": [
                {
                    "description": "TaTa Value Homes Mambakkam, Kelambakkam - Vandalur Rd, Mambakkam, Tamil Nadu, 600127, India",
                    "structured_formatting": {
                        "main_text": "TaTa Value Homes Mambakkam",
                        "secondary_text": "Kelambakkam - Vandalur Rd, Mambakkam, Tamil Nadu, 600127, India",
                    },
                    "place_id": "ola-platform:5000051202741",
                    "types": ["premise", "subpremise"],
                    "geometry": {"location": {"lat": 12.8357, "lng": 80.1565}},
                },
            ]
        })

        with patch("services.ola_maps_service.requests.get", return_value=response):

            result = ola_maps_service.autocomplete("Tata Value Homes, Mambakkam", api_key="key123")

        self.assertEqual(result["status"], "matched")
        self.assertEqual(len(result["candidates"]), 1)
        candidate = result["candidates"][0]
        self.assertEqual(candidate["provider"], "ola")
        self.assertEqual(candidate["place_id"], "ola-platform:5000051202741")
        self.assertEqual(candidate["name"], "TaTa Value Homes Mambakkam")
        self.assertEqual(candidate["latitude"], 12.8357)
        self.assertEqual(candidate["longitude"], 80.1565)

    def test_candidate_without_coordinates_still_returned(self):
        # Not every Ola prediction includes geometry - the candidate must
        # still be usable (get_place_details() resolves it later), never
        # dropped just for missing coordinates at this stage.

        response = _mock_response(200, {
            "predictions": [
                {
                    "description": "Some Place, Chennai, Tamil Nadu, India",
                    "structured_formatting": {"main_text": "Some Place"},
                    "place_id": "ola-platform:123",
                    "types": ["establishment"],
                },
            ]
        })

        with patch("services.ola_maps_service.requests.get", return_value=response):

            result = ola_maps_service.autocomplete("Some Place", api_key="key123")

        self.assertEqual(result["status"], "matched")
        self.assertIsNone(result["candidates"][0]["latitude"])
        self.assertIsNone(result["candidates"][0]["longitude"])

    def test_candidate_without_place_id_is_skipped(self):

        response = _mock_response(200, {
            "predictions": [
                {"description": "No place id here", "structured_formatting": {}},
            ]
        })

        with patch("services.ola_maps_service.requests.get", return_value=response):

            result = ola_maps_service.autocomplete("query", api_key="key123")

        self.assertEqual(result["status"], "no_match")

    def test_empty_predictions_returns_no_match(self):

        response = _mock_response(200, {"predictions": []})

        with patch("services.ola_maps_service.requests.get", return_value=response):

            result = ola_maps_service.autocomplete("asdkfjhaslkdfj", api_key="key123")

        self.assertEqual(result["status"], "no_match")

    def test_malformed_response_returns_no_match_not_crash(self):

        response = _mock_response(200, {"unexpected": "shape"})

        with patch("services.ola_maps_service.requests.get", return_value=response):

            result = ola_maps_service.autocomplete("query", api_key="key123")

        self.assertEqual(result["status"], "no_match")

    def test_http_error_returns_error(self):

        response = _mock_response(401)

        with patch("services.ola_maps_service.requests.get", return_value=response):

            result = ola_maps_service.autocomplete("VIT Chennai", api_key="badkey")

        self.assertEqual(result["status"], "error")
        self.assertIn("401", result["error"])

    def test_network_failure_returns_error(self):

        with patch(
            "services.ola_maps_service.requests.get",
            side_effect=requests_module.ConnectionError("boom"),
        ):

            result = ola_maps_service.autocomplete("VIT Chennai", api_key="key123")

        self.assertEqual(result["status"], "error")

    def test_unreadable_json_returns_error(self):

        response = Mock()
        response.status_code = 200
        response.json.side_effect = ValueError("not json")

        with patch("services.ola_maps_service.requests.get", return_value=response):

            result = ola_maps_service.autocomplete("VIT Chennai", api_key="key123")

        self.assertEqual(result["status"], "error")

    def test_location_bias_is_passed_through(self):

        response = _mock_response(200, {"predictions": []})

        with patch("services.ola_maps_service.requests.get", return_value=response) as mock_get:

            ola_maps_service.autocomplete(
                "VIT Chennai", api_key="key123", location_bias="12.9716,80.2217"
            )

            _, kwargs = mock_get.call_args
            self.assertEqual(kwargs["params"]["location"], "12.9716,80.2217")
            self.assertEqual(kwargs["params"]["api_key"], "key123")

    def test_no_location_bias_omits_location_param(self):

        response = _mock_response(200, {"predictions": []})

        with patch("services.ola_maps_service.requests.get", return_value=response) as mock_get:

            ola_maps_service.autocomplete("VIT Chennai", api_key="key123")

            _, kwargs = mock_get.call_args
            self.assertNotIn("location", kwargs["params"])

    def test_timeout_is_bounded(self):

        response = _mock_response(200, {"predictions": []})

        with patch("services.ola_maps_service.requests.get", return_value=response) as mock_get:

            ola_maps_service.autocomplete("VIT Chennai", api_key="key123")

            _, kwargs = mock_get.call_args
            self.assertEqual(kwargs["timeout"], ola_maps_service.REQUEST_TIMEOUT_SECONDS)


class PlaceDetailsTests(unittest.TestCase):

    def test_empty_place_id_returns_error_without_network_call(self):

        with patch("services.ola_maps_service.requests.get") as mock_get:

            result = ola_maps_service.get_place_details("", api_key="key123")

            mock_get.assert_not_called()
            self.assertEqual(result["status"], "error")

    def test_missing_api_key_returns_error_without_network_call(self):

        with patch("services.ola_maps_service.requests.get") as mock_get:

            result = ola_maps_service.get_place_details("ola-platform:123", api_key=None)

            mock_get.assert_not_called()
            self.assertEqual(result["status"], "error")

    def test_successful_details_extracts_coordinates_and_address(self):

        response = _mock_response(200, {
            "html_attributions": [],
            "result": {
                "name": "TaTa Value Homes Mambakkam",
                "formatted_address": "TaTa Value Homes Mambakkam, Kelambakkam - Vandalur Rd, Mambakkam, Tamil Nadu, 600127, India",
                "geometry": {"location": {"lat": 12.8357, "lng": 80.1565}},
                "place_id": "ola-platform:5000051202741",
                "types": ["premise", "subpremise"],
                "address_components": [
                    {"long_name": "India", "short_name": "India", "types": ["country"]},
                    {"long_name": "Tamil Nadu", "short_name": "Tamil Nadu", "types": ["administrative_area_level_1"]},
                    {"long_name": "Chennai", "short_name": "Chennai", "types": ["locality"]},
                    {"long_name": "Mambakkam", "short_name": "Mambakkam", "types": ["postal_town"]},
                    {"long_name": "600127", "short_name": "600127", "types": ["postal_code"]},
                ],
            },
        })

        with patch("services.ola_maps_service.requests.get", return_value=response):

            result = ola_maps_service.get_place_details("ola-platform:5000051202741", api_key="key123")

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["latitude"], 12.8357)
        self.assertEqual(result["longitude"], 80.1565)
        self.assertEqual(result["name"], "TaTa Value Homes Mambakkam")
        self.assertEqual(result["city"], "Chennai")
        self.assertEqual(result["state"], "Tamil Nadu")
        self.assertEqual(result["locality"], "Mambakkam")
        self.assertEqual(result["postcode"], "600127")

    def test_missing_coordinates_returns_no_match_not_fabricated(self):

        response = _mock_response(200, {
            "result": {
                "name": "Some Place",
                "formatted_address": "Somewhere",
                "geometry": {},
                "place_id": "ola-platform:1",
                "address_components": [],
            }
        })

        with patch("services.ola_maps_service.requests.get", return_value=response):

            result = ola_maps_service.get_place_details("ola-platform:1", api_key="key123")

        self.assertEqual(result["status"], "no_match")
        self.assertIsNone(result["latitude"])
        self.assertIsNone(result["longitude"])

    def test_missing_result_key_returns_no_match(self):

        response = _mock_response(200, {"html_attributions": []})

        with patch("services.ola_maps_service.requests.get", return_value=response):

            result = ola_maps_service.get_place_details("ola-platform:1", api_key="key123")

        self.assertEqual(result["status"], "no_match")

    def test_http_error_returns_error(self):

        response = _mock_response(404)

        with patch("services.ola_maps_service.requests.get", return_value=response):

            result = ola_maps_service.get_place_details("ola-platform:1", api_key="key123")

        self.assertEqual(result["status"], "error")
        self.assertIn("404", result["error"])

    def test_network_failure_returns_error(self):

        with patch(
            "services.ola_maps_service.requests.get",
            side_effect=requests_module.Timeout("boom"),
        ):

            result = ola_maps_service.get_place_details("ola-platform:1", api_key="key123")

        self.assertEqual(result["status"], "error")


class ReverseGeocodeTests(unittest.TestCase):

    def test_invalid_coordinates_returns_error_without_network_call(self):

        with patch("services.ola_maps_service.requests.get") as mock_get:

            result = ola_maps_service.reverse_geocode("not-a-number", 80.15, api_key="key123")

            mock_get.assert_not_called()
            self.assertEqual(result["status"], "error")

    def test_missing_api_key_returns_error_without_network_call(self):

        with patch("services.ola_maps_service.requests.get") as mock_get:

            result = ola_maps_service.reverse_geocode(12.84, 80.15, api_key=None)

            mock_get.assert_not_called()
            self.assertEqual(result["status"], "error")

    def test_successful_reverse_geocode(self):

        response = _mock_response(200, {
            "results": [
                {
                    "formatted_address": "Vellore Institute Of Technology - Chennai, Chennai, Tamil Nadu, 600127, India",
                    "address_components": [
                        {"long_name": "Tamil Nadu", "short_name": "Tamil Nadu", "types": ["administrative_area_level_1"]},
                        {"long_name": "Chennai", "short_name": "Chennai", "types": ["locality"]},
                        {"long_name": "Melakottaiyur", "short_name": "Melakottaiyur", "types": ["sublocality"]},
                        {"long_name": "600127", "short_name": "600127", "types": ["postal_code"]},
                    ],
                }
            ]
        })

        with patch("services.ola_maps_service.requests.get", return_value=response):

            result = ola_maps_service.reverse_geocode(12.8406, 80.1538, api_key="key123")

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["city"], "Chennai")
        self.assertEqual(result["state"], "Tamil Nadu")
        self.assertEqual(result["locality"], "Melakottaiyur")
        self.assertEqual(result["postcode"], "600127")

    def test_no_results_returns_no_match(self):

        response = _mock_response(200, {"results": []})

        with patch("services.ola_maps_service.requests.get", return_value=response):

            result = ola_maps_service.reverse_geocode(0, 0, api_key="key123")

        self.assertEqual(result["status"], "no_match")

    def test_http_error_returns_error(self):

        response = _mock_response(500)

        with patch("services.ola_maps_service.requests.get", return_value=response):

            result = ola_maps_service.reverse_geocode(12.84, 80.15, api_key="key123")

        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
