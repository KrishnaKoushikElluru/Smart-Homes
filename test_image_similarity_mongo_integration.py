"""
Unit tests for services/image_similarity/mongo_smoke_index.py (the
MongoDB SMOKE-TEST embedding index builder - see that module's
docstring for why these are pipeline tests, never similarity-quality
or benchmark claims).

IMPORTANT: these tests do NOT connect to a real MongoDB and do NOT
load the real SigLIP2 model.
- MongoDB access is mocked via a fake `property_service` object
  exposing get_all_properties() (matching services.property_services.
  PropertyService's real interface) - no pymongo/network involved.
- The encoder is mocked via a fake object exposing encode_image() and
  the attributes SiglipEncoder normally has (model_id, device,
  embedding_dim, load_seconds) - no torch/transformers import here.
"""

import os
import shutil
import tempfile
import unittest

from PIL import Image

from services.image_similarity.embedding_cache import EmbeddingCache
from services.image_similarity.mongo_smoke_index import (
    find_eligible_property_documents,
    iter_property_images,
    build_mongodb_smoke_index,
)


class FakePropertyService:
    def __init__(self, documents):
        self._documents = documents

    def get_all_properties(self):
        return self._documents


class FakeEncoder:
    """Mimics SiglipEncoder's public surface without torch/transformers."""

    def __init__(self, embedding_by_path=None, fail_for=None):
        self.model_id = "fake/siglip2-test"
        self.device = "cpu"
        self.embedding_dim = 4
        self.load_seconds = 0.01
        self._embedding_by_path = embedding_by_path or {}
        self._fail_for = set(fail_for or [])
        self.encode_calls = []

    def encode_image(self, path):
        self.encode_calls.append(path)
        if path in self._fail_for:
            raise ValueError(f"corrupted image: {path}")
        return self._embedding_by_path.get(path, [1.0, 0.0, 0.0, 0.0])


class FindEligiblePropertyDocumentsTests(unittest.TestCase):

    def test_only_documents_with_images_are_eligible(self):
        documents = [
            {"_id": "p1", "media": {"images": ["a.jpg"]}},
            {"_id": "p2", "media": {"images": []}},
            {"_id": "p3", "media": {}},
            {"_id": "p4"},
        ]
        service = FakePropertyService(documents)

        eligible = find_eligible_property_documents(service)

        self.assertEqual([d["_id"] for d in eligible], ["p1"])


class IterPropertyImagesTests(unittest.TestCase):

    def test_yields_property_id_image_id_and_resolved_path(self):
        documents = [
            {"_id": "p1", "media": {"images": ["a.jpg", "b.jpg"]}},
        ]

        results = list(iter_property_images(documents, "/static/root"))

        self.assertEqual(len(results), 2)
        property_id, image_id, path = results[0]
        self.assertEqual(property_id, "p1")
        self.assertEqual(image_id, "p1/a.jpg")
        self.assertTrue(path.endswith("a.jpg"))
        self.assertIn("properties", path)
        self.assertIn("/static/root", path)


class BuildMongodbSmokeIndexTests(unittest.TestCase):

    def test_every_record_is_tagged_source_mongodb_smoke_test(self):
        documents = [{"_id": "p1", "media": {"images": ["a.jpg"]}}]
        service = FakePropertyService(documents)
        encoder = FakeEncoder()

        cache, report = build_mongodb_smoke_index(service, "/static/root", encoder=encoder)

        self.assertEqual(len(cache), 1)
        self.assertEqual(cache.records[0]["source"], "mongodb_smoke_test")

    def test_report_fields_present(self):
        documents = [{"_id": "p1", "media": {"images": ["a.jpg", "b.jpg"]}}]
        service = FakePropertyService(documents)
        encoder = FakeEncoder()

        _cache, report = build_mongodb_smoke_index(service, "/static/root", encoder=encoder)

        self.assertEqual(report["source"], "mongodb_smoke_test")
        self.assertEqual(report["n_documents_discovered"], 1)
        self.assertEqual(report["n_images_found"], 2)
        self.assertEqual(report["n_images_embedded_this_run"], 2)
        self.assertEqual(report["n_failures"], 0)
        self.assertEqual(report["model"], "fake/siglip2-test")
        self.assertEqual(report["embedding_dim"], 4)

    def test_failed_image_is_reported_not_silently_skipped(self):
        documents = [{"_id": "p1", "media": {"images": ["a.jpg", "corrupt.jpg"]}}]
        service = FakePropertyService(documents)
        # Derive the exact path the SAME way the code under test does,
        # rather than reconstructing it by hand (which risks a path-
        # separator mismatch on Windows vs. os.path.join's own output).
        paths_by_image_id = {
            image_id: path for _pid, image_id, path in iter_property_images(documents, "/static/root")
        }
        encoder = FakeEncoder(fail_for={paths_by_image_id["p1/corrupt.jpg"]})

        cache, report = build_mongodb_smoke_index(service, "/static/root", encoder=encoder)

        self.assertEqual(len(cache), 1)  # only the good image made it into the cache
        self.assertEqual(report["n_failures"], 1)
        self.assertEqual(report["failures"][0]["image_id"], "p1/corrupt.jpg")

    def test_existing_cached_embedding_with_matching_model_id_is_reused(self):
        documents = [{"_id": "p1", "media": {"images": ["a.jpg"]}}]
        service = FakePropertyService(documents)
        encoder = FakeEncoder()

        existing_cache = EmbeddingCache()
        path = os.path.join("/static/root", "images", "properties", "a.jpg")
        existing_cache.add("p1", "p1/a.jpg", path, encoder.model_id, [0.5, 0.5, 0.5, 0.5], source="mongodb_smoke_test")

        cache, report = build_mongodb_smoke_index(service, "/static/root", cache=existing_cache, encoder=encoder)

        self.assertEqual(len(cache), 1)
        self.assertEqual(report["n_images_reused_from_cache"], 1)
        self.assertEqual(report["n_images_embedded_this_run"], 0)
        self.assertEqual(encoder.encode_calls, [])  # never re-encoded
        # the REUSED embedding is preserved, not overwritten
        self.assertEqual(cache.get("p1/a.jpg")["embedding"], [0.5, 0.5, 0.5, 0.5])

    def test_model_id_mismatch_triggers_re_embedding(self):
        documents = [{"_id": "p1", "media": {"images": ["a.jpg"]}}]
        service = FakePropertyService(documents)
        encoder = FakeEncoder()  # model_id = "fake/siglip2-test"

        existing_cache = EmbeddingCache()
        path = os.path.join("/static/root", "images", "properties", "a.jpg")
        existing_cache.add("p1", "p1/a.jpg", path, "an-old-different-model", [0.9, 0.9, 0.9, 0.9], source="mongodb_smoke_test")

        cache, report = build_mongodb_smoke_index(service, "/static/root", cache=existing_cache, encoder=encoder)

        self.assertEqual(len(cache), 1)  # replaced, not duplicated
        self.assertEqual(report["n_images_embedded_this_run"], 1)
        self.assertEqual(report["n_images_reused_from_cache"], 0)
        self.assertEqual(cache.get("p1/a.jpg")["model_id"], encoder.model_id)
        self.assertNotEqual(cache.get("p1/a.jpg")["embedding"], [0.9, 0.9, 0.9, 0.9])


class EmbeddingCacheHelpersTests(unittest.TestCase):
    """Covers the EmbeddingCache additions this integration relies on
    (get/has_current/remove/source) directly."""

    def test_get_returns_none_for_unknown_image(self):
        cache = EmbeddingCache()
        self.assertIsNone(cache.get("nope"))

    def test_has_current_true_only_for_matching_model_id(self):
        cache = EmbeddingCache()
        cache.add("p1", "p1/a.jpg", "/x/a.jpg", "model-v1", [1.0, 0.0], source="mongodb_smoke_test")

        self.assertTrue(cache.has_current("p1/a.jpg", "model-v1"))
        self.assertFalse(cache.has_current("p1/a.jpg", "model-v2"))
        self.assertFalse(cache.has_current("p1/missing.jpg", "model-v1"))

    def test_remove_deletes_only_the_named_record(self):
        cache = EmbeddingCache()
        cache.add("p1", "p1/a.jpg", "/x/a.jpg", "model-v1", [1.0, 0.0])
        cache.add("p1", "p1/b.jpg", "/x/b.jpg", "model-v1", [0.0, 1.0])

        cache.remove("p1/a.jpg")

        self.assertEqual(len(cache), 1)
        self.assertIsNone(cache.get("p1/a.jpg"))
        self.assertIsNotNone(cache.get("p1/b.jpg"))

    def test_source_round_trips_through_save_and_load(self):
        tmpdir = tempfile.mkdtemp()
        try:
            cache = EmbeddingCache()
            cache.add("p1", "p1/a.jpg", "/x/a.jpg", "model-v1", [1.0, 0.0, 0.0], source="mongodb_smoke_test")
            npz_path = os.path.join(tmpdir, "idx.npz")
            meta_path = os.path.join(tmpdir, "idx_meta.json")
            cache.save(npz_path, meta_path)

            loaded = EmbeddingCache.load(npz_path, meta_path)

            self.assertEqual(loaded.records[0]["source"], "mongodb_smoke_test")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


class SelfMatchExclusionMongoScenarioTests(unittest.TestCase):
    """Step 9's exact example: reference = property_123/image_1,
    candidate pool includes that SAME image - must be excluded."""

    def test_exact_reference_image_excluded_when_it_originated_from_mongodb(self):
        from services.image_similarity.retrieval import search_similar_properties
        from services.image_similarity.similarity import l2_normalize

        cache = EmbeddingCache()
        cache.add("property_123", "property_123/image_1", "/x/i1.jpg", "m1", l2_normalize([1.0, 0.0]), source="mongodb_smoke_test")
        cache.add("property_456", "property_456/image_1", "/x/i2.jpg", "m1", l2_normalize([0.9, 0.1]), source="mongodb_smoke_test")

        class ReplayEncoder:
            def encode_image(self, image_id):
                return l2_normalize([1.0, 0.0])

        results = search_similar_properties(
            "property_123/image_1",
            cache,
            encoder=ReplayEncoder(),
            exclude_image_ids={"property_123/image_1"},
        )

        property_ids = [r["property_id"] for r in results]
        self.assertNotIn("property_123", property_ids)
        self.assertEqual(property_ids, ["property_456"])


if __name__ == "__main__":
    unittest.main()
