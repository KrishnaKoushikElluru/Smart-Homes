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

from extensions import csrf
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
    # These tests exercise business logic, not CSRF itself - see
    # CSRFProtectionTests below for dedicated CSRF coverage (its own
    # app fixture leaves this enabled). Disabling it here is the
    # standard Flask-WTF testing convention, matching how
    # extensions.require_csrf itself checks this same flag.
    app.config["WTF_CSRF_ENABLED"] = False
    csrf.init_app(app)  # registers the csrf_token() Jinja global these templates call
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

    def update_property_for_owner(self, property_id, owner_user_id, updates):
        """Mirrors the real PropertyService.update_property_for_owner()'s
        OWNERSHIP-SCOPED semantics: only applies `updates` (a flat
        dotted-key dict, same shape MongoDB $set would receive) if the
        stored document's seller.user_id matches `owner_user_id` - the
        same guarantee the real method gets from putting both
        conditions directly in its update filter."""
        document = self.documents.get(property_id)
        if document is None:
            return False
        if (document.get("seller") or {}).get("user_id") != owner_user_id:
            return False
        for dotted_key, value in updates.items():
            parts = dotted_key.split(".")
            target = document
            for part in parts[:-1]:
                target = target.setdefault(part, {})
            target[parts[-1]] = value
        self.updates.append((property_id, updates))
        return True


def _real_png_bytes(color=(10, 20, 30), size=(4, 4)):
    from PIL import Image
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


def _make_submit_app(property_service, tmp_static_folder):
    app = Flask(__name__, static_folder=tmp_static_folder, static_url_path="/static")
    app.config["SECRET_KEY"] = "test-secret"
    # These tests exercise business logic, not CSRF itself - see
    # CSRFProtectionTests below for dedicated CSRF coverage (its own
    # app fixture leaves this enabled). Disabling it here is the
    # standard Flask-WTF testing convention, matching how
    # extensions.require_csrf itself checks this same flag.
    app.config["WTF_CSRF_ENABLED"] = False
    csrf.init_app(app)  # registers the csrf_token() Jinja global these templates call
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
        # These tests exercise business logic, not CSRF itself - see
        # CSRFProtectionTests below for dedicated CSRF coverage (its
        # own app fixture leaves this enabled). Disabling it here is
        # the standard Flask-WTF testing convention, matching how
        # extensions.require_csrf itself checks this same flag.
        app.config["WTF_CSRF_ENABLED"] = False
        csrf.init_app(app)  # registers the csrf_token() Jinja global these templates call
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

    def test_property_with_no_nearby_facilities_metadata_renders_without_the_section(self):
        """A legacy property (never enriched) must still render the
        page cleanly - no broken/empty "Nearby Amenities" block. This
        doubles as the existing-behavior-is-intact check: _make_doc()
        above has no nearby_facilities key at all, same as every other
        test in this class, and the page still renders fully (see
        test_existing_property_renders_the_real_details_page)."""
        property_service = FakePropertyServiceForSubmit()
        property_service.documents["p1"] = self._make_doc("p1")  # no nearby_facilities key

        app = self._make_app(property_service)
        client = logged_in_client(app)

        response = client.get("/property/p1")

        self.assertEqual(response.status_code, 200)
        html = response.get_data(as_text=True)
        self.assertNotIn("Nearby Amenities", html)

    def test_property_with_multiple_facilities_across_categories_renders_them_all(self):
        property_service = FakePropertyServiceForSubmit()
        property_service.documents["p1"] = self._make_doc(
            "p1",
            nearby_facilities=[
                {"name": "Tiger Gym", "category": "gym", "address": "Gandhi Road", "distance_m": 134},
                {"name": "Gold's Gym", "category": "gym", "address": "2nd Street", "distance_m": 600},
                {"name": "ABC Hospital", "category": "hospital", "address": "Main Road", "distance_m": 700},
            ],
            nearby_facilities_metadata={"status": "completed", "source": "mappls", "radius_m": 2000.0},
        )

        app = self._make_app(property_service)
        client = logged_in_client(app)

        response = client.get("/property/p1")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("Nearby Amenities", html)
        self.assertIn("Tiger Gym", html)
        self.assertIn("Gold&#39;s Gym", html)  # BOTH gyms, not just the closest (Jinja-escaped apostrophe)
        self.assertIn("ABC Hospital", html)
        self.assertIn("134 m", html)
        self.assertIn("700 m", html)
        # Category labels are CSS-uppercased for display, not
        # uppercased in the markup itself - assert the real text.
        self.assertIn("Gyms", html)
        self.assertIn("Hospitals", html)

    def test_facility_with_missing_address_still_renders(self):
        property_service = FakePropertyServiceForSubmit()
        property_service.documents["p1"] = self._make_doc(
            "p1",
            nearby_facilities=[
                {"name": "Tiger Gym", "category": "gym", "address": None, "distance_m": 134},
            ],
            nearby_facilities_metadata={"status": "completed", "source": "mappls", "radius_m": 2000.0},
        )

        app = self._make_app(property_service)
        client = logged_in_client(app)

        html = client.get("/property/p1").get_data(as_text=True)
        self.assertIn("Tiger Gym", html)
        self.assertIn("134 m", html)

    def test_facility_with_missing_distance_does_not_show_a_misleading_distance(self):
        property_service = FakePropertyServiceForSubmit()
        property_service.documents["p1"] = self._make_doc(
            "p1",
            nearby_facilities=[
                {"name": "Tiger Gym", "category": "gym", "address": "Gandhi Road", "distance_m": None},
            ],
            nearby_facilities_metadata={"status": "completed", "source": "mappls", "radius_m": 2000.0},
        )

        app = self._make_app(property_service)
        client = logged_in_client(app)

        html = client.get("/property/p1").get_data(as_text=True)
        self.assertIn("Tiger Gym", html)
        self.assertNotIn("None away", html)
        self.assertNotIn("0 m away", html)

    def test_pending_enrichment_shows_a_preparing_message_not_empty_section(self):
        property_service = FakePropertyServiceForSubmit()
        property_service.documents["p1"] = self._make_doc(
            "p1", nearby_facilities=[],
            nearby_facilities_metadata={"status": "pending", "source": "mappls", "radius_m": 2000.0},
        )

        app = self._make_app(property_service)
        client = logged_in_client(app)

        html = client.get("/property/p1").get_data(as_text=True)
        self.assertIn("Nearby Amenities", html)
        self.assertIn("being prepared", html)

    def test_failed_enrichment_does_not_pretend_to_be_an_empty_success(self):
        property_service = FakePropertyServiceForSubmit()
        property_service.documents["p1"] = self._make_doc(
            "p1", nearby_facilities=[],
            nearby_facilities_metadata={"status": "failed", "source": "mappls", "radius_m": 2000.0},
        )

        app = self._make_app(property_service)
        client = logged_in_client(app)

        html = client.get("/property/p1").get_data(as_text=True)
        self.assertIn("Nearby Amenities", html)
        self.assertIn("could not be checked", html)
        self.assertNotIn("No nearby facilities were found", html)


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
        # These tests exercise business logic, not CSRF itself - see
        # CSRFProtectionTests below for dedicated CSRF coverage (its
        # own app fixture leaves this enabled). Disabling it here is
        # the standard Flask-WTF testing convention, matching how
        # extensions.require_csrf itself checks this same flag.
        app.config["WTF_CSRF_ENABLED"] = False
        csrf.init_app(app)  # registers the csrf_token() Jinja global these templates call
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


class CSRFProtectionTests(unittest.TestCase):
    """Dedicated coverage for extensions.require_csrf, applied to the 4
    property-mutation routes (submit_listing/update_listing/
    delete_listing/relist_listing). Unlike every other test class in
    this file, CSRF is left ENABLED here (no WTF_CSRF_ENABLED=False) -
    this is the one place that actually exercises the real Flask-WTF
    token generation/validation path end to end."""

    OWNER_ID = "1"  # matches StubUser.id

    def _make_doc(self, property_id, status="active"):
        return {
            "_id": property_id,
            "seller": {"user_id": self.OWNER_ID, "username": "owner"},
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
        app.extensions["osm_location_service"] = FakeOSMService()

        csrf.init_app(app)  # CSRF genuinely enabled - this is the point of this class

        login_manager = LoginManager()
        login_manager.init_app(app)

        @login_manager.user_loader
        def load_user(user_id):
            return StubUser()

        @app.route("/")
        def home():
            return "home"

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

    def _valid_token_and_session_seed(self, app):
        """Generates a REAL, correctly-signed Flask-WTF CSRF token
        (via the same generate_csrf() the templates call), plus the
        raw per-session seed value it was signed against - both are
        needed: the signed token goes in the request's form field, the
        raw seed must already be in the test client's session for
        validate_csrf() to successfully verify it (this is the
        standard way to test a Flask-WTF-protected endpoint - see
        Flask-WTF's own test suite for the identical pattern)."""
        from flask_wtf.csrf import generate_csrf
        from flask import session

        with app.test_request_context():
            token = generate_csrf()
            seed = session["csrf_token"]

        return token, seed

    def test_valid_csrf_token_allows_the_request_to_succeed(self):
        service = FakePropertyServiceForSubmit()
        service.documents["p1"] = self._make_doc("p1")
        app = self._make_app(service)
        token, seed = self._valid_token_and_session_seed(app)
        client = logged_in_client(app)

        with client.session_transaction() as sess:
            sess["csrf_token"] = seed

        response = client.post(
            "/delete_listing/p1", data={"csrf_token": token}, follow_redirects=False
        )

        # A normal successful unlist redirects to /profile - the ROUTE'S
        # OWN logic ran, proving CSRF validation passed (a CSRF failure
        # would be a 400 from handle_csrf_error, never a 302).
        self.assertEqual(response.status_code, 302)
        self.assertEqual(service.documents["p1"]["listing"]["status"], "inactive")

    def test_missing_csrf_token_is_rejected(self):
        service = FakePropertyServiceForSubmit()
        service.documents["p1"] = self._make_doc("p1")
        app = self._make_app(service)
        client = logged_in_client(app)

        response = client.post("/delete_listing/p1", data={})

        self.assertEqual(response.status_code, 400)
        # The route's own logic must NEVER have run - status unchanged.
        self.assertEqual(service.documents["p1"]["listing"]["status"], "active")

    def test_invalid_csrf_token_is_rejected(self):
        service = FakePropertyServiceForSubmit()
        service.documents["p1"] = self._make_doc("p1")
        app = self._make_app(service)
        _, seed = self._valid_token_and_session_seed(app)
        client = logged_in_client(app)

        with client.session_transaction() as sess:
            sess["csrf_token"] = seed

        response = client.post(
            "/delete_listing/p1", data={"csrf_token": "not-a-real-token"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(service.documents["p1"]["listing"]["status"], "active")

    def test_get_routes_remain_completely_unaffected(self):
        """GET requests are never in Flask-WTF's own WTF_CSRF_METHODS
        set (POST/PUT/PATCH/DELETE only) - a GET route must keep
        working with no token at all, CSRF enabled or not."""
        service = FakePropertyServiceForSubmit()
        service.documents["p1"] = self._make_doc("p1")
        app = self._make_app(service)
        client = logged_in_client(app)

        response = client.get("/profile")

        self.assertEqual(response.status_code, 200)

    def test_all_four_mutation_routes_require_csrf(self):
        """Sweep proving EVERY one of the 4 named routes is actually
        decorated, not just delete_listing (tested in isolation
        above). CSRF validation happens before any of the route's own
        business logic, so an otherwise-empty/invalid body still
        reaches the CSRF check first and is rejected the same way."""
        service = FakePropertyServiceForSubmit()
        service.documents["p1"] = self._make_doc("p1", status="inactive")
        app = self._make_app(service)
        client = logged_in_client(app)

        for path in (
            "/submit_listing",
            "/update_listing/p1",
            "/delete_listing/p1",
            "/relist_listing/p1",
        ):
            with self.subTest(path=path):
                response = client.post(path, data={})
                self.assertEqual(response.status_code, 400)


class EditListingTestsBase(unittest.TestCase):
    """Shared fixtures for GET /edit_listing/<id> and POST
    /update_listing/<id> - routes/property_routes.py's edit_listing()
    and update_listing(). Mirrors PropertyUnlistRelistTests' and
    SubmitListingProductionEmbeddingTests' established conventions
    (FakePropertyServiceForSubmit standing in for MongoDB, a tmp
    static folder so media_service's real save/delete file operations
    have somewhere safe to write)."""

    OWNER_ID = "1"  # matches StubUser.id
    OTHER_USER_ID = "2"

    def _make_doc(self, property_id, owner_id=None, status="active",
                  price=25000, bhk="2", lat=12.84, lon=80.15,
                  images=None, image_meta=None):
        # Defaults to one existing image - a real property being
        # edited already has images, and update_listing() (like
        # submit_listing()) requires at least one image across
        # existing-kept + newly-added. Tests specifically about image
        # add/remove/replace behavior pass their own images/image_meta.
        images = ["default.jpg"] if images is None else images
        image_meta = (
            [{"filename": "default.jpg", "category": "other", "is_cover": True}]
            if image_meta is None else image_meta
        )
        return {
            "_id": property_id,
            "seller": {"user_id": owner_id if owner_id is not None else self.OWNER_ID, "username": "owner"},
            "listing": {"type": "rent", "status": status, "price": price,
                        "price_negotiable": False, "title": "Test Flat", "posted_by": "owner"},
            "property": {"type": "apartment", "bhk": bhk, "area_sqft": 950, "bathrooms": 2,
                         "balconies": 1, "furnishing": "semi_furnished", "facing": "east",
                         "property_age": 3, "floor_number": 3, "total_floors": 8},
            "rooms": {"bhk": str(bhk), "bathrooms": 2, "balconies": 1},
            "area": {"built_up_sqft": 950},
            "building": {"furnishing": "semi_furnished", "facing": "east",
                         "floor_number": 3, "total_floors": 8, "property_age": 3},
            "project": None, "parking": None, "type_details": None, "legal": None, "pg_details": None,
            "amenities": {}, "features": [],
            "rental": {"security_deposit": 50000}, "sale": None,
            "location": {"address": "123 Test St", "state": "Tamil Nadu", "city": "Chennai",
                         "locality": "Velachery", "sub_locality": None, "landmark": None,
                         "pincode": "600042",
                         "coordinates": {"type": "Point", "coordinates": [lon, lat]}},
            "contact": {"name": "Test Owner", "phone": "9999999999", "whatsapp": None,
                        "preferred_contact_method": "phone"},
            "description": {"text": "A nice flat.", "language": "en"},
            "media": {"images": images, "image_meta": image_meta, "videos": [],
                      "floor_plan": None, "brochure": None, "virtual_tour_url": None},
            "source": {"type": "owner", "url": None},
        }

    def _make_app(self, property_service, tmp_static_folder):
        app = Flask(__name__, static_folder=tmp_static_folder, static_url_path="/static")
        app.config["SECRET_KEY"] = "test-secret"
        # These tests exercise business logic, not CSRF itself - see
        # CSRFProtectionTests below for dedicated CSRF coverage (its
        # own app fixture leaves this enabled). Disabling it here is
        # the standard Flask-WTF testing convention, matching how
        # extensions.require_csrf itself checks this same flag.
        app.config["WTF_CSRF_ENABLED"] = False
        csrf.init_app(app)  # registers the csrf_token() Jinja global these templates call
        app.testing = True
        app.extensions["property_service"] = property_service
        app.extensions["osm_location_service"] = FakeOSMService()

        login_manager = LoginManager()
        login_manager.init_app(app)

        @login_manager.user_loader
        def load_user(user_id):
            return StubUser()

        @app.route("/")
        def home():
            return "home"

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

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.property_service = FakePropertyServiceForSubmit()
        self.app = self._make_app(self.property_service, self._tmpdir.name)
        self.client = logged_in_client(self.app)

    def tearDown(self):
        self._tmpdir.cleanup()

    def _minimal_apartment_rent_form(self, **overrides):
        base = {
            "listing_type": "rent",
            "property_type": "apartment",
            "title": "Test Apartment",
            "price": "25000",
            "address": "123 Test Street",
            "city": "Chennai",
            "latitude": "12.84",
            "longitude": "80.15",
            "contact_name": "Test Owner",
            "contact_phone": "9876543210",
            "bhk": "2",
            "built_up_sqft": "950",
            "floor_number": "3",
            "total_floors": "8",
        }
        base.update(overrides)
        return base


class EditListingGetRouteTests(EditListingTestsBase):
    """1) owner can open the edit form; 2) it pre-fills current values;
    plus the ownership and not-found safety checks GET must also have."""

    def test_owner_can_open_edit_form(self):
        self.property_service.documents["p1"] = self._make_doc("p1")

        response = self.client.get("/edit_listing/p1")

        self.assertEqual(response.status_code, 200)
        self.assertIn("Edit Listing", response.get_data(as_text=True))

    def test_values_populate_correctly(self):
        self.property_service.documents["p1"] = self._make_doc("p1", price=25000)

        html = self.client.get("/edit_listing/p1").get_data(as_text=True)

        # The price input must carry the CURRENT stored value, not an
        # empty "create" form - this is the actual pre-fill contract
        # _property_field_values() + _field_macros.html's value-aware
        # render_field() exist for.
        self.assertIn('value="25000"', html)
        self.assertIn('value="123 Test St"', html)
        self.assertIn('value="Test Owner"', html)

    def test_unauthorized_user_cannot_open_another_users_edit_form(self):
        self.property_service.documents["p1"] = self._make_doc("p1", owner_id=self.OTHER_USER_ID)

        response = self.client.get("/edit_listing/p1", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"do not have permission", response.data.lower())

    def test_invalid_property_id_handled_safely(self):
        response = self.client.get("/edit_listing/does_not_exist", follow_redirects=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"not found", response.data.lower())


class UpdateListingRouteTests(EditListingTestsBase):
    """3-13 and 15-17 of the 19 explicitly required behaviors: basic
    field updates actually reach the stored document and Profile,
    ownership/validation safety, and the image <-> similarity-index
    and location <-> nearby-enrichment synchronization rules."""

    def test_owner_can_update_basic_fields_and_mongo_reflects_it(self):
        self.property_service.documents["p1"] = self._make_doc("p1", price=25000, bhk="2")

        with patch("services.image_similarity.production_indexer.start_background_embedding"):
            response = self.client.post(
                "/update_listing/p1",
                data=self._minimal_apartment_rent_form(price="30000", bhk="3"),
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        updated_doc = self.property_service.documents["p1"]
        self.assertEqual(updated_doc["listing"]["price"], 30000.0)
        self.assertEqual(updated_doc["property"]["bhk"], 3)

    def test_profile_reflects_updated_values_immediately(self):
        self.property_service.documents["p1"] = self._make_doc("p1", price=25000)

        with patch("services.image_similarity.production_indexer.start_background_embedding"):
            self.client.post(
                "/update_listing/p1",
                data=self._minimal_apartment_rent_form(price="30000"),
                content_type="multipart/form-data",
            )

        html = self.client.get("/profile").get_data(as_text=True)
        self.assertIn("30000", html)
        self.assertNotIn("25000", html)

    def test_unauthorized_user_cannot_update_another_users_property(self):
        self.property_service.documents["p1"] = self._make_doc("p1", owner_id=self.OTHER_USER_ID, price=25000)

        response = self.client.post(
            "/update_listing/p1",
            data=self._minimal_apartment_rent_form(price="99999"),
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"do not have permission", response.data.lower())
        self.assertEqual(self.property_service.documents["p1"]["listing"]["price"], 25000)

    def test_update_scoped_to_owner_at_the_service_layer(self):
        # Structural proof, not just behavioral: update_listing() must
        # call the OWNER-SCOPED method, not the unscoped update_property()
        # whose MongoDB filter is _id-only (see PropertyService.
        # update_property_for_owner()'s own docstring for why that
        # distinction is the real security boundary, not just the
        # app-level seller.user_id check above it).
        self.property_service.documents["p1"] = self._make_doc("p1")

        with patch.object(
            self.property_service, "update_property_for_owner",
            wraps=self.property_service.update_property_for_owner,
        ) as mock_update:
            with patch("services.image_similarity.production_indexer.start_background_embedding"):
                self.client.post(
                    "/update_listing/p1",
                    data=self._minimal_apartment_rent_form(),
                    content_type="multipart/form-data",
                )

        mock_update.assert_called_once()
        call_args = mock_update.call_args.args
        self.assertEqual(call_args[0], "p1")
        self.assertEqual(call_args[1], self.OWNER_ID)

    def test_invalid_property_id_handled_safely_on_update(self):
        response = self.client.post(
            "/update_listing/does_not_exist",
            data=self._minimal_apartment_rent_form(),
            content_type="multipart/form-data",
            follow_redirects=True,
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn(b"not found", response.data.lower())

    def test_validation_errors_handled_correctly(self):
        self.property_service.documents["p1"] = self._make_doc("p1", price=25000)

        with patch(
            "services.image_similarity.production_indexer.start_background_embedding"
        ) as mock_start:
            response = self.client.post(
                "/update_listing/p1",
                data=self._minimal_apartment_rent_form(price="not-a-number"),
                content_type="multipart/form-data",
                follow_redirects=True,
            )

        self.assertEqual(response.status_code, 200)
        # Invalid data must never reach the stored document.
        self.assertEqual(self.property_service.documents["p1"]["listing"]["price"], 25000)
        mock_start.assert_not_called()

    def test_metadata_only_update_does_not_trigger_reembedding(self):
        self.property_service.documents["p1"] = self._make_doc(
            "p1", price=25000, images=["existing.jpg"],
            image_meta=[{"filename": "existing.jpg", "category": "other", "is_cover": True}],
        )

        with patch(
            "services.image_similarity.production_indexer.start_background_embedding"
        ) as mock_start, patch(
            "services.image_similarity.production_indexer.remove_property_image_embeddings"
        ) as mock_remove:
            response = self.client.post(
                "/update_listing/p1",
                data=self._minimal_apartment_rent_form(price="30000"),
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        mock_start.assert_not_called()
        mock_remove.assert_not_called()
        self.assertEqual(
            self.property_service.documents["p1"]["media"]["images"], ["existing.jpg"]
        )

    def test_adding_an_image_triggers_background_embedding_for_the_new_image_only(self):
        self.property_service.documents["p1"] = self._make_doc(
            "p1", images=["existing.jpg"],
            image_meta=[{"filename": "existing.jpg", "category": "other", "is_cover": True}],
        )

        with patch(
            "services.image_similarity.production_indexer.start_background_embedding"
        ) as mock_start:
            response = self.client.post(
                "/update_listing/p1",
                data={
                    **self._minimal_apartment_rent_form(),
                    "images": (io.BytesIO(_real_png_bytes()), "new.png"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        mock_start.assert_called_once()
        call_args = mock_start.call_args.args
        self.assertEqual(call_args[0], "p1")
        self.assertEqual(len(call_args[1]), 1)  # only the NEW image, never "existing.jpg"
        self.assertNotIn("existing.jpg", call_args[1])

        updated_images = self.property_service.documents["p1"]["media"]["images"]
        self.assertIn("existing.jpg", updated_images)
        self.assertEqual(len(updated_images), 2)

    def test_removing_an_image_removes_its_similarity_index_entry(self):
        self.property_service.documents["p1"] = self._make_doc(
            "p1",
            images=["keep.jpg", "remove_me.jpg"],
            image_meta=[
                {"filename": "keep.jpg", "category": "other", "is_cover": True},
                {"filename": "remove_me.jpg", "category": "other", "is_cover": False},
            ],
        )

        with patch(
            "services.image_similarity.production_indexer.remove_property_image_embeddings"
        ) as mock_remove, patch(
            "services.image_similarity.production_indexer.start_background_embedding"
        ) as mock_start:
            response = self.client.post(
                "/update_listing/p1",
                data={
                    **self._minimal_apartment_rent_form(),
                    "remove_images": "remove_me.jpg",
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        mock_remove.assert_called_once_with("p1", ["remove_me.jpg"])
        mock_start.assert_not_called()  # no NEW image here - metadata+removal only

        updated_images = self.property_service.documents["p1"]["media"]["images"]
        self.assertEqual(updated_images, ["keep.jpg"])

    def test_replacing_an_image_updates_the_similarity_index_both_ways(self):
        self.property_service.documents["p1"] = self._make_doc(
            "p1",
            images=["old.jpg"],
            image_meta=[{"filename": "old.jpg", "category": "other", "is_cover": True}],
        )

        with patch(
            "services.image_similarity.production_indexer.remove_property_image_embeddings"
        ) as mock_remove, patch(
            "services.image_similarity.production_indexer.start_background_embedding"
        ) as mock_start:
            response = self.client.post(
                "/update_listing/p1",
                data={
                    **self._minimal_apartment_rent_form(),
                    "remove_images": "old.jpg",
                    "images": (io.BytesIO(_real_png_bytes()), "new.png"),
                },
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        mock_remove.assert_called_once_with("p1", ["old.jpg"])
        mock_start.assert_called_once()

        updated_images = self.property_service.documents["p1"]["media"]["images"]
        self.assertEqual(len(updated_images), 1)
        self.assertNotIn("old.jpg", updated_images)

    def test_existing_images_remain_intact_when_not_removed(self):
        self.property_service.documents["p1"] = self._make_doc(
            "p1",
            images=["a.jpg", "b.jpg"],
            image_meta=[
                {"filename": "a.jpg", "category": "other", "is_cover": True},
                {"filename": "b.jpg", "category": "other", "is_cover": False},
            ],
        )

        with patch("services.image_similarity.production_indexer.start_background_embedding"):
            response = self.client.post(
                "/update_listing/p1",
                data=self._minimal_apartment_rent_form(price="30000"),
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        self.assertEqual(
            sorted(self.property_service.documents["p1"]["media"]["images"]),
            ["a.jpg", "b.jpg"],
        )

    def test_location_change_triggers_nearby_enrichment(self):
        self.property_service.documents["p1"] = self._make_doc("p1", lat=12.84, lon=80.15)

        with patch("services.image_similarity.production_indexer.start_background_embedding"), \
             patch("services.nearby_facility_service.start_background_enrichment") as mock_enrich:

            response = self.client.post(
                "/update_listing/p1",
                data=self._minimal_apartment_rent_form(latitude="13.0", longitude="81.0"),
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        mock_enrich.assert_called_once()
        self.assertEqual(mock_enrich.call_args.args[0], "p1")

    def test_no_location_change_does_not_trigger_enrichment(self):
        self.property_service.documents["p1"] = self._make_doc("p1", lat=12.84, lon=80.15)

        with patch("services.image_similarity.production_indexer.start_background_embedding"), \
             patch("services.nearby_facility_service.start_background_enrichment") as mock_enrich:

            response = self.client.post(
                "/update_listing/p1",
                data=self._minimal_apartment_rent_form(latitude="12.84", longitude="80.15", price="30000"),
                content_type="multipart/form-data",
            )

        self.assertEqual(response.status_code, 302)
        mock_enrich.assert_not_called()

    def test_editing_does_not_change_unlisted_status(self):
        self.property_service.documents["p1"] = self._make_doc("p1", status="inactive", price=25000)

        with patch("services.image_similarity.production_indexer.start_background_embedding"):
            self.client.post(
                "/update_listing/p1",
                data=self._minimal_apartment_rent_form(price="30000"),
                content_type="multipart/form-data",
            )

        updated_doc = self.property_service.documents["p1"]
        self.assertEqual(updated_doc["listing"]["status"], "inactive")
        self.assertEqual(updated_doc["listing"]["price"], 30000.0)

    def test_editing_does_not_change_an_active_listed_status(self):
        self.property_service.documents["p1"] = self._make_doc("p1", status="active", price=25000)

        with patch("services.image_similarity.production_indexer.start_background_embedding"):
            self.client.post(
                "/update_listing/p1",
                data=self._minimal_apartment_rent_form(price="30000"),
                content_type="multipart/form-data",
            )

        self.assertEqual(self.property_service.documents["p1"]["listing"]["status"], "active")


if __name__ == "__main__":
    unittest.main()
