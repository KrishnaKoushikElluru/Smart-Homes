"""
Integration tests for routes/comparison_routes.py.

Exercises the REAL Flask blueprint/routing/session layer against a
minimal standalone app (matching test_design_routes.py's established
convention), never the real app.py (which needs a live MongoDB
connection). Square Yards detail retrieval is always mocked here - no
test in this file makes a real MCP/network call.
"""

import unittest
from unittest.mock import patch

from flask import Blueprint, Flask
from flask_login import LoginManager, UserMixin

from routes.comparison_routes import comparison_bp


class StubUser(UserMixin):
    id = "1"


class FakePropertyService:
    """Minimal PropertyService.get_property() stand-in - no real
    MongoDB. `documents` maps property_id -> a raw document dict (or
    omits it, to simulate a not-found/deleted property)."""

    def __init__(self, documents=None):
        self.documents = documents or {}

    def get_property(self, property_id):
        return self.documents.get(property_id)


def make_property_doc(**overrides):
    doc = {
        "listing": {"type": "rent", "status": "active", "price": 25000, "title": "Test Property"},
        "property": {"type": "apartment", "bhk": "2", "area_sqft": 1100, "furnishing": "semi_furnished"},
        "location": {"city": "Chennai", "locality": "Velachery"},
        "features": ["lift", "power_backup"],
        "media": {"images": []},
        "rental": {},
        "sale": {},
        "building": {},
        "parking": {},
        "rooms": {},
        "area": {},
        "project": {},
        "type_details": {},
        "legal": {},
        "pg_details": {},
    }
    doc.update(overrides)
    return doc


def make_square_yards_listing(**overrides):
    normalized = {
        "source": "squareyards",
        "external_id": "SY999",
        "title": "Test External Listing",
        "listing_type": "rent",
        "price": 30000,
        "price_on_request": False,
        "bhk": "2",
        "area_sqft": 1200,
        "property_type": "Apartment",
        "furnishing": "unfurnished",
        "amenities": ["Gym"],
        "locality": "OMR",
        "city": "Chennai",
        "images": [],
        "source_url": "https://www.squareyards.com/listing/SY999",
    }
    normalized.update(overrides)
    return normalized


def make_test_app(property_service=None):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["SQUARE_YARDS_ENABLED"] = True
    app.testing = True

    app.extensions["property_service"] = property_service or FakePropertyService()

    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return StubUser()

    app.register_blueprint(comparison_bp)

    @app.route("/")
    def home():
        return "home"

    stub_property_bp = Blueprint("property", __name__)

    @stub_property_bp.route("/rentals")
    def rentals():
        return "rentals"

    app.register_blueprint(stub_property_bp)

    stub_design_bp = Blueprint("design", __name__)

    @stub_design_bp.route("/design")
    def design():
        return "design"

    app.register_blueprint(stub_design_bp)

    return app


def logged_in_client(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True
    return client


# ============================================================
# 1. VALID SMARTHOMES COMPARISON
# ============================================================

class ValidSmartHomesComparisonTests(unittest.TestCase):

    def test_two_smarthomes_properties_compare_successfully(self):
        service = FakePropertyService({
            "p1": make_property_doc(),
            "p2": make_property_doc(
                listing={"type": "rent", "status": "active", "price": 35000, "title": "Pricier"}
            ),
        })
        app = make_test_app(property_service=service)
        client = logged_in_client(app)

        response = client.get("/api/compare?items=smarthomes:p1,smarthomes:p2")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["properties"]), 2)
        self.assertEqual(data["failed"], [])
        for prop in data["properties"]:
            self.assertEqual(prop["provider"], "smarthomes")
            self.assertIn("ratings", prop)


# ============================================================
# 2. VALID SQUARE YARDS COMPARISON
# ============================================================

class ValidSquareYardsComparisonTests(unittest.TestCase):

    def test_two_square_yards_listings_compare_successfully(self):
        app = make_test_app()
        client = logged_in_client(app)

        with patch(
            "routes.comparison_routes.square_yards_service.get_listing_details"
        ) as mock_get_details:
            mock_get_details.side_effect = [
                make_square_yards_listing(external_id="SY1"),
                make_square_yards_listing(external_id="SY2", price=40000),
            ]

            response = client.get("/api/compare?items=squareyards:SY1,squareyards:SY2")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["properties"]), 2)
        for prop in data["properties"]:
            self.assertEqual(prop["provider"], "squareyards")
            self.assertEqual(prop["ratings"]["categories"]["availability"]["status"], "unavailable")


# ============================================================
# 3. MIXED SMARTHOMES + SQUARE YARDS COMPARISON
# ============================================================

class MixedComparisonTests(unittest.TestCase):

    def test_mixed_sources_compare_successfully(self):
        service = FakePropertyService({"p1": make_property_doc()})
        app = make_test_app(property_service=service)
        client = logged_in_client(app)

        with patch(
            "routes.comparison_routes.square_yards_service.get_listing_details"
        ) as mock_get_details:
            mock_get_details.return_value = make_square_yards_listing()

            response = client.get("/api/compare?items=smarthomes:p1,squareyards:SY999")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        providers = {prop["provider"] for prop in data["properties"]}
        self.assertEqual(providers, {"smarthomes", "squareyards"})


# ============================================================
# 4. INVALID PROPERTY ID
# ============================================================

class InvalidPropertyIdTests(unittest.TestCase):

    def test_malformed_mongo_id_is_treated_as_not_found(self):
        service = FakePropertyService({"p1": make_property_doc()})
        app = make_test_app(property_service=service)
        client = logged_in_client(app)

        response = client.get("/api/compare?items=smarthomes:not-a-real-id,smarthomes:p1")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["failed"]), 1)
        self.assertEqual(data["failed"][0]["id"], "not-a-real-id")
        self.assertEqual(len(data["properties"]), 1)


# ============================================================
# 5. MISSING PROPERTY
# ============================================================

class MissingPropertyTests(unittest.TestCase):

    def test_not_found_property_is_reported_not_crashed(self):
        service = FakePropertyService({"p1": make_property_doc()})
        app = make_test_app(property_service=service)
        client = logged_in_client(app)

        response = client.get("/api/compare?items=smarthomes:p1,smarthomes:does-not-exist")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["properties"]), 1)
        self.assertEqual(len(data["failed"]), 1)
        self.assertEqual(data["failed"][0]["reason"], "Property not found.")


# ============================================================
# 6. MALFORMED PROVIDER/ID
# ============================================================

class MalformedRequestTests(unittest.TestCase):

    def test_unknown_provider_is_rejected(self):
        app = make_test_app()
        client = logged_in_client(app)

        response = client.get("/api/compare?items=unknownprovider:x,smarthomes:p1")

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_missing_items_param_is_rejected(self):
        app = make_test_app()
        client = logged_in_client(app)

        response = client.get("/api/compare")

        self.assertEqual(response.status_code, 400)

    def test_entry_with_no_colon_is_rejected(self):
        app = make_test_app()
        client = logged_in_client(app)

        response = client.get("/api/compare?items=smarthomesp1,smarthomes:p2")

        self.assertEqual(response.status_code, 400)

    def test_too_few_items_is_rejected(self):
        app = make_test_app()
        client = logged_in_client(app)

        response = client.get("/api/compare?items=smarthomes:p1")

        self.assertEqual(response.status_code, 400)

    def test_too_many_items_is_rejected(self):
        app = make_test_app()
        client = logged_in_client(app)

        response = client.get(
            "/api/compare?items=smarthomes:p1,smarthomes:p2,smarthomes:p3,smarthomes:p4,smarthomes:p5"
        )

        self.assertEqual(response.status_code, 400)


# ============================================================
# 7. DUPLICATE SELECTION
# ============================================================

class DuplicateSelectionTests(unittest.TestCase):

    def test_duplicate_provider_id_pair_is_rejected(self):
        app = make_test_app()
        client = logged_in_client(app)

        response = client.get("/api/compare?items=smarthomes:p1,smarthomes:p1")

        self.assertEqual(response.status_code, 400)
        self.assertIn("Duplicate", response.get_json()["error"])


# ============================================================
# 8. SQUARE YARDS DETAIL RETRIEVAL FAILURE
# ============================================================

class SquareYardsFailureTests(unittest.TestCase):

    def test_square_yards_failure_does_not_crash_the_comparison(self):
        service = FakePropertyService({"p1": make_property_doc()})
        app = make_test_app(property_service=service)
        client = logged_in_client(app)

        with patch(
            "routes.comparison_routes.square_yards_service.get_listing_details"
        ) as mock_get_details:
            mock_get_details.return_value = None  # matches the real function's "never raises" contract

            response = client.get("/api/compare?items=smarthomes:p1,squareyards:SY999")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["properties"]), 1)
        self.assertEqual(data["properties"][0]["provider"], "smarthomes")
        self.assertEqual(len(data["failed"]), 1)
        self.assertEqual(data["failed"][0]["provider"], "squareyards")

    def test_square_yards_raising_an_exception_is_caught(self):
        service = FakePropertyService({"p1": make_property_doc()})
        app = make_test_app(property_service=service)
        client = logged_in_client(app)

        with patch(
            "routes.comparison_routes.square_yards_service.get_listing_details"
        ) as mock_get_details:
            mock_get_details.side_effect = RuntimeError("MCP exploded")

            response = client.get("/api/compare?items=smarthomes:p1,squareyards:SY999")

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertEqual(len(data["failed"]), 1)


# ============================================================
# 9. MISSING CATEGORY DATA
# ============================================================

class MissingCategoryDataTests(unittest.TestCase):

    def test_response_marks_unavailable_categories_explicitly(self):
        app = make_test_app()
        client = logged_in_client(app)

        with patch(
            "routes.comparison_routes.square_yards_service.get_listing_details"
        ) as mock_get_details:
            mock_get_details.side_effect = [
                make_square_yards_listing(external_id="SY1"),
                make_square_yards_listing(external_id="SY2"),
            ]
            response = client.get("/api/compare?items=squareyards:SY1,squareyards:SY2")

        data = response.get_json()
        categories = data["properties"][0]["ratings"]["categories"]
        self.assertEqual(categories["availability"]["status"], "unavailable")
        self.assertIsNone(categories["availability"]["score"])
        self.assertEqual(categories["connectivity"]["status"], "unavailable")
        self.assertEqual(categories["property_features"]["status"], "unavailable")


# ============================================================
# 10. RESPONSE STRUCTURE
# ============================================================

class ResponseStructureTests(unittest.TestCase):

    def test_response_has_expected_top_level_keys(self):
        service = FakePropertyService({
            "p1": make_property_doc(),
            "p2": make_property_doc(),
        })
        app = make_test_app(property_service=service)
        client = logged_in_client(app)

        response = client.get("/api/compare?items=smarthomes:p1,smarthomes:p2")
        data = response.get_json()

        self.assertIn("properties", data)
        self.assertIn("failed", data)

        prop = data["properties"][0]
        for key in ("provider", "id", "title", "price", "ratings"):
            self.assertIn(key, prop)

        ratings = prop["ratings"]
        self.assertIn("categories", ratings)
        self.assertIn("overall", ratings)
        for category_key in (
            "price_value", "location", "facilities",
            "availability", "connectivity", "property_features",
        ):
            self.assertIn(category_key, ratings["categories"])
            category = ratings["categories"][category_key]
            self.assertIn("status", category)
            self.assertIn("score", category)
            self.assertIn("reason", category)
            self.assertIn("weight", category)
            self.assertIn("label", category)

    def test_compare_page_renders(self):
        app = make_test_app()
        client = logged_in_client(app)

        response = client.get("/compare")

        self.assertEqual(response.status_code, 200)

    def test_requires_login(self):
        app = make_test_app()
        client = app.test_client()

        response = client.get("/api/compare?items=smarthomes:p1,smarthomes:p2")

        # This minimal test app has no login_view configured (no real
        # auth blueprint registered), so Flask-Login's @login_required
        # returns a bare 401 for an unauthenticated request rather than
        # a redirect - the real app.py DOES set login_view (see
        # extensions.py), where this would be a 302 to the login page
        # instead. Either way, the request is rejected before reaching
        # the comparison logic - that's what this test verifies.
        self.assertEqual(response.status_code, 401)


if __name__ == "__main__":
    unittest.main()
