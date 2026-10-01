"""
Unit tests for services/image_similarity/ (the production-oriented,
isolated SigLIP2 similarity service - separate from
evaluation/image_similarity/, which is research-only).

IMPORTANT: these tests do NOT download or load the real SigLIP2 model.
- similarity.py's tests use only stdlib (no numpy/torch at all).
- siglip2_encoder.py's `_load_pil_image` tests use real Pillow (an
  existing root dependency) but never touch model state.
- retrieval.py's tests use a FAKE encoder object (a plain class with
  an encode_image() method) instead of the real SiglipEncoder - this
  is the "mock the encoder" requirement from this phase's task spec.
  numpy IS required for these (embedding_cache.py/retrieval.py's
  matrix math), but torch/transformers are not imported anywhere in
  this file.
"""

import io
import unittest

from PIL import Image

from services.image_similarity.similarity import (
    l2_normalize,
    cosine_similarity,
    aggregate_property_scores,
    rank_properties,
    ZeroNormError,
)
from services.image_similarity.siglip2_encoder import SiglipEncoder, InvalidImageError
from services.image_similarity.embedding_cache import EmbeddingCache
from services.image_similarity.retrieval import search_similar_properties


class L2NormalizeTests(unittest.TestCase):

    def test_scales_to_unit_length(self):
        normalized = l2_normalize([3.0, 4.0])
        self.assertAlmostEqual(normalized[0], 0.6, places=9)
        self.assertAlmostEqual(normalized[1], 0.8, places=9)

    def test_already_normalized_vector_is_unchanged(self):
        self.assertAlmostEqual(l2_normalize([1.0, 0.0])[0], 1.0, places=9)
        self.assertAlmostEqual(l2_normalize([1.0, 0.0])[1], 0.0, places=9)

    def test_zero_vector_raises_a_clear_error(self):
        with self.assertRaises(ZeroNormError):
            l2_normalize([0.0, 0.0, 0.0])


class CosineSimilarityTests(unittest.TestCase):

    def test_same_vector_is_approximately_one(self):
        v = l2_normalize([1.0, 2.0, 3.0])
        self.assertAlmostEqual(cosine_similarity(v, v), 1.0, places=9)

    def test_orthogonal_vectors_are_approximately_zero(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0, places=9)

    def test_opposite_vectors_are_approximately_minus_one(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [-1.0, 0.0]), -1.0, places=9)

    def test_mismatched_lengths_raise(self):
        with self.assertRaises(ValueError):
            cosine_similarity([1.0, 0.0], [1.0, 0.0, 0.0])


class AggregatePropertyScoresTests(unittest.TestCase):

    def test_matches_the_task_spec_example(self):
        image_scores = [
            {"property_id": "House_A", "image_id": "image1", "score": 0.70},
            {"property_id": "House_A", "image_id": "image2", "score": 0.91},
            {"property_id": "House_B", "image_id": "image1", "score": 0.85},
        ]
        result = aggregate_property_scores(image_scores)

        self.assertEqual(result["House_A"]["score"], 0.91)
        self.assertEqual(result["House_A"]["best_image"], "image2")
        self.assertEqual(result["House_B"]["score"], 0.85)
        self.assertEqual(result["House_B"]["best_image"], "image1")

    def test_single_image_property(self):
        result = aggregate_property_scores([{"property_id": "House_C", "image_id": "only.jpg", "score": 0.5}])
        self.assertEqual(result["House_C"]["score"], 0.5)


class RankPropertiesTests(unittest.TestCase):

    def test_descending_order(self):
        scores = {
            "House_A": {"score": 0.91, "best_image": "a.jpg"},
            "House_B": {"score": 0.85, "best_image": "b.jpg"},
            "House_C": {"score": 0.95, "best_image": "c.jpg"},
        }
        ranked = rank_properties(scores)
        self.assertEqual([r["property_id"] for r in ranked], ["House_C", "House_A", "House_B"])

    def test_top_k_truncates(self):
        scores = {
            "House_A": {"score": 0.9, "best_image": "a.jpg"},
            "House_B": {"score": 0.8, "best_image": "b.jpg"},
            "House_C": {"score": 0.7, "best_image": "c.jpg"},
        }
        ranked = rank_properties(scores, top_k=2)
        self.assertEqual(len(ranked), 2)

    def test_tie_break_is_deterministic_property_id_ascending(self):
        scores = {
            "House_C": {"score": 0.5, "best_image": "c.jpg"},
            "House_A": {"score": 0.5, "best_image": "a.jpg"},
            "House_B": {"score": 0.5, "best_image": "b.jpg"},
        }
        ranked = rank_properties(scores)
        self.assertEqual([r["property_id"] for r in ranked], ["House_A", "House_B", "House_C"])

    def test_repeated_calls_produce_identical_order(self):
        scores = {
            "House_X": {"score": 0.5, "best_image": "x.jpg"},
            "House_Y": {"score": 0.5, "best_image": "y.jpg"},
        }
        first = rank_properties(scores)
        second = rank_properties(scores)
        self.assertEqual(first, second)


class LoadPilImageTests(unittest.TestCase):
    """Tests SiglipEncoder._load_pil_image() directly - pure PIL logic,
    no model/torch involved, so no download or heavy dependency is
    needed for these."""

    def setUp(self):
        self.encoder = SiglipEncoder()

    def _png_bytes(self, mode, size=(8, 8), color=None):
        if color is None:
            color = 128 if mode == "L" else (255, 0, 0) if mode == "RGB" else (255, 0, 0, 128)
        image = Image.new(mode, size, color=color)
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        return buf.getvalue()

    def test_rgb_image_stays_rgb(self):
        result = self.encoder._load_pil_image(self._png_bytes("RGB"))
        self.assertEqual(result.mode, "RGB")

    def test_grayscale_image_converts_to_rgb(self):
        result = self.encoder._load_pil_image(self._png_bytes("L"))
        self.assertEqual(result.mode, "RGB")

    def test_rgba_image_converts_to_rgb(self):
        result = self.encoder._load_pil_image(self._png_bytes("RGBA"))
        self.assertEqual(result.mode, "RGB")

    def test_pil_image_object_is_accepted_directly(self):
        image = Image.new("RGB", (4, 4), color=(0, 255, 0))
        result = self.encoder._load_pil_image(image)
        self.assertEqual(result.mode, "RGB")

    def test_corrupted_bytes_raise_invalid_image_error(self):
        with self.assertRaises(InvalidImageError):
            self.encoder._load_pil_image(b"this is definitely not an image" * 10)

    def test_nonexistent_path_raises_invalid_image_error(self):
        with self.assertRaises(InvalidImageError):
            self.encoder._load_pil_image("/no/such/file/anywhere.png")


class FakeEncoder:
    """A minimal stand-in for SiglipEncoder used to test retrieval.py
    without loading the real model - this IS the "mock the encoder"
    requirement from the task spec."""

    def __init__(self, embedding_by_image_id):
        self._embedding_by_image_id = embedding_by_image_id
        self.calls = []

    def encode_image(self, image):
        # In these tests `image` is just the lookup key (a string),
        # standing in for a real reference image path.
        self.calls.append(image)
        return self._embedding_by_image_id[image]


class SearchSimilarPropertiesTests(unittest.TestCase):

    def _build_cache(self, entries):
        cache = EmbeddingCache()
        for property_id, image_id, embedding in entries:
            cache.add(property_id, image_id, f"/fake/path/{image_id}", "fake-model", l2_normalize(embedding))
        return cache

    def test_multiple_images_per_property_collapse_to_one_result(self):
        cache = self._build_cache([
            ("House_001", "House_001/living_room_01.jpg", [1.0, 0.0]),
            ("House_001", "House_001/bedroom_01.jpg", [0.9, 0.1]),
            ("House_002", "House_002/living_room_01.jpg", [0.0, 1.0]),
        ])
        encoder = FakeEncoder({"query.jpg": l2_normalize([1.0, 0.0])})

        results = search_similar_properties("query.jpg", cache, encoder=encoder)

        property_ids = [r["property_id"] for r in results]
        self.assertEqual(property_ids.count("House_001"), 1)
        self.assertIn("House_002", property_ids)

    def test_ranking_is_descending_by_score(self):
        cache = self._build_cache([
            ("House_001", "House_001/a.jpg", [1.0, 0.0]),
            ("House_002", "House_002/a.jpg", [0.7, 0.3]),
        ])
        encoder = FakeEncoder({"query.jpg": l2_normalize([1.0, 0.0])})

        results = search_similar_properties("query.jpg", cache, encoder=encoder)

        self.assertEqual(results[0]["property_id"], "House_001")
        self.assertGreaterEqual(results[0]["score"], results[1]["score"])

    def test_exact_reference_image_is_excluded_from_candidates(self):
        # The reference image is ITSELF one of the cached candidates
        # (self-match would trivially score ~1.0 and dominate results)
        # - Step 10's data-leakage rule.
        cache = self._build_cache([
            ("House_001", "House_001/living_room_01.jpg", [1.0, 0.0]),
            ("House_002", "House_002/living_room_01.jpg", [0.9, 0.1]),
        ])
        query_vector = l2_normalize([1.0, 0.0])
        encoder = FakeEncoder({"House_001/living_room_01.jpg": query_vector})

        results = search_similar_properties(
            "House_001/living_room_01.jpg",
            cache,
            encoder=encoder,
            exclude_image_ids={"House_001/living_room_01.jpg"},
        )

        property_ids = [r["property_id"] for r in results]
        self.assertNotIn("House_001", property_ids)
        self.assertIn("House_002", property_ids)

    def test_exclude_property_ids_removes_the_whole_property(self):
        cache = self._build_cache([
            ("House_001", "House_001/a.jpg", [1.0, 0.0]),
            ("House_001", "House_001/b.jpg", [0.95, 0.05]),
            ("House_002", "House_002/a.jpg", [0.5, 0.5]),
        ])
        encoder = FakeEncoder({"query.jpg": l2_normalize([1.0, 0.0])})

        results = search_similar_properties(
            "query.jpg", cache, encoder=encoder, exclude_property_ids={"House_001"},
        )

        property_ids = [r["property_id"] for r in results]
        self.assertNotIn("House_001", property_ids)
        self.assertEqual(property_ids, ["House_002"])

    def test_top_k_limits_result_count(self):
        cache = self._build_cache([
            (f"House_{i:03d}", f"House_{i:03d}/a.jpg", [1.0 - i * 0.01, i * 0.01])
            for i in range(5)
        ])
        encoder = FakeEncoder({"query.jpg": l2_normalize([1.0, 0.0])})

        results = search_similar_properties("query.jpg", cache, encoder=encoder, top_k=2)

        self.assertEqual(len(results), 2)

    def test_empty_cache_returns_empty_list_not_a_crash(self):
        cache = EmbeddingCache()
        encoder = FakeEncoder({"query.jpg": [1.0, 0.0]})

        results = search_similar_properties("query.jpg", cache, encoder=encoder)

        self.assertEqual(results, [])

    def test_encoder_encode_image_is_called_exactly_once(self):
        cache = self._build_cache([("House_001", "House_001/a.jpg", [1.0, 0.0])])
        encoder = FakeEncoder({"query.jpg": l2_normalize([1.0, 0.0])})

        search_similar_properties("query.jpg", cache, encoder=encoder)

        self.assertEqual(encoder.calls, ["query.jpg"])


if __name__ == "__main__":
    unittest.main()
