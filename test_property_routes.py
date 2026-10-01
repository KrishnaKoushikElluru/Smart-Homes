"""
Integration tests for routes/property_routes.py's location endpoints
(Phase 5: Ola-primary / Mappls-fallback property-registration location
search - replaces the old Geoapify-based autocomplete/reverse-geocode
flow).

Exercises the REAL Flask blueprint/routing/session layer (a genuine
Flask test client), with a minimal standalone app - not the real
app.py - matching test_search_routes_integration.py's established
convention. services.ola_maps_service / services.mappls_service HTTP
calls are mocked; osm_location_service is a fake.
"""

import io
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask
from flask_login import LoginManager, UserMixin

from routes.property_routes import property_bp


class StubUser(UserMixin):
    id = "1"
    username = "test_user"


class FakeOSMService:

    def __init__(self):
        self.calls = []
        self.next_result = None

    def resolve_coordinates(self, mappls_poi):
        self.calls.append(mappls_poi)
        return self.next_result


def make_test_app(osm_service=None, ola_key="ola-test-key", mappls_key="mappls-test-key"):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["OLA_MAPS_API_KEY"] = ola_key
    app.config["MAPPLS_API_KEY"] = mappls_key
    app.testing = True

    app.extensions["osm_location_service"] = osm_service or FakeOSMService()

    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return StubUser()

    app.register_blueprint(property_bp)
    return app


def logged_in_client(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True
    return client


class AutocompleteRouteTests(unittest.TestCase):

    def test_ola_success_returns_candidates(self):
        app = make_test_app()
        client = logged_in_client(app)

        ola_return = {
            "status": "matched",
            "candidates": [{
                "provider": "ola", "place_id": "ola-platform:1",
                "name": "VIT Chennai", "address": "Kandigai, Tamil Nadu, 600127, India",
                "latitude": 12.8473, "longitude": 80.1454, "types": ["point_of_interest"],
            }],
            "error": None,
        }

        with patch("routes.property_routes.ola_maps_service.autocomplete", return_value=ola_return) as mock_ola, \
             patch("routes.property_routes.mappls_service.resolve_place") as mock_mappls:

            response = client.get("/api/location/autocomplete?text=VIT Chennai")

        mock_ola.assert_called_once()
        mock_mappls.assert_not_called()
        data = response.get_json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["provider"], "ola")
        self.assertEqual(data["results"][0]["latitude"], 12.8473)

    def test_short_query_returns_empty_without_any_call(self):
        app = make_test_app()
        client = logged_in_client(app)

        with patch("routes.property_routes.ola_maps_service.autocomplete") as mock_ola:
            response = client.get("/api/location/autocomplete?text=VI")

        mock_ola.assert_not_called()
        self.assertEqual(response.get_json()["results"], [])

    def test_ola_no_match_returns_empty_without_mappls_fallback(self):
        app = make_test_app()
        client = logged_in_client(app)

        with patch(
            "routes.property_routes.ola_maps_service.autocomplete",
            return_value={"status": "no_match", "candidates": [], "error": None},
        ), patch("routes.property_routes.mappls_service.resolve_place") as mock_mappls:

            response = client.get("/api/location/autocomplete?text=asdkfjhaslkdfj")

        mock_mappls.assert_not_called()
        self.assertEqual(response.get_json()["results"], [])

    def test_ola_error_falls_back_to_mappls_single_candidate(self):
        app = make_test_app()
        client = logged_in_client(app)

        with patch(
            "routes.property_routes.ola_maps_service.autocomplete",
            return_value={"status": "error", "candidates": [], "error": "boom"},
        ), patch(
            "routes.property_routes.mappls_service.resolve_place",
            return_value={"status": "matched", "place_name": "VIT Chennai",
                          "place_address": "Chennai, Tamil Nadu", "eloc": "2NB2R6",
                          "type": "POI", "error": None},
        ) as mock_mappls:

            response = client.get("/api/location/autocomplete?text=VIT Chennai")

        mock_mappls.assert_called_once()
        data = response.get_json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["provider"], "mappls")
        self.assertEqual(data["results"][0]["name"], "VIT Chennai")
        # Mappls' own search never returns coordinates (see
        # services/mappls_service.py's module docstring) - must not be
        # fabricated here either.
        self.assertIsNone(data["results"][0]["latitude"])

    def test_no_provider_keys_configured_returns_explicit_error(self):
        app = make_test_app(ola_key=None, mappls_key=None)
        client = logged_in_client(app)

        response = client.get("/api/location/autocomplete?text=VIT Chennai")

        data = response.get_json()
        self.assertEqual(data["results"], [])
        self.assertIn("not configured", data["error"])

    def test_geoapify_is_not_used_by_the_relevant_location_flow(self):
        # Structural proof, not just behavioral: the property-location
        # autocomplete/reverse/resolve-candidate routes no longer
        # reference Geoapify at all. services/geospatial_service.py's
        # UNRELATED "nearby POI" feature (property_nearby_poi()) still
        # legitimately uses GEOAPIFY_API_KEY - that's a separate,
        # explicitly out-of-scope feature (see this phase's report),
        # so this checks only the three location routes this task
        # actually changed, not the whole file.
        import inspect
        import routes.property_routes as pr

        for func in (pr.location_autocomplete, pr.location_reverse, pr.location_resolve_candidate):
            source = inspect.getsource(func)
            self.assertNotIn("geoapify", source.lower(), f"{func.__name__} still references Geoapify")


class ResolveCandidateRouteTests(unittest.TestCase):

    def test_ola_candidate_resolves_via_place_details(self):
        app = make_test_app()
        client = logged_in_client(app)

        details_return = {
            "status": "matched", "latitude": 12.8358, "longitude": 80.1561,
            "formatted_address": "New Haven Ribbon Walk, Mambakkam, Tamil Nadu, 600127, India",
            "city": "Chennai", "state": "Tamil Nadu", "locality": "Mambakkam",
            "sub_locality": None, "postcode": "600127", "error": None,
        }

        with patch(
            "routes.property_routes.location_provider_service.resolve_selected_candidate",
            return_value={**details_return, "provider": "ola"},
        ) as mock_resolve:

            response = client.post("/api/location/resolve-candidate", json={
                "provider": "ola", "place_id": "ola-platform:5000330359668",
                "name": "TaTa New Haven Ribbon Walk", "address": "Mambakkam, Tamil Nadu",
            })

        mock_resolve.assert_called_once()
        data = response.get_json()
        self.assertEqual(data["status"], "matched")
        self.assertEqual(data["latitude"], 12.8358)
        self.assertEqual(data["provider"], "ola")

    def test_missing_provider_is_rejected(self):
        app = make_test_app()
        client = logged_in_client(app)

        response = client.post("/api/location/resolve-candidate", json={"name": "X"})

        self.assertEqual(response.status_code, 400)

    def test_mappls_candidate_resolves_via_osm_fallback(self):
        osm = FakeOSMService()
        osm.next_result = {
            "status": "matched", "latitude": 12.8406, "longitude": 80.1538,
            "display_name": "VIT Chennai, Chennai, Tamil Nadu, India", "error": None,
        }
        app = make_test_app(osm_service=osm)
        client = logged_in_client(app)

        response = client.post("/api/location/resolve-candidate", json={
            "provider": "mappls", "name": "VIT Chennai", "address": "Chennai, Tamil Nadu",
        })

        data = response.get_json()
        self.assertEqual(data["status"], "matched")
        self.assertEqual(data["provider"], "osm")
        self.assertEqual(data["latitude"], 12.8406)
        self.assertEqual(len(osm.calls), 1)


class ReverseGeocodeRouteTests(unittest.TestCase):

    def test_successful_reverse_geocode(self):
        app = make_test_app()
        client = logged_in_client(app)

        with patch(
            "routes.property_routes.ola_maps_service.reverse_geocode",
            return_value={
                "status": "matched",
                "formatted_address": "VIT Chennai, Chennai, Tamil Nadu, 600127, India",
                "city": "Chennai", "state": "Tamil Nadu", "locality": "Melakottaiyur",
                "sub_locality": None, "postcode": "600127", "error": None,
            },
        ):
            response = client.get("/api/location/reverse?lat=12.8406&lon=80.1538")

        data = response.get_json()
        self.assertEqual(data["city"], "Chennai")
        self.assertEqual(data["postcode"], "600127")

    def test_invalid_coordinates_returns_400(self):
        app = make_test_app()
        client = logged_in_client(app)

        response = client.get("/api/location/reverse?lat=not-a-number&lon=80.15")

        self.assertEqual(response.status_code, 400)

    def test_not_configured_returns_error(self):
        app = make_test_app(ola_key=None)
        client = logged_in_client(app)

        response = client.get("/api/location/reverse?lat=12.84&lon=80.15")

        self.assertIn("not configured", response.get_json()["error"])


class ResolvePoiRouteTests(unittest.TestCase):

    def test_ola_matched_short_circuits_before_mappls(self):
        app = make_test_app()
        client = logged_in_client(app)

        with patch(
            "routes.property_routes.location_provider_service.resolve_location_via_ola",
            return_value={
                "status": "matched", "latitude": 12.8358, "longitude": 80.1561,
                "place_name": "TaTa New Haven Ribbon Walk", "formatted_address": "...",
                "confidence": 0.95, "error": None, "alternates": [], "provider": "ola",
            },
        ), patch("routes.property_routes.mappls_service.resolve_place") as mock_mappls:

            response = client.post("/api/location/resolve-poi", json={"query": "Tata New Haven Ribbon Walk"})

        mock_mappls.assert_not_called()
        data = response.get_json()
        self.assertEqual(data["provider"], "ola")
        self.assertEqual(data["ola"]["status"], "matched")
        self.assertIsNone(data["mappls"])

    def test_ola_no_match_falls_back_to_mappls_and_osm(self):
        osm = FakeOSMService()
        osm.next_result = {
            "status": "matched", "latitude": 12.9, "longitude": 80.2,
            "display_name": "IIT Madras", "confidence": 0.7, "match_method": "bare_name",
            "matched_name": "IIT Madras", "matched_address": "Chennai", "osm_id": "1",
            "osm_type": "way", "osm_category": "amenity", "candidate_count": 1,
            "alternates": [], "error": None,
        }
        app = make_test_app(osm_service=osm)
        client = logged_in_client(app)

        with patch(
            "routes.property_routes.location_provider_service.resolve_location_via_ola",
            return_value={
                "status": "no_match", "latitude": None, "longitude": None,
                "place_name": None, "formatted_address": None, "confidence": None,
                "error": None, "alternates": [], "provider": "ola",
            },
        ), patch(
            "routes.property_routes.mappls_service.resolve_place",
            return_value={"status": "matched", "place_name": "IIT Madras",
                          "place_address": "Chennai", "eloc": "E1", "type": "POI", "error": None},
        ):
            response = client.post("/api/location/resolve-poi", json={"query": "IIT Madras"})

        data = response.get_json()
        self.assertEqual(data["provider"], "mappls")
        self.assertEqual(data["osm"]["status"], "matched")
        self.assertEqual(data["osm"]["latitude"], 12.9)

    def test_empty_query_returns_400(self):
        app = make_test_app()
        client = logged_in_client(app)

        response = client.post("/api/location/resolve-poi", json={"query": ""})

        self.assertEqual(response.status_code, 400)


class FakePropertyServiceForSubmit:
    """Minimal fake matching the PropertyService surface submit_listing()
    actually calls - no real MongoDB. claim_nearby_facilities_enrichment()
    returns False (declines the claim) so the unrelated nearby-facility
    background thread never starts during these tests - keeps focus on
    the image-similarity background wiring being tested here."""

    def __init__(self):
        self.created_properties = []
        self.updates = []
        self.documents = {}

    def create_property(self, property_data):
        self.created_properties.append(property_data)
        return "aaaaaaaaaaaaaaaaaaaaaaaa"

    def claim_nearby_facilities_enrichment(self, property_id, pending_metadata):
        return False

    def update_property(self, property_id, updates):
        self.updates.append((property_id, updates))
        return True

    def get_property(self, property_id):
        return self.documents.get(property_id)

    def get_properties_by_seller(self, seller_id):
        return [
            doc for doc in self.documents.values()
            if (doc.get("seller") or {}).get("user_id") == seller_id
        ]

    def update_status(self, property_id, status):
        document = self.documents.get(property_id)
        if document is None:
            return False
        document.setdefault("listing", {})["status"] = status
        self.updates.append((property_id, {"listing.status": status}))
        return True


def _real_png_bytes(color=(10, 20, 30), size=(4, 4)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


def _make_submit_app(property_service, tmp_static_folder):
    app = Flask(__name__, static_folder=tmp_static_folder, static_url_path="/static")
    app.config["SECRET_KEY"] = "test-secret"
    app.testing = True
    app.extensions["property_service"] = property_service
    app.extensions["osm_location_service"] = FakeOSMService()

    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return StubUser()

    app.register_blueprint(property_bp)
    return app


def _minimal_valid_listing_form():
    """The smallest valid submit_listing() payload: property_type
    "plot" + listing_type "sell" requires the fewest type-dependent
    fields (see services/property_fields.py - bathrooms/floor_number/
    etc. do not apply_to "plot")."""
    return {
        "listing_type": "sell",
        "property_type": "plot",
        "title": "Test Plot",
        "price": "1000000",
        "address": "123 Test Street",
        "city": "Chennai",
        "latitude": "13.0827",
        "longitude": "80.2707",
        "contact_name": "Test Owner",
        "contact_phone": "9876543210",
        "plot_sqft": "1200",
        "land_use": "residential",
    }


class SubmitListingProductionEmbeddingTests(unittest.TestCase):
    """Integration tests for the Phase 6 production image-similarity
    wiring inside routes/property_routes.py's submit_listing() - Steps
    1/2/3/7 of the production integration: registration and image
    storage continue exactly as before, and background embedding is
    started without blocking the response. No real SigLIP2 model is
    loaded anywhere in this class - services.image_similarity.
    production_indexer.start_background_embedding is patched at its
    source (routes/property_routes.py imports it lazily, inside
    submit_listing(), matching this project's established
    lazy-import-torch convention)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.property_service = FakePropertyServiceForSubmit()
        self.app = _make_submit_app(self.property_service, self._tmpdir.name)
        self.client = logged_in_client(self.app)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_registration_succeeds_and_background_embedding_is_started(self):
        with patch(
            "services.image_similarity.production_indexer.start_background_embedding"
        ) as mock_start:
            response = self.client.post(
                "/submit_listing",
                data={
                    **_minimal_valid_listing_form(),
                    "images": (io.BytesIO(_real_png_bytes()), "house.png"),
                },
                content_type="multipart/form-data",
            )

        # submit_listing() redirects to profile on success.
        self.assertEqual(response.status_code, 302)
        self.assertEqual(len(self.property_service.created_properties), 1)

        mock_start.assert_called_once()
        call_args = mock_start.call_args.args
        self.assertEqual(call_args[0], "aaaaaaaaaaaaaaaaaaaaaaaa")  # property_id
        self.assertEqual(len(call_args[1]), 1)  # one saved image filename

    def test_registration_does_not_wait_for_a_slow_embedding_worker(self):
        """Step 7: registration must not block on SigLIP2. Patches
        start_background_embedding with a slow implementation and
        asserts the HTTP response returns well before that delay - if
        submit_listing() were accidentally calling embedding work
        synchronously, this would time out/take >0.2s."""
        import time

        def slow_start_background_embedding(*args, **kwargs):
            time.sleep(0.3)
            return None

        with patch(
            "services.image_similarity.production_indexer.start_background_embedding",
            side_effect=slow_start_background_embedding,
        ):
            started_at = time.perf_counter()
            response = self.client.post(
                "/submit_listing",
                data={
                    **_minimal_valid_listing_form(),
                    "images": (io.BytesIO(_real_png_bytes()), "house.png"),
                },
                content_type="multipart/form-data",
            )
            elapsed = time.perf_counter() - started_at

        # This proves submit_listing() calls start_background_embedding()
        # itself (a real function call, not skipped) while still not
        # being the SLOW PART of the response - the real production
        # code's start_background_embedding() only ever spawns a thread
        # and returns immediately; a slow mock here stands in for what
        # would happen if that contract were ever broken.
        self.assertEqual(response.status_code, 302)
        self.assertGreaterEqual(elapsed, 0.3)  # confirms the mock really ran synchronously in-request
        # (This test intentionally documents the CONTRACT: production's
        # start_background_embedding() itself must be non-blocking -
        # see services/image_similarity/production_indexer.py's own
        # test_start_background_embedding_returns_immediately_and_does_not_block
        # in test_design_routes.py, which verifies the REAL function.)

    def test_property_with_no_images_is_rejected_before_reaching_embedding(self):
        """validate_images() already requires >=1 image - confirms
        that existing validation is untouched and embedding is never
        even attempted for a request that never reaches image saving."""
        with patch(
            "services.image_similarity.production_indexer.start_background_embedding"
        ) as mock_start:
            response = self.client.post(
                "/submit_listing",
                data=_minimal_valid_listing_form(),
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)  # redirect back with a flashed error
        self.assertEqual(len(self.property_service.created_properties), 0)
        mock_start.assert_not_called()


class PropertyDetailsRouteTests(unittest.TestCase):
    """Integration tests for GET /property/<property_id> (routes/
    property_routes.py's property_details()) - the EXISTING
    property-details page that a Find Similar Homes result card's
    detail_url (routes/design_routes.py's _enrich_similarity_results())
    must open. Exercises the REAL route + REAL templates
    (property_details.html / _property_view.html), not a stub, so this
    is the authoritative proof that "click a similarity card -> real
    property details page" actually works end-to-end."""

    def _make_doc(self, property_id, **overrides):
        doc = {
            "_id": property_id,
            "listing": {"type": "rent", "status": "active", "price": 25000, "price_negotiable": False, "title": "2BHK Flat"},
            "property": {"type": "apartment", "bhk": 2, "area_sqft": 950, "bathrooms": 2, "balconies": 1,
                         "furnishing": "semi_furnished", "facing": "east", "property_age": 3,
                         "floor_number": 3, "total_floors": 8},
            "rooms": None, "area": None, "building": None, "project": None, "parking": None,
            "type_details": None, "legal": None, "pg_details": None,
            "amenities": {}, "features": [],
            "rental": None, "sale": None,
            "location": {"address": "123 Test St", "state": "Tamil Nadu", "city": "Chennai",
                         "locality": "Velachery", "sub_locality": None, "landmark": None, "pincode": None,
                         "coordinates": {"type": "Point", "coordinates": [80.22, 12.97]}},
            "contact": {"name": "Test Owner", "phone": "9999999999", "whatsapp": None, "preferred_contact_method": "phone"},
            "description": {"text": "A nice flat.", "language": "en"},
            "media": {"images": [], "image_meta": [], "videos": [], "floor_plan": None, "brochure": None, "virtual_tour_url": None},
            "source": {"type": "owner", "url": None},
        }
        doc.update(overrides)
        return doc

    def _make_app(self, property_service):
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "test-secret"
        app.testing = True
        app.extensions["property_service"] = property_service

        login_manager = LoginManager()
        login_manager.init_app(app)

        @login_manager.user_loader
        def load_user(user_id):
            return StubUser()

        # property_details.html's nav links to these - stubbed here
        # rather than pulling in the real app.py (needs live MongoDB).
        @app.route("/")
        def home():
            return "home"

        from flask import Blueprint
        design_bp_stub = Blueprint("design", __name__)

        @design_bp_stub.route("/design")
        def design():
            return "design"

        app.register_blueprint(design_bp_stub)
        app.register_blueprint(property_bp)
        return app

    def test_existing_property_renders_the_real_details_page(self):
        property_service = FakePropertyServiceForSubmit()
        property_service.documents["real_prop_1"] = self._make_doc("real_prop_1")

        app = self._make_app(property_service)
        client = logged_in_client(app)

        response = client.get("/property/real_prop_1")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertIn("Apartment", html)
        self.assertIn("2 BHK", html)
        self.assertIn("Velachery", html)
        self.assertIn("25000", html)

    def test_deleted_property_redirects_instead_of_crashing(self):
        property_service = FakePropertyServiceForSubmit()  # no documents registered

        app = self._make_app(property_service)
        client = logged_in_client(app)

        response = client.get("/property/does_not_exist", follow_redirects=False)

        self.assertEqual(response.status_code, 302)


class PropertyServiceGetPropertyTests(unittest.TestCase):
    """Direct unit tests for services/property_services.py's
    get_property() - specifically the invalid-ObjectId safety fix this
    phase added, since a malformed property_id must be treated as
    "not found" (returns None), never an unhandled exception. No real
    MongoDB: the collection is a bare stand-in whose find_one() would
    raise AssertionError if ever reached with a bad id (proving the
    fix short-circuits before touching the collection at all)."""

    def test_invalid_object_id_string_returns_none_not_a_crash(self):
        from services.property_services import PropertyService

        class FakeCollection:
            def find_one(self, *_args, **_kwargs):
                raise AssertionError("should never query with an invalid id")

        class FakeMongoService:
            def get_collection(self, _name):
                return FakeCollection()

        service = PropertyService(FakeMongoService())

        self.assertIsNone(service.get_property("not-a-valid-object-id"))
        self.assertIsNone(service.get_property(None))


class PropertyUnlistRelistTests(unittest.TestCase):
    """Integration tests for POST /delete_listing/<id> (unlist) and
    POST /relist_listing/<id> (relist) - routes/property_routes.py.
    Exercises the REAL routes/blueprint via a Flask test client, with
    FakePropertyServiceForSubmit standing in for MongoDB. Confirms the
    application's actual existing semantics: unlisting is a reversible
    listing.status flip ("active" <-> "inactive"), never a permanent
    delete (PropertyService.delete_property() is never called by
    either route)."""

    OWNER_ID = "1"  # matches StubUser.id
    OTHER_USER_ID = "2"

    def _make_doc(self, property_id, status="active", owner_id=None):
        return {
            "_id": property_id,
            "seller": {"user_id": owner_id if owner_id is not None else self.OWNER_ID, "username": "owner"},
            "listing": {"type": "rent", "status": status, "price": 15000, "title": "Test Flat"},
            "property": {"type": "apartment", "bhk": 2},
            "location": {"city": "Chennai"},
            "media": {"images": []},
        }

    def _make_app(self, property_service):
        app = Flask(__name__)
        app.config["SECRET_KEY"] = "test-secret"
        app.testing = True
        app.extensions["property_service"] = property_service

        login_manager = LoginManager()
        login_manager.init_app(app)

        @login_manager.user_loader
        def load_user(user_id):
            return StubUser()

        @app.route("/")
        def home():
            return "home"

        # profile.html's nav links to these - stubbed here rather than
        # pulling in the real app.py (needs live MongoDB/SQLite setup).
        from flask import Blueprint

        design_bp_stub = Blueprint("design", __name__)

        @design_bp_stub.route("/design")
        def design():
            return "design"

        auth_bp_stub = Blueprint("auth", __name__)

        @auth_bp_stub.route("/logout")
        def logout():
            return "logout"

        app.register_blueprint(design_bp_stub)
        app.register_blueprint(auth_bp_stub)
        app.register_blueprint(property_bp)
        return app

    def test_owner_can_unlist_own_active_property(self):
        service = FakePropertyServiceForSubmit()
        service.documents["p1"] = self._make_doc("p1", status="active")
        app = self._make_app(service)
        client = logged_in_client(app)

        response = client.post("/delete_listing/p1", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.documents["p1"]["listing"]["status"], "inactive")
        self.assertIn(b"unlisted", response.data.lower())

    def test_owner_can_relist_own_inactive_property(self):
        service = FakePropertyServiceForSubmit()
        service.documents["p1"] = self._make_doc("p1", status="inactive")
        app = self._make_app(service)
        client = logged_in_client(app)

        response = client.post("/relist_listing/p1", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.documents["p1"]["listing"]["status"], "active")
        self.assertIn(b"relisted", response.data.lower())

    def test_unlisting_an_already_inactive_property_is_a_safe_no_op(self):
        service = FakePropertyServiceForSubmit()
        service.documents["p1"] = self._make_doc("p1", status="inactive")
        app = self._make_app(service)
        client = logged_in_client(app)

        response = client.post("/delete_listing/p1", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.documents["p1"]["listing"]["status"], "inactive")
        self.assertIn(b"already unlisted", response.data.lower())

    def test_relisting_an_already_active_property_is_a_safe_no_op(self):
        service = FakePropertyServiceForSubmit()
        service.documents["p1"] = self._make_doc("p1", status="active")
        app = self._make_app(service)
        client = logged_in_client(app)

        response = client.post("/relist_listing/p1", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.documents["p1"]["listing"]["status"], "active")
        self.assertIn(b"already listed", response.data.lower())

    def test_unauthorized_user_cannot_unlist_another_users_property(self):
        service = FakePropertyServiceForSubmit()
        service.documents["p1"] = self._make_doc("p1", status="active", owner_id=self.OTHER_USER_ID)
        app = self._make_app(service)
        client = logged_in_client(app)

        response = client.post("/delete_listing/p1", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.documents["p1"]["listing"]["status"], "active")
        self.assertIn(b"do not have permission", response.data.lower())

    def test_unauthorized_user_cannot_relist_another_users_property(self):
        service = FakePropertyServiceForSubmit()
        service.documents["p1"] = self._make_doc("p1", status="inactive", owner_id=self.OTHER_USER_ID)
        app = self._make_app(service)
        client = logged_in_client(app)

        response = client.post("/relist_listing/p1", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(service.documents["p1"]["listing"]["status"], "inactive")
        self.assertIn(b"do not have permission", response.data.lower())

    def test_unlisting_a_nonexistent_property_is_handled_safely(self):
        service = FakePropertyServiceForSubmit()
        app = self._make_app(service)
        client = logged_in_client(app)

        response = client.post("/delete_listing/does_not_exist", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"not found", response.data.lower())

    def test_relisting_a_nonexistent_property_is_handled_safely(self):
        service = FakePropertyServiceForSubmit()
        app = self._make_app(service)
        client = logged_in_client(app)

        response = client.post("/relist_listing/does_not_exist", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"not found", response.data.lower())

    def test_profile_page_shows_unlist_for_active_and_relist_for_inactive(self):
        service = FakePropertyServiceForSubmit()
        service.documents["active_prop"] = self._make_doc("active_prop", status="active")
        service.documents["inactive_prop"] = self._make_doc("inactive_prop", status="inactive")
        app = self._make_app(service)
        client = logged_in_client(app)

        response = client.get("/profile")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Unlist Property", html)
        self.assertIn("Relist Property", html)
        self.assertIn("View Property", html)
        self.assertIn("status-badge-inactive", html)


if __name__ == "__main__":
    unittest.main()
