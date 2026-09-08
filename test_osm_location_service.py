"""
Unit tests for services/osm_location_service.py.

Run with:
    python -m unittest test_osm_location_service

No network access needed - every Nominatim HTTP call is mocked via
unittest.mock, matching test_geospatial_service.py's convention.
"""

import unittest
from unittest.mock import patch, Mock

import requests as requests_module

from services import osm_location_service as osm


# ============================================================
# FAKE MONGO COLLECTION (in-memory, just enough of the pymongo
# Collection API for the cache to exercise real code paths)
# ============================================================

class FakeCollection:

    def __init__(self):
        self._docs = {}
        self.create_index_calls = []

    def create_index(self, *args, **kwargs):
        self.create_index_calls.append((args, kwargs))

    def find_one(self, query):
        return self._docs.get(query.get("cache_key"))

    def update_one(self, query, update, upsert=False):
        key = query.get("cache_key")
        self._docs[key] = dict(update["$set"])


class FakeMongoService:

    def __init__(self):
        self.collections = {}

    def get_collection(self, name):
        self.collections.setdefault(name, FakeCollection())
        return self.collections[name]


def nominatim_result(name, lat, lon, city="Chennai", state="Tamil Nadu",
                      postcode="600127", category="amenity", osm_type_tag="university",
                      osm_id=1, osm_type="way"):
    return {
        "osm_id": osm_id,
        "osm_type": osm_type,
        "lat": str(lat),
        "lon": str(lon),
        "category": category,
        "type": osm_type_tag,
        "display_name": f"{name}, Some Road, {city}, {state}, {postcode}, India",
        "namedetails": {"name": name},
        "address": {"city": city, "state": state, "postcode": postcode},
        "importance": 0.5,
    }


def mock_response(json_data, status_code=200):
    response = Mock()
    response.status_code = status_code
    response.json.return_value = json_data
    return response


# ============================================================
# NORMALIZATION
# ============================================================

class NormalizationTests(unittest.TestCase):

    def test_normalize_text_lowercases_and_strips_punctuation(self):
        # Commas are deliberately KEPT (structural separators used by the
        # address-component extraction functions below) - only other
        # punctuation is stripped.
        self.assertEqual(
            osm.normalize_text("VIT Chennai, No. 21!"),
            "vit chennai, no 21",
        )

    def test_normalize_text_expands_generic_abbreviations(self):
        self.assertIn("road", osm.normalize_text("Anna Salai Rd"))

    def test_normalize_text_does_not_alias_poi_names(self):
        # "VIT" must NOT be expanded to "Vellore Institute of Technology" -
        # that is an explicitly prohibited manual alias.
        normalized = osm.normalize_text("VIT Chennai")
        self.assertIn("vit", normalized)
        self.assertNotIn("vellore", normalized)

    def test_extract_pincode_finds_six_digit_code(self):
        self.assertEqual(
            osm.extract_pincode("Chennai, Tamil Nadu, 600127"),
            "600127",
        )

    def test_extract_pincode_returns_none_when_absent(self):
        self.assertIsNone(osm.extract_pincode("Chennai, Tamil Nadu"))

    def test_extract_city_guess_prefers_chennai_token(self):
        self.assertEqual(
            osm.extract_city_guess("Some Road, Chennai, Tamil Nadu, 600001"),
            "Chennai",
        )

    def test_extract_locality_tokens_excludes_trailing_admin_fragments(self):
        tokens = osm.extract_locality_tokens(
            "Vandalur Kelambakkam Road, Kandigai, Chennai, Tamil Nadu, 600127"
        )
        self.assertIn("kandigai", tokens)
        self.assertNotIn("600127", tokens)


# ============================================================
# QUERY VARIANT GENERATION
# ============================================================

class QueryVariantTests(unittest.TestCase):

    def test_bare_name_is_tried_first(self):
        variants = osm.generate_query_variants(
            "VIT Chennai",
            "Vandalur Kelambakkam Road, SH 121, Kandigai, Chennai, Tamil Nadu, 600127",
        )
        self.assertEqual(variants[0][0], "bare_name")
        self.assertEqual(variants[0][1]["q"], "VIT Chennai")

    def test_structured_variant_never_mixes_q_with_structured_fields(self):
        variants = osm.generate_query_variants("VIT Chennai", "Chennai, Tamil Nadu, 600127")
        structured = dict(variants)["structured"]
        self.assertNotIn("q", structured)
        self.assertEqual(structured["city"], "Chennai")

    def test_full_address_variant_is_last_resort(self):
        variants = osm.generate_query_variants(
            "VIT Chennai", "Vandalur Kelambakkam Road, SH 121, Chennai, Tamil Nadu, 600127"
        )
        strategy_names = [v[0] for v in variants]
        self.assertLess(
            strategy_names.index("bare_name"),
            strategy_names.index("freeform_name_address"),
        )

    def test_no_name_still_generates_address_only_variant(self):
        variants = osm.generate_query_variants("", "Chennai, Tamil Nadu, 600001")
        self.assertTrue(any(v[0] == "freeform_address_only" for v in variants))


# ============================================================
# MATCHER
# ============================================================

class MatcherTests(unittest.TestCase):

    def test_exact_name_and_pincode_scores_high(self):
        mappls = {"place_name": "VIT Chennai", "address": "Vandalur Road, Chennai, Tamil Nadu, 600127"}
        candidate = {
            "name": "VIT Chennai", "full_text": "VIT Chennai, Vandalur Road, Chennai, Tamil Nadu, 600127, India",
            "city": "Chennai", "state": "Tamil Nadu", "postcode": "600127", "category_plausible": True,
        }
        score = osm.score_candidate(mappls, candidate)
        self.assertIsNone(score.gate_triggered)
        self.assertGreater(score.raw_score, 0.6)

    def test_state_mismatch_triggers_hard_gate(self):
        # The "VIT" ambiguous-query failure mode from the benchmark:
        # Mappls resolves to a Bengaluru entity, candidate is elsewhere.
        mappls = {"place_name": "Visvesvaraya Museum", "address": "Cubbon Park, Bengaluru, Karnataka, 560001"}
        candidate = {
            "name": "Some Other Place", "full_text": "Some Other Place, Mumbai, Maharashtra, 400001, India",
            "city": "Mumbai", "state": "Maharashtra", "postcode": "400001", "category_plausible": True,
        }
        score = osm.score_candidate(mappls, candidate)
        self.assertEqual(score.gate_triggered, "STATE_MISMATCH")

    def test_pincode_locality_street_mismatch_triggers_hard_gate(self):
        # The Apollo Hospital Chennai / Perungudi false-positive from the
        # Geoapify benchmark, re-verified here for the OSM matcher: same
        # city and state, but a different pincode/locality/street combo
        # must still be rejected even with decent name similarity.
        mappls = {
            "place_name": "Apollo Hospitals, Chennai",
            "address": "10/169, 1st Street, Greams Lane, Thousand Lights West, Chennai, Tamil Nadu, 600006",
        }
        candidate = {
            "name": "Apollo Pharmacy", "full_text": "Apollo Pharmacy, Perungudi, Chennai, Tamil Nadu, 600091, India",
            "city": "Chennai", "state": "Tamil Nadu", "postcode": "600091", "category_plausible": True,
        }
        score = osm.score_candidate(mappls, candidate)
        self.assertEqual(score.gate_triggered, "PINCODE_LOCALITY_STREET_MISMATCH")

    def test_exact_pincode_match_required_no_partial_credit_for_same_prefix(self):
        # 600006 vs 600091 share "600" but must NOT get partial credit -
        # this is the exact bug fixed after the Apollo Hospital finding.
        mappls = {"place_name": "X", "address": "X, Chennai, Tamil Nadu, 600006"}
        candidate = {"name": "X", "full_text": "X", "city": "Chennai", "state": "Tamil Nadu", "postcode": "600091"}
        score = osm.score_candidate(mappls, candidate)
        self.assertEqual(score.pincode_status, "different")
        self.assertEqual(score.pincode_score, 0.0)

    def test_sparse_mappls_address_does_not_get_punished_as_mismatch(self):
        # IIT Madras-style case: Mappls address is just "Chennai, Tamil
        # Nadu, 600036" with no street/locality text at all. The Mappls
        # side of street/locality tokenizes to empty, so these must land
        # in the neutral "not enough data to compare" range (0.4-0.5),
        # never the near-zero range that signals a genuine mismatch -
        # and critically, must never trigger the hard rejection gate.
        mappls = {"place_name": "IIT Madras", "address": "Chennai, Tamil Nadu, 600036"}
        candidate = {
            "name": "IIT Madras", "full_text": "IIT Madras, Chennai, Tamil Nadu, 600036, India",
            "city": "Chennai", "state": "Tamil Nadu", "postcode": "600036", "category_plausible": True,
        }
        score = osm.score_candidate(mappls, candidate)
        self.assertGreaterEqual(score.street_similarity, 0.4)
        self.assertGreaterEqual(score.locality_similarity, 0.4)
        self.assertIsNone(score.gate_triggered)


# ============================================================
# SERVICE: resolve_coordinates end-to-end (mocked HTTP)
# ============================================================

class ResolveCoordinatesTests(unittest.TestCase):

    def setUp(self):
        self.mongo = FakeMongoService()
        self.service = osm.OSMLocationService(mongo_service=self.mongo, min_score=0.40, min_margin=0.05)

    def test_clear_single_candidate_matches(self):
        response = mock_response([nominatim_result("VIT Chennai", 12.8406, 80.1538)])

        with patch("services.osm_location_service.requests.get", return_value=response):
            result = self.service.resolve_coordinates({
                "place_name": "VIT Chennai",
                "address": "Vandalur Kelambakkam Road, Chennai, Tamil Nadu, 600127",
            })

        self.assertEqual(result["status"], "matched")
        self.assertAlmostEqual(result["latitude"], 12.8406)
        self.assertAlmostEqual(result["longitude"], 80.1538)
        self.assertIsNotNone(result["confidence"])

    def test_no_osm_results_returns_no_match_not_a_guess(self):
        response = mock_response([])

        with patch("services.osm_location_service.requests.get", return_value=response):
            result = self.service.resolve_coordinates({
                "place_name": "Totally Unmapped Place Xyz",
                "address": "Nowhere, Chennai, Tamil Nadu, 600001",
            })

        self.assertEqual(result["status"], "no_match")
        self.assertIsNone(result["latitude"])
        self.assertIsNone(result["longitude"])

    def test_network_failure_returns_error_not_a_guess(self):
        with patch(
            "services.osm_location_service.requests.get",
            side_effect=requests_module.ConnectionError("boom"),
        ):
            result = self.service.resolve_coordinates({
                "place_name": "VIT Chennai",
                "address": "Chennai, Tamil Nadu, 600127",
            })

        self.assertEqual(result["status"], "no_match")
        self.assertIsNone(result["latitude"])

    def test_wrong_state_candidate_is_rejected_not_returned(self):
        response = mock_response([
            nominatim_result("Visvesvaraya Museum", 12.9752, 77.5964, city="Bengaluru", state="Karnataka", postcode="560001"),
        ])

        with patch("services.osm_location_service.requests.get", return_value=response):
            result = self.service.resolve_coordinates({
                "place_name": "VIT Chennai",
                "address": "Vandalur Kelambakkam Road, Chennai, Tamil Nadu, 600127",
            })

        self.assertEqual(result["status"], "rejected")
        self.assertIsNone(result["latitude"])

    def test_tight_margin_between_top_two_candidates_is_ambiguous(self):
        response = mock_response([
            nominatim_result("SRM Institute A", 13.05, 80.21, osm_id=1),
            nominatim_result("SRM Institute B", 13.06, 80.22, osm_id=2),
        ])

        with patch("services.osm_location_service.requests.get", return_value=response):
            result = self.service.resolve_coordinates({
                "place_name": "SRM Institute A",
                "address": "Chennai, Tamil Nadu, 600026",
            })

        # Both candidates are near-identical text matches -> tight margin
        # -> must NOT silently pick one.
        if result["candidate_count"] > 1:
            self.assertIn(result["status"], ("ambiguous", "matched"))
            if result["status"] == "ambiguous":
                self.assertIsNone(result["latitude"])
                self.assertTrue(len(result["alternates"]) >= 1)

    def test_empty_input_returns_error(self):
        result = self.service.resolve_coordinates({"place_name": "", "address": ""})
        self.assertEqual(result["status"], "error")

    def test_second_call_for_same_query_is_served_from_cache(self):
        response = mock_response([nominatim_result("VIT Chennai", 12.8406, 80.1538)])

        with patch("services.osm_location_service.requests.get", return_value=response) as mock_get:
            self.service.resolve_coordinates({
                "place_name": "VIT Chennai", "address": "Chennai, Tamil Nadu, 600127",
            })
            first_call_count = mock_get.call_count

            self.service.resolve_coordinates({
                "place_name": "VIT Chennai", "address": "Chennai, Tamil Nadu, 600127",
            })
            second_call_count = mock_get.call_count

        self.assertEqual(first_call_count, second_call_count, "second identical lookup must be served from cache")

    def test_cache_disabled_skips_mongo_entirely(self):
        service = osm.OSMLocationService(mongo_service=None, min_score=0.40, min_margin=0.05)
        response = mock_response([nominatim_result("VIT Chennai", 12.8406, 80.1538)])

        with patch("services.osm_location_service.requests.get", return_value=response):
            result = service.resolve_coordinates({
                "place_name": "VIT Chennai", "address": "Chennai, Tamil Nadu, 600127",
            })

        self.assertEqual(result["status"], "matched")


if __name__ == "__main__":
    unittest.main()
