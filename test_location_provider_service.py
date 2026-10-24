"""
Unit tests for services/location_provider_service.py.

Run with:
    python -m unittest test_location_provider_service

No network access needed - services.ola_maps_service's HTTP calls are
mocked via unittest.mock, matching the rest of this project's location-
service test conventions.
"""

import unittest
from unittest.mock import patch, Mock

from services import location_provider_service as lps


VIT_BIAS = "12.8406,80.1538"


class ClassifyOlaCandidatesTests(unittest.TestCase):

    def test_no_candidates_is_no_match(self):
        result = lps.classify_ola_candidates("VIT Chennai", [])
        self.assertEqual(result["status"], "no_match")

    def test_strong_single_match_is_matched(self):
        candidates = [{
            "provider": "ola", "place_id": "ola-platform:1",
            "name": "TaTa Value Homes Mambakkam",
            "address": "Kelambakkam - Vandalur Rd, Mambakkam, Tamil Nadu, 600127, India",
            "latitude": 12.8357, "longitude": 80.1565, "types": ["premise"],
        }]
        result = lps.classify_ola_candidates("Tata Value Homes, Mambakkam", candidates)
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["best"]["place_id"], "ola-platform:1")

    def test_weak_generic_result_is_not_silently_matched(self):
        # "Police Quarters" alone shares almost no tokens with a
        # candidate whose real name/address is mostly unrelated text.
        candidates = [{
            "provider": "ola", "place_id": "ola-platform:2",
            "name": "M4 Police Quaters", "address": "Sathyamurthi Nagar, Avadi, Tamil Nadu, 600062, India",
            "latitude": 13.1288, "longitude": 80.1213, "types": ["police"],
        }]
        result = lps.classify_ola_candidates("Police Quarters", candidates)
        # Either rejected by the distance gate (far from no bias -> N/A
        # here, no bias given) or by score - either way, must not be
        # blindly "matched" just because it's the only candidate.
        self.assertIn(result["status"], ("no_match", "ambiguous"))

    def test_candidate_far_from_location_bias_is_gated_out(self):
        # Real "Police Quarters" entity, correct name, but ~28 km from
        # the VIT/Mambakkam bias - the exact live-observed failure mode
        # this gate exists for.
        candidates = [{
            "provider": "ola", "place_id": "ola-platform:3",
            "name": "Police Quarters", "address": "Thousand Lights West, Chennai, Tamil Nadu, 600006, India",
            "latitude": 13.0653, "longitude": 80.2513, "types": ["police"],
        }]
        result = lps.classify_ola_candidates("Police Quarters near VIT Chennai", candidates, location_bias=VIT_BIAS)
        self.assertEqual(result["status"], "no_match")

    def test_candidate_within_bias_distance_is_not_gated(self):
        candidates = [{
            "provider": "ola", "place_id": "ola-platform:4",
            "name": "VIT Chennai", "address": "Kelambakkam - Vandalur Rd, Kandigai, Tamil Nadu, 600127, India",
            "latitude": 12.8473, "longitude": 80.1454, "types": ["point_of_interest"],
        }]
        result = lps.classify_ola_candidates("VIT Chennai", candidates, location_bias=VIT_BIAS)
        self.assertEqual(result["status"], "matched")

    def test_tight_margin_between_top_two_is_ambiguous(self):
        candidates = [
            {
                "provider": "ola", "place_id": "ola-platform:5",
                "name": "Mambakkam", "address": "Chennai, Tamil Nadu, 600127, India",
                "latitude": 12.836, "longitude": 80.167, "types": ["locality"],
            },
            {
                "provider": "ola", "place_id": "ola-platform:6",
                "name": "Mambakkam", "address": "Sriperumbudur, Tamil Nadu, 602106, India",
                "latitude": 12.97, "longitude": 79.95, "types": ["locality"],
            },
        ]
        # No location bias here - both candidates score identically on
        # name text alone, so the margin between them is exactly 0.
        result = lps.classify_ola_candidates("Mambakkam", candidates)
        self.assertEqual(result["status"], "ambiguous")
        self.assertTrue(len(result["alternates"]) >= 2)


class ResolveLocationViaOlaTests(unittest.TestCase):

    def test_autocomplete_error_propagates_as_error(self):
        with patch(
            "services.location_provider_service.ola_maps_service.autocomplete",
            return_value={"status": "error", "candidates": [], "error": "boom"},
        ):
            result = lps.resolve_location_via_ola("VIT Chennai", "key")
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["provider"], "ola")

    def test_autocomplete_no_match_propagates(self):
        with patch(
            "services.location_provider_service.ola_maps_service.autocomplete",
            return_value={"status": "no_match", "candidates": [], "error": None},
        ):
            result = lps.resolve_location_via_ola("asdkfjhaslkdfj", "key")
        self.assertEqual(result["status"], "no_match")

    def test_matched_candidate_resolves_via_place_details(self):
        autocomplete_return = {
            "status": "matched",
            "candidates": [{
                "provider": "ola", "place_id": "ola-platform:5000330359668",
                "name": "TaTa New Haven Ribbon Walk",
                "address": "Next To Vellore Institute Of Technology, Mambakkam, Tamil Nadu, 600127, India",
                "latitude": 12.8358, "longitude": 80.1561, "types": ["real_estate_agency"],
            }],
            "error": None,
        }
        details_return = {
            "status": "matched", "name": "TaTa New Haven Ribbon Walk",
            "formatted_address": "New Haven Ribbon Walk, Mambakkam, Tamil Nadu, 600127, India",
            "latitude": 12.8358, "longitude": 80.1561, "place_id": "ola-platform:5000330359668",
            "types": ["real_estate_agency"], "city": "Chennai", "state": "Tamil Nadu",
            "locality": "Mambakkam", "sub_locality": None, "postcode": "600127", "error": None,
        }
        with patch(
            "services.location_provider_service.ola_maps_service.autocomplete",
            return_value=autocomplete_return,
        ), patch(
            "services.location_provider_service.ola_maps_service.get_place_details",
            return_value=details_return,
        ) as mock_details:
            result = lps.resolve_location_via_ola("Tata New Haven Ribbon Walk", "key")

        mock_details.assert_called_once_with("ola-platform:5000330359668", "key")
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["latitude"], 12.8358)
        self.assertEqual(result["longitude"], 80.1561)
        self.assertEqual(result["provider"], "ola")

    def test_place_details_no_coordinates_is_no_match_not_fabricated(self):
        autocomplete_return = {
            "status": "matched",
            "candidates": [{
                "provider": "ola", "place_id": "ola-platform:1",
                "name": "VIT Chennai", "address": "Kandigai, Tamil Nadu, 600127, India",
                "latitude": 12.8473, "longitude": 80.1454, "types": ["point_of_interest"],
            }],
            "error": None,
        }
        with patch(
            "services.location_provider_service.ola_maps_service.autocomplete",
            return_value=autocomplete_return,
        ), patch(
            "services.location_provider_service.ola_maps_service.get_place_details",
            return_value={"status": "no_match", "latitude": None, "longitude": None,
                           "name": None, "formatted_address": None, "error": None},
        ):
            result = lps.resolve_location_via_ola("VIT Chennai", "key")

        self.assertEqual(result["status"], "no_match")
        self.assertIsNone(result["latitude"])

    def test_ambiguous_result_never_silently_picks_a_location(self):
        candidates = [
            {"provider": "ola", "place_id": "a", "name": "Mambakkam",
             "address": "Chennai, Tamil Nadu, 600127, India", "latitude": 12.836, "longitude": 80.167, "types": []},
            {"provider": "ola", "place_id": "b", "name": "Mambakkam",
             "address": "Sriperumbudur, Tamil Nadu, 602106, India", "latitude": 12.97, "longitude": 79.95, "types": []},
        ]
        with patch(
            "services.location_provider_service.ola_maps_service.autocomplete",
            return_value={"status": "matched", "candidates": candidates, "error": None},
        ) as mock_autocomplete, patch(
            "services.location_provider_service.ola_maps_service.get_place_details",
        ) as mock_details:
            result = lps.resolve_location_via_ola("Mambakkam", "key")

        mock_details.assert_not_called()
        self.assertEqual(result["status"], "ambiguous")
        self.assertIsNone(result["latitude"])
        self.assertIsNone(result["longitude"])
        self.assertTrue(len(result["alternates"]) >= 2)

    def test_ambiguous_alternates_carry_place_id_and_provider_for_the_picker(self):
        # Additive fields (see location_provider_service.py's own
        # comment on this) needed so a picked alternate can be
        # re-resolved via the EXISTING
        # /api/location/resolve-candidate -> resolve_selected_candidate()
        # -> Ola Place Details path, instead of trusting a raw
        # autocomplete coordinate as final.
        candidates = [
            {"provider": "ola", "place_id": "ola-platform:a", "name": "Mambakkam",
             "address": "Chennai, Tamil Nadu, 600127, India", "latitude": 12.836, "longitude": 80.167, "types": []},
            {"provider": "ola", "place_id": "ola-platform:b", "name": "Mambakkam",
             "address": "Sriperumbudur, Tamil Nadu, 602106, India", "latitude": 12.97, "longitude": 79.95, "types": []},
        ]
        with patch(
            "services.location_provider_service.ola_maps_service.autocomplete",
            return_value={"status": "matched", "candidates": candidates, "error": None},
        ), patch(
            "services.location_provider_service.ola_maps_service.get_place_details",
        ):
            result = lps.resolve_location_via_ola("Mambakkam", "key")

        self.assertEqual(result["status"], "ambiguous")
        place_ids = {alt["place_id"] for alt in result["alternates"]}
        self.assertEqual(place_ids, {"ola-platform:a", "ola-platform:b"})
        self.assertTrue(all(alt["provider"] == "ola" for alt in result["alternates"]))
        # Existing fields untouched - a caller reading only these 5
        # (e.g. the picker code written before this phase) still works.
        self.assertEqual(
            set(result["alternates"][0].keys()),
            {"matched_name", "matched_address", "latitude", "longitude", "score", "place_id", "provider"},
        )


class ResolveSelectedCandidateTests(unittest.TestCase):

    def test_ola_candidate_resolves_via_place_details(self):
        candidate = {"provider": "ola", "place_id": "ola-platform:1", "name": "VIT Chennai", "address": "..."}
        details_return = {
            "status": "matched", "latitude": 12.8473, "longitude": 80.1454,
            "formatted_address": "VIT Chennai, Tamil Nadu, 600127, India",
            "city": "Chennai", "state": "Tamil Nadu", "locality": "Kandigai",
            "sub_locality": None, "postcode": "600127", "error": None,
            "name": "VIT Chennai", "place_id": "ola-platform:1", "types": [],
        }
        with patch(
            "services.location_provider_service.ola_maps_service.get_place_details",
            return_value=details_return,
        ):
            result = lps.resolve_selected_candidate(candidate, ola_api_key="key")

        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["provider"], "ola")
        self.assertEqual(result["latitude"], 12.8473)
        self.assertEqual(result["city"], "Chennai")

    def test_mappls_candidate_resolves_via_osm(self):
        candidate = {"provider": "mappls", "name": "VIT Chennai", "address": "Vandalur, Chennai, Tamil Nadu, 600127"}

        fake_osm = Mock()
        fake_osm.resolve_coordinates.return_value = {
            "status": "matched", "latitude": 12.8406, "longitude": 80.1538,
            "display_name": "VIT Chennai, Chennai, Tamil Nadu, India", "error": None,
        }

        result = lps.resolve_selected_candidate(candidate, osm_service=fake_osm)

        fake_osm.resolve_coordinates.assert_called_once()
        self.assertEqual(result["status"], "matched")
        self.assertEqual(result["provider"], "osm")
        self.assertEqual(result["latitude"], 12.8406)

    def test_mappls_candidate_osm_no_match_never_fabricates_coordinates(self):
        candidate = {"provider": "mappls", "name": "Nonexistent Place", "address": "Nowhere"}

        fake_osm = Mock()
        fake_osm.resolve_coordinates.return_value = {
            "status": "no_match", "latitude": None, "longitude": None,
            "display_name": None, "error": "No OSM candidates found.",
        }

        result = lps.resolve_selected_candidate(candidate, osm_service=fake_osm)

        self.assertEqual(result["status"], "no_match")
        self.assertIsNone(result["latitude"])
        self.assertIsNone(result["longitude"])

    def test_unknown_provider_returns_error(self):
        result = lps.resolve_selected_candidate({"provider": "geoapify"})
        self.assertEqual(result["status"], "error")


if __name__ == "__main__":
    unittest.main()
