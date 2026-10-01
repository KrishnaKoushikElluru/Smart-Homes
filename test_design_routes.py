"""
Integration tests for routes/design_routes.py's reference-image upload
endpoint (POST /design/upload_reference).

Exercises the REAL Flask blueprint/routing/session layer (a genuine
Flask test client), matching test_property_routes.py's established
convention (minimal standalone app, not the real app.py). No network
calls: the uploaded file never reaches Gemini/FLUX in this phase, so
services.image_service is not touched by these tests at all.
"""

import base64
import io
import os
import tempfile
import unittest
from unittest.mock import patch

from flask import Flask, Blueprint
from flask_login import LoginManager, UserMixin
from PIL import Image

from routes.design_routes import design_bp


class StubUser(UserMixin):
    id = "1"


class FakePropertyService:
    """Minimal PropertyService.get_property() stand-in for
    _enrich_similarity_results() - no real MongoDB. `documents` maps
    property_id -> a raw property document dict (or omits it, to
    simulate a deleted/missing property)."""

    def __init__(self, documents=None):
        self.documents = documents or {}

    def get_property(self, property_id):
        return self.documents.get(property_id)


def make_property_doc(property_id, images=None, **overrides):
    """A minimal-but-realistic property document - enough fields for
    routes/search_routes.py's REAL _serialize_property() (reused by
    _enrich_similarity_results()) to produce a full summary."""

    doc = {
        "_id": property_id,
        "listing": {"type": "sell", "status": "active", "price": 5000000, "title": "Test Property"},
        "property": {"type": "apartment", "bhk": 2, "area_sqft": 1100},
        "location": {"city": "Chennai", "locality": "Adyar"},
        "description": {"text": "A test property."},
        "contact": {"name": "Test Owner", "phone": "9999999999"},
        "media": {"images": images or [], "image_meta": []},
        "source": {"type": "owner"},
        "building": {"furnishing": "semi_furnished"},
    }
    doc.update(overrides)
    return doc


def make_test_app(tmp_static_folder, property_service=None):
    app = Flask(__name__, static_folder=tmp_static_folder, static_url_path="/static")
    app.config["SECRET_KEY"] = "test-secret"
    app.testing = True

    app.extensions["property_service"] = property_service or FakePropertyService()

    login_manager = LoginManager()
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return StubUser()

    app.register_blueprint(design_bp)

    # design.html's header nav links to url_for('home') and
    # url_for('property.rentals') - stub both here rather than pulling
    # in the real app.py (which needs a live MongoDB connection), same
    # spirit as test_property_routes.py's make_test_app not needing
    # the design blueprint at all. property_details is the EXISTING
    # detail-page route that a similarity card's detail_url must point
    # to - stubbed minimally here (its own real behavior is tested in
    # test_property_routes.py against the REAL property_bp).
    @app.route("/")
    def home():
        return "home"

    stub_property_bp = Blueprint("property", __name__)

    @stub_property_bp.route("/rentals")
    def rentals():
        return "rentals"

    @stub_property_bp.route("/property/<property_id>")
    def property_details(property_id):
        return f"property details page for {property_id}"

    app.register_blueprint(stub_property_bp)

    return app


def logged_in_client(app):
    client = app.test_client()
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True
    return client


def _real_png_bytes(color=(255, 0, 0), size=(4, 4)):
    buf = io.BytesIO()
    Image.new("RGB", size, color=color).save(buf, format="PNG")
    return buf.getvalue()


class UploadReferenceImageTests(unittest.TestCase):

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.app = make_test_app(self._tmpdir.name)
        self.client = logged_in_client(self.app)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_requires_login(self):
        anon_client = self.app.test_client()

        response = anon_client.post(
            "/design/upload_reference",
            data={"reference_image": (io.BytesIO(_real_png_bytes()), "house.png")},
            content_type="multipart/form-data",
        )

        # flask_login's default unauthorized handler without a
        # configured login view raises/produces a 401.
        self.assertEqual(response.status_code, 401)

    def test_valid_png_upload_succeeds_and_returns_static_url(self):
        response = self.client.post(
            "/design/upload_reference",
            data={"reference_image": (io.BytesIO(_real_png_bytes()), "house.png")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertIn("reference_image_url", data)
        self.assertTrue(data["reference_image_url"].startswith("/static/images/design_references/"))
        # Never leaks a filesystem path.
        self.assertNotIn(self._tmpdir.name.replace("\\", "/"), data["reference_image_url"])

    def test_valid_jpeg_upload_succeeds(self):
        buf = io.BytesIO()
        Image.new("RGB", (4, 4), color=(0, 255, 0)).save(buf, format="JPEG")

        response = self.client.post(
            "/design/upload_reference",
            data={"reference_image": (io.BytesIO(buf.getvalue()), "house.jpg")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 200)
        self.assertIn("reference_image_url", response.get_json())

    def test_no_file_returns_400(self):
        response = self.client.post(
            "/design/upload_reference",
            data={},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.get_json())

    def test_unsupported_file_type_rejected(self):
        response = self.client.post(
            "/design/upload_reference",
            data={"reference_image": (io.BytesIO(b"not a real gif but has the extension"), "house.gif")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("unsupported file type", response.get_json()["error"].lower())

    def test_oversized_upload_rejected(self):
        from services import media_service

        oversized = b"\xff" * (media_service.MAX_IMAGE_BYTES + 1)

        response = self.client.post(
            "/design/upload_reference",
            data={"reference_image": (io.BytesIO(oversized), "house.png")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("exceeds the maximum", response.get_json()["error"])

    def test_malformed_non_image_file_with_image_extension_rejected(self):
        # Correct extension, correct-ish size, but not real image bytes -
        # must be rejected on CONTENT, not just extension (Pillow verify).
        response = self.client.post(
            "/design/upload_reference",
            data={"reference_image": (io.BytesIO(b"this is definitely not a png" * 50), "house.png")},
            content_type="multipart/form-data",
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("not a valid image", response.get_json()["error"])

    def test_replace_upload_overwrites_previous_reference(self):
        first = self.client.post(
            "/design/upload_reference",
            data={"reference_image": (io.BytesIO(_real_png_bytes(color=(255, 0, 0))), "first.png")},
            content_type="multipart/form-data",
        )
        second = self.client.post(
            "/design/upload_reference",
            data={"reference_image": (io.BytesIO(_real_png_bytes(color=(0, 0, 255))), "second.png")},
            content_type="multipart/form-data",
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        # Each upload is validated/saved independently and gets its own
        # collision-safe filename - replacing is just "upload again".
        self.assertNotEqual(
            first.get_json()["reference_image_url"],
            second.get_json()["reference_image_url"],
        )


class DesignPageRenderTests(unittest.TestCase):
    """Smoke tests for GET /design's rendered markup after the
    two-step source-selection redesign (templates/design.html). These
    intentionally check structure/text, not visual layout - the real
    interaction logic (mode switching, reference-image state, stale-
    request guards) lives in static/design_reference_state.js and is
    covered by test_design_reference_state.js (node:test) instead,
    since it has no server-side equivalent to exercise here."""

    def setUp(self):
        import tempfile
        self._tmpdir = tempfile.TemporaryDirectory()
        self.app = make_test_app(self._tmpdir.name)
        self.client = logged_in_client(self.app)

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_page_requires_login(self):
        anon_client = self.app.test_client()
        response = anon_client.get("/design")
        self.assertEqual(response.status_code, 401)

    def test_page_renders_source_selection_step(self):
        response = self.client.get("/design")
        html = response.get_data(as_text=True)

        self.assertEqual(response.status_code, 200)
        self.assertIn("How would you like to provide your reference image?", html)
        self.assertIn("Generate an Image", html)
        self.assertIn("Upload an Image", html)

    def test_page_still_contains_existing_generate_workflow_controls(self):
        # The redesign must not have dropped any existing functionality -
        # the same ids/controls from before must still be present.
        html = self.client.get("/design").get_data(as_text=True)

        self.assertIn('id="houseDescription"', html)
        self.assertIn('id="designVoiceButton"', html)
        self.assertIn('id="generateButton"', html)
        self.assertIn('id="imagePreview"', html)
        self.assertIn("resetDesign()", html)

    def test_page_still_contains_existing_upload_workflow_controls(self):
        html = self.client.get("/design").get_data(as_text=True)

        self.assertIn('id="referenceImageInput"', html)
        self.assertIn('id="removeReferenceButton"', html)
        self.assertIn('id="referenceImagePreview"', html)
        self.assertIn("Accepted formats: JPG, PNG, WebP.", html)

    def test_page_contains_find_similar_homes_action(self):
        html = self.client.get("/design").get_data(as_text=True)

        self.assertIn('id="findSimilarButton"', html)
        self.assertIn("Find Similar Homes", html)
        # Disabled by default in the markup - JS only enables it once a
        # reference image is ready.
        self.assertIn("disabled", html.split('id="findSimilarButton"')[1].split(">")[0])

    def test_page_loads_the_reference_state_module_before_the_upload_module(self):
        # design_reference_state.js must be a real static asset the
        # page can load (not just referenced) and must load before the
        # inline script that depends on window.DesignReferenceState.
        html = self.client.get("/design").get_data(as_text=True)

        self.assertIn("design_reference_state.js", html)
        state_script_pos = html.index("design_reference_state.js")
        inline_script_pos = html.index("window.DesignReferenceState.create")
        self.assertLess(state_script_pos, inline_script_pos)


class FindSimilarRouteTests(unittest.TestCase):
    """Integration tests for POST /design/find_similar - now the
    PRODUCTION similarity endpoint (source="mongodb_production" only,
    services/image_similarity/production_indexer.py). No real SigLIP2
    model is loaded: the encoder is mocked via
    services.image_similarity.siglip2_encoder.get_default_encoder
    (patched at its source, since routes/design_routes.py imports it
    lazily, inside the route function, not at module load time). The
    candidate index is a real (tiny) EmbeddingCache saved to a temp
    directory at the exact paths production_indexer.py reads from
    (patched via PRODUCTION_NPZ_PATH/PRODUCTION_META_PATH) - exercises
    the real file-loading code path without needing a real MongoDB or
    the actual 84-image benchmark dataset."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.property_service = FakePropertyService()
        self.app = make_test_app(self._tmpdir.name, property_service=self.property_service)
        self.client = logged_in_client(self.app)
        self._cache_tmpdir = tempfile.TemporaryDirectory()
        self._npz_path = os.path.join(self._cache_tmpdir.name, "production_index.npz")
        self._meta_path = os.path.join(self._cache_tmpdir.name, "production_index_meta.json")

    def tearDown(self):
        self._tmpdir.cleanup()
        self._cache_tmpdir.cleanup()

    def _production_paths_patch(self):
        return patch.multiple(
            "services.image_similarity.production_indexer",
            PRODUCTION_NPZ_PATH=self._npz_path,
            PRODUCTION_META_PATH=self._meta_path,
        )

    def _save_fake_cache(self, records, source="mongodb_production"):
        """records: iterable of (property_id, image_id, embedding),
        or (property_id, image_id, embedding, source) to override the
        per-record source (used by the isolation test below)."""
        from services.image_similarity.embedding_cache import EmbeddingCache

        cache = EmbeddingCache()
        for record in records:
            if len(record) == 4:
                property_id, image_id, embedding, record_source = record
            else:
                property_id, image_id, embedding = record
                record_source = source
            cache.add(property_id, image_id, f"/fake/{image_id}", "fake-model", embedding, source=record_source)

        cache.save(self._npz_path, self._meta_path)

    def _reference_body(self, source="generated"):
        png_b64 = base64.b64encode(_real_png_bytes()).decode("ascii")
        return {"reference_image_url": f"data:image/png;base64,{png_b64}", "source": source}

    def test_requires_login(self):
        anon_client = self.app.test_client()
        response = anon_client.post("/design/find_similar", json=self._reference_body())
        self.assertEqual(response.status_code, 401)

    def test_missing_reference_image_returns_400(self):
        response = self.client.post("/design/find_similar", json={})
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["success"])

    def test_invalid_reference_image_data_returns_400(self):
        response = self.client.post("/design/find_similar", json={
            "reference_image_url": "data:image/png;base64,not-valid-base64-data!!!",
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["success"])

    def test_path_traversal_in_uploaded_reference_url_is_rejected(self):
        response = self.client.post("/design/find_similar", json={
            "reference_image_url": "/static/../../../../etc/passwd",
            "source": "uploaded",
        })
        self.assertEqual(response.status_code, 400)
        self.assertFalse(response.get_json()["success"])

    def test_index_not_built_yet_returns_503(self):
        missing_dir = os.path.join(self._cache_tmpdir.name, "does_not_exist_yet")
        with patch.multiple(
            "services.image_similarity.production_indexer",
            PRODUCTION_NPZ_PATH=os.path.join(missing_dir, "production_index.npz"),
            PRODUCTION_META_PATH=os.path.join(missing_dir, "production_index_meta.json"),
        ):
            response = self.client.post("/design/find_similar", json=self._reference_body())

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.get_json()["success"])

    def test_valid_response_ranks_production_candidates(self):
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([
            ("real_prop_1", "real_prop_1/a.jpg", l2_normalize([1.0, 0.0])),
            ("real_prop_2", "real_prop_2/a.jpg", l2_normalize([0.0, 1.0])),
        ])
        self.property_service.documents["real_prop_1"] = make_property_doc("real_prop_1", images=["a.jpg"])
        self.property_service.documents["real_prop_2"] = make_property_doc("real_prop_2", images=["a.jpg"])

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        with self._production_paths_patch(), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body())

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["source"], "mongodb_production")
        self.assertEqual(data["results"][0]["property_id"], "real_prop_1")

    def test_result_contains_property_id_best_image_and_score(self):
        """TESTS list: 'similarity result contains property ID, best
        image and score' - the retrieval layer's own minimal contract,
        unchanged, still present alongside the new enrichment fields."""
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([("real_prop_1", "real_prop_1/a.jpg", l2_normalize([1.0, 0.0]))])
        self.property_service.documents["real_prop_1"] = make_property_doc("real_prop_1", images=["a.jpg"])

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        with self._production_paths_patch(), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body())

        top = response.get_json()["results"][0]
        self.assertEqual(top["property_id"], "real_prop_1")
        self.assertEqual(top["best_image"], "real_prop_1/a.jpg")
        self.assertAlmostEqual(top["score"], 1.0, places=5)

    def test_enrichment_adds_property_summary_fields_reusing_existing_serializer(self):
        """TESTS list: 'property data enrichment works'. Reuses
        routes/search_routes.py's REAL _serialize_property() - not a
        second, hand-written property-summary implementation."""
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([("real_prop_1", "real_prop_1/cover.jpg", l2_normalize([1.0, 0.0]))])
        self.property_service.documents["real_prop_1"] = make_property_doc(
            "real_prop_1",
            images=["cover.jpg"],
            listing={"type": "rent", "status": "active", "price": 25000, "title": "2BHK Flat"},
            property={"type": "apartment", "bhk": 2, "area_sqft": 950},
            location={"city": "Chennai", "locality": "Velachery"},
            building={"furnishing": "fully_furnished"},
        )

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        with self._production_paths_patch(), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body())

        top = response.get_json()["results"][0]
        self.assertEqual(top["property_type"], "apartment")
        self.assertEqual(top["listing_type"], "rent")
        self.assertEqual(top["price"], 25000)
        self.assertEqual(top["bhk"], 2)
        self.assertEqual(top["area"], 950)
        self.assertEqual(top["city"], "Chennai")
        self.assertEqual(top["locality"], "Velachery")
        self.assertEqual(top["furnishing"], "fully_furnished")
        self.assertEqual(top["image_url"], "/static/images/properties/cover.jpg")

    def test_detail_url_points_to_the_existing_property_details_route(self):
        """TESTS list: 'correct existing property-details URL is
        generated' + 'clicking/navigating to a result opens the
        correct existing property'. Confirms both the URL SHAPE and
        that following it actually reaches a real, working route (the
        stub here mirrors the real property.property_details endpoint
        registered by routes/property_routes.py; that real route's own
        behavior is covered separately in test_property_routes.py)."""
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([("real_prop_1", "real_prop_1/a.jpg", l2_normalize([1.0, 0.0]))])
        self.property_service.documents["real_prop_1"] = make_property_doc("real_prop_1", images=["a.jpg"])

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        with self._production_paths_patch(), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body())

        detail_url = response.get_json()["results"][0]["detail_url"]
        self.assertEqual(detail_url, "/property/real_prop_1")

        navigate_response = self.client.get(detail_url)
        self.assertEqual(navigate_response.status_code, 200)
        self.assertIn("real_prop_1", navigate_response.get_data(as_text=True))

    def test_missing_property_is_dropped_from_results_gracefully(self):
        """TESTS list: 'missing/deleted property is handled
        gracefully'. real_prop_1 was deleted after being indexed - its
        document is simply absent from property_service; real_prop_2
        still exists and must still come back normally."""
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([
            ("real_prop_1", "real_prop_1/a.jpg", l2_normalize([1.0, 0.0])),
            ("real_prop_2", "real_prop_2/a.jpg", l2_normalize([0.9, 0.1])),
        ])
        # Only real_prop_2 has a document - real_prop_1 is "deleted".
        self.property_service.documents["real_prop_2"] = make_property_doc("real_prop_2", images=["a.jpg"])

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        with self._production_paths_patch(), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body())

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        property_ids = [r["property_id"] for r in data["results"]]
        self.assertNotIn("real_prop_1", property_ids)
        self.assertIn("real_prop_2", property_ids)

    def test_unlisted_inactive_property_is_excluded_from_results(self):
        """An unlisted property (routes/property_routes.py's
        delete_listing() sets listing.status="inactive") must never
        appear in Find Similar Homes, even though its embedding is
        still sitting in the production cache untouched - status is
        checked fresh on every request rather than deleting the
        embedding, so relisting makes it eligible again immediately
        with no re-embedding needed."""
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([
            ("real_prop_1", "real_prop_1/a.jpg", l2_normalize([1.0, 0.0])),
            ("real_prop_2", "real_prop_2/a.jpg", l2_normalize([0.9, 0.1])),
        ])
        self.property_service.documents["real_prop_1"] = make_property_doc(
            "real_prop_1", images=["a.jpg"],
            listing={"type": "sell", "status": "inactive", "price": 5000000, "title": "Unlisted"},
        )
        self.property_service.documents["real_prop_2"] = make_property_doc("real_prop_2", images=["a.jpg"])

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        with self._production_paths_patch(), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body())

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        property_ids = [r["property_id"] for r in data["results"]]
        self.assertNotIn("real_prop_1", property_ids)
        self.assertIn("real_prop_2", property_ids)

    def test_missing_image_file_results_in_null_image_url_not_an_error(self):
        """TESTS list: 'missing image is handled gracefully'. The
        indexed best_image filename is no longer in the property's
        current media.images (e.g. removed from the listing since it
        was embedded) - the card must still render, just without a
        broken image."""
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([("real_prop_1", "real_prop_1/deleted_photo.jpg", l2_normalize([1.0, 0.0]))])
        self.property_service.documents["real_prop_1"] = make_property_doc("real_prop_1", images=["some_other_photo.jpg"])

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        with self._production_paths_patch(), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body())

        self.assertEqual(response.status_code, 200)
        top = response.get_json()["results"][0]
        self.assertEqual(top["property_id"], "real_prop_1")
        self.assertIsNone(top["image_url"])

    def test_empty_candidate_index_returns_empty_results_not_an_error(self):
        self._save_fake_cache([])

        class FakeEncoder:
            def encode_image(self, image):
                return [1.0, 0.0]

        with self._production_paths_patch(), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body())

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["results"], [])

    def test_encoder_failure_returns_503_not_a_crash(self):
        self._save_fake_cache([("real_prop_1", "real_prop_1/a.jpg", [1.0, 0.0])])

        class FailingEncoder:
            def encode_image(self, image):
                raise RuntimeError("model exploded")

        with self._production_paths_patch(), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FailingEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body())

        self.assertEqual(response.status_code, 503)
        self.assertFalse(response.get_json()["success"])

    def test_never_exposes_raw_embeddings_or_model_internals(self):
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([("real_prop_1", "real_prop_1/a.jpg", l2_normalize([1.0, 0.0]))])
        self.property_service.documents["real_prop_1"] = make_property_doc("real_prop_1", images=["a.jpg"])

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        with self._production_paths_patch(), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body())

        body_text = response.get_data(as_text=True)
        self.assertNotIn("embedding", body_text.lower())

    def test_smoke_test_records_never_leak_into_production_results(self):
        """Step 10: even if a cache file somehow contained BOTH
        source="mongodb_production" and source="mongodb_smoke_test"
        records (should never happen given they're separate files, but
        this proves the route's defensive filter_by_source() actually
        works), only the production-tagged property must ever be
        returned."""
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([
            ("real_prop_1", "real_prop_1/a.jpg", l2_normalize([1.0, 0.0]), "mongodb_production"),
            ("smoke_prop_1", "smoke_prop_1/a.jpg", l2_normalize([1.0, 0.0]), "mongodb_smoke_test"),
        ])
        self.property_service.documents["real_prop_1"] = make_property_doc("real_prop_1", images=["a.jpg"])

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        with self._production_paths_patch(), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body())

        data = response.get_json()
        property_ids = [r["property_id"] for r in data["results"]]
        self.assertIn("real_prop_1", property_ids)
        self.assertNotIn("smoke_prop_1", property_ids)

    def test_route_no_longer_503s_when_model_returns_a_model_output_not_a_bare_tensor(self):
        """Regression test for the real bug found when this endpoint
        was first exercised against the actual SigLIP2 model: on the
        installed transformers version, get_image_features() returns a
        BaseModelOutputWithPooling (dict-like), not a bare tensor -
        the old code's `features[0]` silently grabbed last_hidden_state
        (3-D, per-patch tokens) instead of the pooled embedding, and
        L2-normalizing that doubly-nested list crashed with "can't
        multiply sequence by non-int of type 'list'", surfaced to the
        client as a 503 ("Similarity search is currently unavailable.").

        This test wires a REAL SiglipEncoder (not a fully-fake
        encode_image()) to a fake torch model reproducing that exact
        ModelOutput shape, so it exercises the actual fixed extraction
        logic in services/image_similarity/siglip2_encoder.py, not
        just the route/retrieval plumbing around it."""

        import torch

        from services.image_similarity.siglip2_encoder import SiglipEncoder

        self._save_fake_cache([("real_prop_1", "real_prop_1/a.jpg", [1.0, 0.0, 0.0, 0.0])])
        self.property_service.documents["real_prop_1"] = make_property_doc("real_prop_1", images=["a.jpg"])

        class FakeProcessor:
            def __call__(self, images, return_tensors="pt"):
                return {"pixel_values": torch.zeros(1, 3, 4, 4)}

        class FakeModelOutputWithPooler:
            def __init__(self, last_hidden_state, pooler_output):
                self.last_hidden_state = last_hidden_state
                self.pooler_output = pooler_output

            def __getitem__(self, index):
                return (self.last_hidden_state, self.pooler_output)[index]

        class FakeModel:
            def get_image_features(self, **inputs):
                return FakeModelOutputWithPooler(
                    last_hidden_state=torch.zeros(1, 5, 4),
                    pooler_output=torch.tensor([[1.0, 0.0, 0.0, 0.0]]),
                )

        real_encoder = SiglipEncoder()
        real_encoder._model = FakeModel()
        real_encoder._processor = FakeProcessor()
        real_encoder._device = "cpu"

        with self._production_paths_patch(), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=real_encoder):
            response = self.client.post("/design/find_similar", json=self._reference_body())

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["results"][0]["property_id"], "real_prop_1")

    def test_multiple_images_per_property_aggregate_to_max_score(self):
        """Step 12: property-level MAX aggregation must still hold
        against the production index, exactly as it already does for
        the benchmark/smoke test - no new scoring formula."""
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([
            ("real_prop_1", "real_prop_1/a.jpg", l2_normalize([0.2, 1.0])),   # weaker match
            ("real_prop_1", "real_prop_1/b.jpg", l2_normalize([1.0, 0.0])),   # exact match
            ("real_prop_2", "real_prop_2/a.jpg", l2_normalize([0.5, 0.5])),
        ])
        self.property_service.documents["real_prop_1"] = make_property_doc("real_prop_1", images=["a.jpg", "b.jpg"])
        self.property_service.documents["real_prop_2"] = make_property_doc("real_prop_2", images=["a.jpg"])

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        with self._production_paths_patch(), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body())

        data = response.get_json()
        top = data["results"][0]
        self.assertEqual(top["property_id"], "real_prop_1")
        self.assertEqual(top["best_image"], "real_prop_1/b.jpg")
        self.assertAlmostEqual(top["score"], 1.0, places=5)


class CombinedNlpImageSearchTests(unittest.TestCase):
    """COMBINED NLP + IMAGE SEARCH (Version A) - Mode 3: TEXT + IMAGE,
    via the optional "query" field on POST /design/find_similar.

    search_orchestration.orchestrate_search() is mocked at its
    definition (not reimplemented) - its own correctness (NLP parsing,
    MongoDB filter construction) is already covered by
    test_search_orchestration.py; this class tests ONLY the new
    integration point: design_routes.py's find_similar() must (a) call
    orchestrate_search() with the user's raw query text, (b) restrict
    the production embedding cache to exactly the candidate property
    IDs orchestrate_search() returned BEFORE any similarity ranking
    runs, and (c) never invoke SigLIP2 at all when there are zero
    candidates. Reuses FindSimilarRouteTests' exact fixtures (same
    make_test_app/FakePropertyService/_save_fake_cache/
    _production_paths_patch helpers) via inheritance so every existing
    image-only guarantee (production-source isolation, active-only,
    MAX-per-property) is exercised identically here."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.property_service = FakePropertyService()
        self.app = make_test_app(self._tmpdir.name, property_service=self.property_service)
        self.client = logged_in_client(self.app)
        self._cache_tmpdir = tempfile.TemporaryDirectory()
        self._npz_path = os.path.join(self._cache_tmpdir.name, "production_index.npz")
        self._meta_path = os.path.join(self._cache_tmpdir.name, "production_index_meta.json")

    def tearDown(self):
        self._tmpdir.cleanup()
        self._cache_tmpdir.cleanup()

    def _production_paths_patch(self):
        return patch.multiple(
            "services.image_similarity.production_indexer",
            PRODUCTION_NPZ_PATH=self._npz_path,
            PRODUCTION_META_PATH=self._meta_path,
        )

    def _save_fake_cache(self, records, source="mongodb_production"):
        from services.image_similarity.embedding_cache import EmbeddingCache

        cache = EmbeddingCache()
        for record in records:
            if len(record) == 4:
                property_id, image_id, embedding, record_source = record
            else:
                property_id, image_id, embedding = record
                record_source = source
            cache.add(property_id, image_id, f"/fake/{image_id}", "fake-model", embedding, source=record_source)

        cache.save(self._npz_path, self._meta_path)

    def _reference_body(self, query=None, source="generated"):
        png_b64 = base64.b64encode(_real_png_bytes()).decode("ascii")
        body = {"reference_image_url": f"data:image/png;base64,{png_b64}", "source": source}
        if query is not None:
            body["query"] = query
        return body

    def _orchestration_result(self, property_docs, applied_filters=None):
        """Builds a scripted return value matching
        search_orchestration.orchestrate_search()'s REAL shape exactly
        - see that function's own docstring for the contract."""
        return {
            "parsed_query": {},
            "location_resolution": None,
            "applied_filters": applied_filters or {},
            "properties": property_docs,
            "nearby_facility_enrichment_caveat": None,
        }

    def _patch_orchestration(self, property_docs, applied_filters=None):
        return patch(
            "services.search_orchestration.orchestrate_search",
            return_value=self._orchestration_result(property_docs, applied_filters),
        )

    def test_query_is_passed_to_orchestrate_search_unchanged(self):
        self._save_fake_cache([])

        with self._patch_orchestration([]) as mock_orchestrate:
            self.client.post("/design/find_similar", json=self._reference_body(
                query="2 BHK semi furnished apartment near VIT Chennai under 30000 with a gym"
            ))

        self.assertEqual(mock_orchestrate.call_args.args[0],
                          "2 BHK semi furnished apartment near VIT Chennai under 30000 with a gym")

    def test_candidates_restrict_ranking_unqualified_property_never_appears(self):
        """Core Version A guarantee: a property with a HIGHER raw image
        score that does NOT satisfy the hard text requirements must
        never outrank (or even appear alongside) a qualifying one."""
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([
            ("qualifies", "qualifies/a.jpg", l2_normalize([0.9, 0.1])),
            ("does_not_qualify", "does_not_qualify/a.jpg", l2_normalize([1.0, 0.0])),  # closer match, but NOT a candidate
        ])
        self.property_service.documents["qualifies"] = make_property_doc("qualifies", images=["a.jpg"])
        self.property_service.documents["does_not_qualify"] = make_property_doc("does_not_qualify", images=["a.jpg"])

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        # orchestrate_search() only returns the ONE property that
        # actually satisfies the (mocked) hard filters.
        with self._production_paths_patch(), self._patch_orchestration(
            [self.property_service.documents["qualifies"]]
        ), patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body(query="2 BHK"))

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        property_ids = [r["property_id"] for r in data["results"]]
        self.assertEqual(property_ids, ["qualifies"])
        self.assertNotIn("does_not_qualify", property_ids)

    def test_zero_candidates_returns_empty_without_invoking_siglip2(self):
        """Step 12.A: zero NLP candidates - never rank unrelated
        properties as a fallback, and never pay for model loading."""
        self._save_fake_cache([("some_prop", "some_prop/a.jpg", [1.0, 0.0])])
        self.property_service.documents["some_prop"] = make_property_doc("some_prop", images=["a.jpg"])

        with self._production_paths_patch(), self._patch_orchestration([]), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder") as mock_get_encoder:
            response = self.client.post("/design/find_similar", json=self._reference_body(query="5 BHK villa in Antarctica"))

        self.assertEqual(response.status_code, 200)
        data = response.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["results"], [])
        self.assertEqual(data["candidate_count"], 0)
        self.assertIsNotNone(data["message"])
        mock_get_encoder.assert_not_called()

    def test_candidates_exist_but_none_have_embedded_images_shows_message(self):
        """Step 12.B: candidates exist but have no usable similarity
        images yet (e.g. embedding still queued) - distinct message
        from the zero-candidates case, NOT a silent empty result."""
        self._save_fake_cache([])  # production cache has nothing at all
        self.property_service.documents["no_photos_yet"] = make_property_doc("no_photos_yet", images=[])

        class FakeEncoder:
            def encode_image(self, image):
                return [1.0, 0.0]

        with self._production_paths_patch(), \
             self._patch_orchestration([self.property_service.documents["no_photos_yet"]]), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body(query="2 BHK"))

        data = response.get_json()
        self.assertEqual(data["results"], [])
        self.assertEqual(data["candidate_count"], 1)
        self.assertIn("none currently have indexed photos", data["message"])

    def test_max_per_property_aggregation_preserved_with_candidate_restriction(self):
        """Step 7: candidate restriction must not change the existing
        MAX-per-property aggregation behavior."""
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([
            ("candidate_a", "candidate_a/weak.jpg", l2_normalize([0.2, 1.0])),
            ("candidate_a", "candidate_a/strong.jpg", l2_normalize([1.0, 0.0])),
            ("candidate_b", "candidate_b/a.jpg", l2_normalize([0.5, 0.5])),
            ("not_a_candidate", "not_a_candidate/a.jpg", l2_normalize([1.0, 0.0])),
        ])
        for pid, imgs in [("candidate_a", ["weak.jpg", "strong.jpg"]), ("candidate_b", ["a.jpg"]), ("not_a_candidate", ["a.jpg"])]:
            self.property_service.documents[pid] = make_property_doc(pid, images=imgs)

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        candidates = [self.property_service.documents["candidate_a"], self.property_service.documents["candidate_b"]]
        with self._production_paths_patch(), self._patch_orchestration(candidates), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body(query="apartment"))

        data = response.get_json()
        property_ids = [r["property_id"] for r in data["results"]]
        self.assertEqual(set(property_ids), {"candidate_a", "candidate_b"})
        top = data["results"][0]
        self.assertEqual(top["property_id"], "candidate_a")
        self.assertEqual(top["best_image"], "candidate_a/strong.jpg")
        self.assertAlmostEqual(top["score"], 1.0, places=5)

    def test_production_source_used_smoke_test_excluded_in_combined_search(self):
        """Step 8: combined search must use source="mongodb_production"
        only, exactly like image-only search."""
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([
            ("candidate_a", "candidate_a/a.jpg", l2_normalize([1.0, 0.0]), "mongodb_production"),
            ("candidate_a", "candidate_a/smoke.jpg", l2_normalize([1.0, 0.0]), "mongodb_smoke_test"),
        ])
        self.property_service.documents["candidate_a"] = make_property_doc("candidate_a", images=["a.jpg"])

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        with self._production_paths_patch(), \
             self._patch_orchestration([self.property_service.documents["candidate_a"]]), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body(query="apartment"))

        data = response.get_json()
        self.assertEqual(data["source"], "mongodb_production")
        self.assertEqual(data["results"][0]["best_image"], "candidate_a/a.jpg")

    def test_deleted_candidate_property_is_dropped_gracefully(self):
        """A candidate ID returned by orchestrate_search() whose
        document has since been deleted must not crash the request -
        _enrich_similarity_results() already drops it (existing
        behavior, unchanged); this proves it still applies under
        candidate restriction."""
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([
            ("ghost_property", "ghost_property/a.jpg", l2_normalize([1.0, 0.0])),
        ])
        # Deliberately NOT added to self.property_service.documents -
        # simulates a property deleted after being indexed, but
        # orchestrate_search() is mocked to still "return" its stale doc
        # shape (as a real Mongo query snapshot might, in a race).
        ghost_doc = make_property_doc("ghost_property", images=["a.jpg"])

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        with self._production_paths_patch(), self._patch_orchestration([ghost_doc]), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body(query="apartment"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["results"], [])

    def test_invalid_reference_image_with_query_still_returns_400_before_nlp_runs(self):
        with self._patch_orchestration([]) as mock_orchestrate:
            response = self.client.post("/design/find_similar", json={
                "reference_image_url": "data:image/png;base64,not-valid-base64!!!",
                "query": "2 BHK apartment",
            })

        self.assertEqual(response.status_code, 400)
        mock_orchestrate.assert_not_called()

    def test_empty_query_string_preserves_existing_image_only_behavior(self):
        """Regression lock: an empty/absent "query" must be byte-for-byte
        the original image-only response shape - candidate_count,
        applied_filters, location_resolution, query_used are all None,
        and orchestrate_search() is never called."""
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([("real_prop_1", "real_prop_1/a.jpg", l2_normalize([1.0, 0.0]))])
        self.property_service.documents["real_prop_1"] = make_property_doc("real_prop_1", images=["a.jpg"])

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        with self._production_paths_patch(), \
             patch("services.search_orchestration.orchestrate_search") as mock_orchestrate, \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body(query=""))

        data = response.get_json()
        self.assertEqual(data["results"][0]["property_id"], "real_prop_1")
        self.assertIsNone(data["candidate_count"])
        self.assertIsNone(data["applied_filters"])
        self.assertIsNone(data["location_resolution"])
        self.assertIsNone(data["query_used"])
        mock_orchestrate.assert_not_called()

    def test_unlisted_candidate_cannot_appear_even_if_orchestration_mock_misbehaves(self):
        """Defense in depth (Step 9): even though orchestrate_search()
        itself already guarantees "listing.status": "active" in every
        real query it builds, _enrich_similarity_results() independently
        re-checks status too - so an inactive property can never
        appear, even if a candidate list were ever produced incorrectly."""
        from services.image_similarity.similarity import l2_normalize

        self._save_fake_cache([("unlisted_prop", "unlisted_prop/a.jpg", l2_normalize([1.0, 0.0]))])
        self.property_service.documents["unlisted_prop"] = make_property_doc(
            "unlisted_prop", images=["a.jpg"],
            listing={"type": "sell", "status": "inactive", "price": 1000000, "title": "Unlisted"},
        )

        class FakeEncoder:
            def encode_image(self, image):
                return l2_normalize([1.0, 0.0])

        with self._production_paths_patch(), \
             self._patch_orchestration([self.property_service.documents["unlisted_prop"]]), \
             patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=FakeEncoder()):
            response = self.client.post("/design/find_similar", json=self._reference_body(query="apartment"))

        self.assertEqual(response.get_json()["results"], [])


class ProductionEmbeddingIndexerTests(unittest.TestCase):
    """Unit tests for services/image_similarity/production_indexer.py
    (Steps 3-9 of the production integration). No real SigLIP2 model or
    MongoDB - the encoder is a fake object, and images are tiny real
    PNG files on disk (so encoder.encode_image(path) receives a real,
    openable path exactly like production code would)."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self._static_root = self._tmpdir.name
        self._images_dir = os.path.join(self._static_root, "images", "properties")
        os.makedirs(self._images_dir, exist_ok=True)
        self._cache_dir = tempfile.TemporaryDirectory()
        self._npz_path = os.path.join(self._cache_dir.name, "idx.npz")
        self._meta_path = os.path.join(self._cache_dir.name, "idx_meta.json")

    def tearDown(self):
        self._tmpdir.cleanup()
        self._cache_dir.cleanup()

    def _write_fake_image(self, filename):
        path = os.path.join(self._images_dir, filename)
        with open(path, "wb") as f:
            f.write(_real_png_bytes())
        return path

    def test_multiple_images_for_one_property_are_all_embedded(self):
        from services.image_similarity.production_indexer import embed_property_images

        self._write_fake_image("a.jpg")
        self._write_fake_image("b.jpg")

        class FakeEncoder:
            model_id = "fake-model"

            def encode_image(self, path):
                return [1.0, 0.0, 0.0, 0.0]

        report = embed_property_images(
            "prop_1", ["a.jpg", "b.jpg"], self._static_root,
            npz_path=self._npz_path, meta_path=self._meta_path, encoder=FakeEncoder(),
        )

        self.assertEqual(report["n_images"], 2)
        self.assertEqual(report["n_embedded"], 2)
        self.assertEqual(report["n_failed"], 0)
        self.assertEqual(report["embedding_dim"], 4)

        from services.image_similarity.embedding_cache import EmbeddingCache
        cache = EmbeddingCache.load(self._npz_path, self._meta_path)
        self.assertEqual(len(cache), 2)
        self.assertTrue(all(r["source"] == "mongodb_production" for r in cache))
        self.assertTrue(all(r["property_id"] == "prop_1" for r in cache))

    def test_one_image_failing_does_not_stop_the_others(self):
        from services.image_similarity.production_indexer import embed_property_images

        self._write_fake_image("good.jpg")
        self._write_fake_image("bad.jpg")

        class PartiallyFailingEncoder:
            model_id = "fake-model"

            def encode_image(self, path):
                if "bad" in path:
                    raise ValueError("corrupted image")
                return [1.0, 0.0, 0.0, 0.0]

        report = embed_property_images(
            "prop_1", ["good.jpg", "bad.jpg"], self._static_root,
            npz_path=self._npz_path, meta_path=self._meta_path, encoder=PartiallyFailingEncoder(),
        )

        self.assertEqual(report["n_embedded"], 1)
        self.assertEqual(report["n_failed"], 1)
        self.assertEqual(report["failures"][0]["image_id"], "prop_1/bad.jpg")

        from services.image_similarity.embedding_cache import EmbeddingCache
        cache = EmbeddingCache.load(self._npz_path, self._meta_path)
        self.assertEqual(len(cache), 1)
        self.assertEqual(cache.records[0]["image_id"], "prop_1/good.jpg")

    def test_already_current_embedding_is_reused_not_recomputed(self):
        from services.image_similarity.production_indexer import embed_property_images

        self._write_fake_image("a.jpg")

        class FakeEncoder:
            model_id = "fake-model"

            def __init__(self):
                self.calls = 0

            def encode_image(self, path):
                self.calls += 1
                return [1.0, 0.0, 0.0, 0.0]

        encoder = FakeEncoder()
        embed_property_images(
            "prop_1", ["a.jpg"], self._static_root,
            npz_path=self._npz_path, meta_path=self._meta_path, encoder=encoder,
        )
        self.assertEqual(encoder.calls, 1)

        # Re-run with the SAME model_id - must be a no-op (reused), not
        # a second encode call.
        report = embed_property_images(
            "prop_1", ["a.jpg"], self._static_root,
            npz_path=self._npz_path, meta_path=self._meta_path, encoder=encoder,
        )
        self.assertEqual(encoder.calls, 1)  # still 1 - not re-encoded
        self.assertEqual(report["n_reused"], 1)
        self.assertEqual(report["n_embedded"], 0)

    def test_model_id_change_triggers_re_embedding(self):
        from services.image_similarity.production_indexer import embed_property_images

        self._write_fake_image("a.jpg")

        class FakeEncoderV1:
            model_id = "fake-model-v1"

            def encode_image(self, path):
                return [1.0, 0.0, 0.0, 0.0]

        class FakeEncoderV2:
            model_id = "fake-model-v2"

            def encode_image(self, path):
                return [0.0, 1.0, 0.0, 0.0]

        embed_property_images(
            "prop_1", ["a.jpg"], self._static_root,
            npz_path=self._npz_path, meta_path=self._meta_path, encoder=FakeEncoderV1(),
        )
        report = embed_property_images(
            "prop_1", ["a.jpg"], self._static_root,
            npz_path=self._npz_path, meta_path=self._meta_path, encoder=FakeEncoderV2(),
        )

        self.assertEqual(report["n_embedded"], 1)
        self.assertEqual(report["n_reused"], 0)

        from services.image_similarity.embedding_cache import EmbeddingCache
        cache = EmbeddingCache.load(self._npz_path, self._meta_path)
        self.assertEqual(len(cache), 1)  # replaced, not duplicated
        self.assertEqual(cache.records[0]["model_id"], "fake-model-v2")

    def test_no_images_is_a_safe_no_op(self):
        from services.image_similarity.production_indexer import embed_property_images

        report = embed_property_images(
            "prop_1", [], self._static_root,
            npz_path=self._npz_path, meta_path=self._meta_path, encoder=None,
        )

        self.assertEqual(report["n_images"], 0)
        self.assertEqual(report["n_embedded"], 0)
        self.assertFalse(os.path.isfile(self._npz_path))  # never even opened the cache

    def test_start_background_embedding_returns_immediately_and_does_not_block(self):
        """Step 1/7: registration must not wait for SigLIP2. This
        verifies the call returns without waiting for a slow encoder to
        finish, and that the work still completes shortly after (on
        the background thread)."""
        import time

        from services.image_similarity.production_indexer import start_background_embedding, embed_property_images

        self._write_fake_image("a.jpg")

        class SlowEncoder:
            model_id = "fake-model"

            def encode_image(self, path):
                time.sleep(0.3)
                return [1.0, 0.0, 0.0, 0.0]

        # Patch get_default_encoder (embed_property_images' default
        # when no encoder is passed) so the background thread picks up
        # the slow fake without a real model ever loading.
        with patch("services.image_similarity.siglip2_encoder.get_default_encoder", return_value=SlowEncoder()):
            started_at = time.perf_counter()
            thread = start_background_embedding(
                "prop_1", ["a.jpg"], self._static_root,
                npz_path=self._npz_path, meta_path=self._meta_path,
            )
            elapsed = time.perf_counter() - started_at

            self.assertIsNotNone(thread)
            self.assertLess(elapsed, 0.2)  # returned well before the encoder's 0.3s sleep

            thread.join(timeout=2)

        from services.image_similarity.embedding_cache import EmbeddingCache
        cache = EmbeddingCache.load(self._npz_path, self._meta_path)
        self.assertEqual(len(cache), 1)

    def test_property_with_no_images_starts_no_thread(self):
        from services.image_similarity.production_indexer import start_background_embedding

        thread = start_background_embedding("prop_1", [], self._static_root)
        self.assertIsNone(thread)


if __name__ == "__main__":
    unittest.main()
