"""
Integration tests for routes/search_routes.py's /search_rentals
(Phase 3: optional natural-language "query" field layered on top of
the existing structured search).

Exercises the REAL Flask blueprint/routing/session layer (a genuine
Flask test client, not a bypass), but with a minimal standalone app -
not the real app.py - so this suite has NO live dependency (no real
MongoDB, no real Mappls/OSM, no SQLAlchemy user model). PropertyService
and OSMLocationService are fakes; mappls_service.resolve_place is
patched. This matches the task's instruction: mock Mappls/OSM for
automated tests, and do not require a live MongoDB just to test route
wiring - the orchestration logic itself is already covered against
fakes in test_search_orchestration.py; this file's job is specifically
to prove the HTTP layer (backward compatibility, status codes, response
shape) is wired correctly.
"""

import unittest
from unittest.mock import patch

from flask import Flask
from flask_login import LoginManager, UserMixin

from routes.search_routes import search_bp


class StubUser(UserMixin):
    id = "1"


class FakePropertyService:

    def __init__(self):
        self.ranked_search_calls = []
        self.filtered_search_calls = []
        self.ranked_search_results = []
        self.filtered_search_results = []

    def ranked_search(self, preferences):
        self.ranked_search_calls.append(preferences)
        return self.ranked_search_results

    def filtered_search(self, mongo_filter):
        self.filtered_search_calls.append(mongo_filter)
        return self.filtered_search_results


class FakeOSMService:

    def __init__(self):
        self.next_result = None

    def resolve_coordinates(self, mappls_poi):
        return self.next_result


def sample_property(prop_id="p1", match_score=None):
    doc = {
        "_id": prop_id,
        "listing": {"type": "rent", "price": 25000, "status": "active"},
        "property": {"type": "apartment", "bhk": 2, "area_sqft": 900},
        "location": {"address": "Some Rd", "city": "Chennai", "locality": "Tambaram",
                     "coordinates": {"type": "Point", "coordinates": [80.2, 12.9]}},
        "description": {"text": "Nice flat"},
        "contact": {"name": "Owner", "phone": "9999999999"},
        "media": {"images": ["img1.jpg"]},
        "source": {"type": "owner", "url": None},
        "features": ["parking", "gym"],
    }
    if match_score is not None:
        doc["_match_score"] = match_score
    return doc


def make_test_app(property_service, osm_service, mappls_key="dummy-key"):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["MAPPLS_API_KEY"] = mappls_key
    app.testing = True

    app.extensions["property_service"] = property_service
    app.extensions["osm_location_service"] = osm_service

    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return StubUser()

    app.register_blueprint(search_bp)
    return app


def logged_in_client(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True
    return client


def mappls_matched():
    return {"status": "matched", "place_name": "IIT Madras", "place_address": "Chennai",
            "eloc": "ELOC1", "type": "poi", "error": None}


def mappls_no_match():
    return {"status": "no_match", "place_name": None, "place_address": None,
            "eloc": None, "type": None, "error": None}


def osm_matched(lat=12.99, lon=80.23):
    return {"status": "matched", "latitude": lat, "longitude": lon, "confidence": 0.8, "error": None}


def osm_status(status):
    return {"status": status, "latitude": None, "longitude": None, "confidence": 0.3, "error": "reason"}


# ============================================================
# BACKWARD COMPATIBILITY: no "query" field at all
# ============================================================

class BackwardCompatibilityTests(unittest.TestCase):

    def setUp(self):
        self.property_service = FakePropertyService()
        self.osm_service = FakeOSMService()
        self.app = make_test_app(self.property_service, self.osm_service)
        self.client = logged_in_client(self.app)

    def test_no_query_field_uses_ranked_search_exactly_as_before(self):
        self.property_service.ranked_search_results = [sample_property(match_score=42)]

        resp = self.client.post("/search_rentals", json={
            "budget": 30000, "city": "Chennai", "locality": "", "listing_type": "rent",
            "property_type": "apartment", "bhk": 2,
        })

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(len(self.property_service.ranked_search_calls), 1)
        self.assertEqual(self.property_service.filtered_search_calls, [])
        self.assertEqual(body["properties"][0]["match_score"], 42)
        # Old response shape has no Phase 3 keys.
        self.assertNotIn("parsed_query", body)
        self.assertNotIn("location_resolution", body)
        self.assertNotIn("applied_filters", body)

    def test_invalid_request_still_returns_400(self):
        resp = self.client.post("/search_rentals", data="not json",
                                 content_type="application/json")
        self.assertEqual(resp.status_code, 400)

    def test_negative_budget_still_rejected(self):
        resp = self.client.post("/search_rentals", json={"budget": -5})
        self.assertEqual(resp.status_code, 400)

    def test_empty_query_string_behaves_like_no_query(self):
        self.property_service.ranked_search_results = []
        resp = self.client.post("/search_rentals", json={"budget": 0, "query": "   "})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(self.property_service.ranked_search_calls), 1)
        self.assertEqual(self.property_service.filtered_search_calls, [])


# ============================================================
# NATURAL-LANGUAGE QUERY PATH
# ============================================================

class NaturalLanguageSearchTests(unittest.TestCase):

    def setUp(self):
        self.property_service = FakePropertyService()
        self.osm_service = FakeOSMService()
        self.app = make_test_app(self.property_service, self.osm_service)
        self.client = logged_in_client(self.app)

    def test_query_without_location_uses_filtered_search(self):
        self.property_service.filtered_search_results = [sample_property()]

        resp = self.client.post("/search_rentals", json={
            "budget": 0, "query": "2 BHK apartment for rent under 30000 with gym"
        })

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(len(self.property_service.filtered_search_calls), 1)
        self.assertEqual(self.property_service.ranked_search_calls, [])
        self.assertIsNone(body["location_resolution"])
        self.assertEqual(body["parsed_query"]["bedrooms"]["value"], 2.0)
        self.assertIn("gym", body["applied_filters"]["amenities"])
        mongo_filter = self.property_service.filtered_search_calls[0]
        self.assertEqual(mongo_filter["listing.price"], {"$lte": 30000.0})

    def test_area_or_city_query(self):
        self.property_service.filtered_search_results = []

        resp = self.client.post("/search_rentals", json={
            "budget": 0, "query": "2 BHK apartment for rent in Chennai"
        })

        self.assertEqual(resp.status_code, 200)
        mongo_filter = self.property_service.filtered_search_calls[0]
        self.assertIn("$and", mongo_filter)
        self.assertNotIn("location.coordinates", mongo_filter)

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_poi_matched_runs_geospatial_search(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_matched()
        self.osm_service.next_result = osm_matched()
        self.property_service.filtered_search_results = [sample_property()]

        resp = self.client.post("/search_rentals", json={
            "budget": 0, "query": "apartments near IIT Madras"
        })

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["location_resolution"]["status"], "matched")
        self.assertEqual(len(body["properties"]), 1)
        mongo_filter = self.property_service.filtered_search_calls[0]
        self.assertIn("$near", mongo_filter["location.coordinates"])

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_poi_ambiguous_returns_empty_with_explicit_status(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_matched()
        self.osm_service.next_result = osm_status("ambiguous")
        self.property_service.filtered_search_results = [sample_property()]  # must NOT be returned

        resp = self.client.post("/search_rentals", json={
            "budget": 0, "query": "2 BHK flats around Apollo Hospital Chennai"
        })

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["location_resolution"]["status"], "ambiguous")
        self.assertEqual(body["properties"], [])
        self.assertEqual(self.property_service.filtered_search_calls, [])

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_poi_no_match_returns_empty_with_explicit_status(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_no_match()

        resp = self.client.post("/search_rentals", json={
            "budget": 0, "query": "houses near Nonexistent Place Xyz"
        })

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["location_resolution"]["status"], "no_match")
        self.assertEqual(body["properties"], [])

    def test_malformed_unsupported_query_returns_200_not_error(self):
        resp = self.client.post("/search_rentals", json={
            "budget": 0, "query": "what's the weather today"
        })
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["parsed_query"]["intent"], "unknown")
        self.assertEqual(body["properties"], [])

    def test_explicit_structured_field_wins_over_query(self):
        self.property_service.filtered_search_results = []

        resp = self.client.post("/search_rentals", json={
            "budget": 0, "listing_type": "sell", "query": "2 bhk flat for rent"
        })

        self.assertEqual(resp.status_code, 200)
        mongo_filter = self.property_service.filtered_search_calls[0]
        self.assertEqual(mongo_filter["listing.type"], "sell")  # explicit override, not "rent" from the query

    def test_response_never_exposes_mappls_api_key(self):
        self.property_service.filtered_search_results = []
        resp = self.client.post("/search_rentals", json={
            "budget": 0, "query": "2 bhk flat for rent"
        })
        body_text = resp.get_data(as_text=True)
        self.assertNotIn("dummy-key", body_text)

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_ambiguous_response_includes_alternates_for_a_picker(self, mock_resolve_place):
        mock_resolve_place.return_value = mappls_matched()
        self.osm_service.next_result = {
            **osm_status("ambiguous"),
            "alternates": [
                {"matched_name": "VIT Chennai Administrative Block", "matched_address": "...",
                 "latitude": 12.8406, "longitude": 80.1539, "score": 0.4866},
                {"matched_name": "VIT Academic Block 1", "matched_address": "...",
                 "latitude": 12.8436, "longitude": 80.1534, "score": 0.4647},
            ],
        }

        resp = self.client.post("/search_rentals", json={
            "budget": 0, "query": "flat near VIT Chennai"
        })

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["location_resolution"]["status"], "ambiguous")
        self.assertEqual(len(body["location_resolution"]["alternates"]), 2)
        self.assertEqual(
            body["location_resolution"]["alternates"][0]["matched_name"],
            "VIT Chennai Administrative Block",
        )


class ExplicitCoordinatesTests(unittest.TestCase):
    """Covers "pick one of these" follow-up searches: the frontend
    already knows exactly which place the user meant (from a previous
    ambiguous result's alternates) and sends coordinates directly,
    bypassing Mappls/OSM entirely for this request."""

    def setUp(self):
        self.property_service = FakePropertyService()
        self.osm_service = FakeOSMService()
        self.app = make_test_app(self.property_service, self.osm_service)
        self.client = logged_in_client(self.app)

    @patch("services.search_orchestration.mappls_service.resolve_place")
    def test_explicit_coordinates_skip_poi_resolution(self, mock_resolve_place):
        self.property_service.filtered_search_results = [sample_property()]

        resp = self.client.post("/search_rentals", json={
            "budget": 0, "query": "flat near VIT Chennai",
            "location_lat": 12.8406, "location_lon": 80.1539,
        })

        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        mock_resolve_place.assert_not_called()
        self.assertEqual(body["location_resolution"]["status"], "matched")
        self.assertEqual(body["location_resolution"]["latitude"], 12.8406)
        self.assertEqual(len(body["properties"]), 1)
        mongo_filter = self.property_service.filtered_search_calls[0]
        self.assertEqual(
            mongo_filter["location.coordinates"]["$near"]["$geometry"]["coordinates"],
            [80.1539, 12.8406],
        )

    def test_malformed_coordinates_rejected_with_400(self):
        resp = self.client.post("/search_rentals", json={
            "budget": 0, "query": "flat near VIT Chennai",
            "location_lat": "not-a-number", "location_lon": 80.1539,
        })
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.property_service.filtered_search_calls, [])

    def test_out_of_range_coordinates_rejected_with_400(self):
        resp = self.client.post("/search_rentals", json={
            "budget": 0, "query": "flat near VIT Chennai",
            "location_lat": 999, "location_lon": 80.1539,
        })
        self.assertEqual(resp.status_code, 400)

    def test_lone_latitude_without_longitude_rejected_with_400(self):
        resp = self.client.post("/search_rentals", json={
            "budget": 0, "query": "flat near VIT Chennai",
            "location_lat": 12.8406,
        })
        self.assertEqual(resp.status_code, 400)

    def test_no_coordinates_falls_back_to_normal_poi_resolution(self):
        # Absence of location_lat/location_lon must not change anything
        # about the existing flow - a request with neither key behaves
        # exactly as it did before this feature existed.
        self.property_service.filtered_search_results = []

        resp = self.client.post("/search_rentals", json={
            "budget": 0, "query": "2 bhk apartment for rent"
        })

        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(resp.get_json()["location_resolution"])


if __name__ == "__main__":
    unittest.main()
