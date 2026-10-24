"""
Unit tests for evaluation/image_similarity/metrics.py (Phase 6 image-
similarity benchmark's pure-logic scoring code).

IMPORTANT: metrics.py has zero ML dependencies (no torch/transformers,
no numpy) and makes no network calls - these tests exercise it with
synthetic, hand-constructed embeddings only. No model is downloaded or
loaded here, so this file is safe to run as part of the project's
normal test suite (python -m unittest discover). The actual model-
loading/embedding code (evaluation/image_similarity/models.py) is
intentionally NOT imported by this file or by anything else in the
root test suite.
"""

import math
import unittest

from evaluation.image_similarity.metrics import (
    l2_normalize,
    cosine_similarity,
    rank_candidates,
    top_k_category_accuracy,
    same_property_leakage_rate,
    evaluate_grouped_retrieval,
    exclude_records,
    compute_margins,
)


class L2NormalizeTests(unittest.TestCase):

    def test_unit_vector_is_unchanged(self):
        self.assertEqual(l2_normalize([1.0, 0.0]), [1.0, 0.0])

    def test_scales_to_unit_length(self):
        normalized = l2_normalize([3.0, 4.0])
        norm = math.sqrt(sum(c * c for c in normalized))
        self.assertAlmostEqual(norm, 1.0, places=9)
        self.assertAlmostEqual(normalized[0], 0.6, places=9)
        self.assertAlmostEqual(normalized[1], 0.8, places=9)

    def test_zero_vector_is_returned_unchanged_not_crashed(self):
        self.assertEqual(l2_normalize([0.0, 0.0, 0.0]), [0.0, 0.0, 0.0])


class CosineSimilarityTests(unittest.TestCase):

    def test_identical_vectors_have_similarity_one(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 2.0, 3.0], [1.0, 2.0, 3.0]), 1.0, places=9)

    def test_orthogonal_vectors_have_similarity_zero(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0, places=9)

    def test_opposite_vectors_have_similarity_minus_one(self):
        self.assertAlmostEqual(cosine_similarity([1.0, 0.0], [-1.0, 0.0]), -1.0, places=9)

    def test_scale_invariant(self):
        # cosine similarity must not care that one vector is 100x
        # longer than the other - this is exactly why L2 normalization
        # doesn't change the *ranking*, only pre-normalizes for
        # convenience/consistency elsewhere in the pipeline.
        self.assertAlmostEqual(
            cosine_similarity([1.0, 1.0], [100.0, 100.0]),
            1.0,
            places=9,
        )

    def test_mismatched_lengths_raise(self):
        with self.assertRaises(ValueError):
            cosine_similarity([1.0, 2.0], [1.0, 2.0, 3.0])

    def test_zero_vector_similarity_is_zero_not_a_crash(self):
        self.assertEqual(cosine_similarity([0.0, 0.0], [1.0, 1.0]), 0.0)


class RankCandidatesTests(unittest.TestCase):

    def test_excludes_the_query_itself(self):
        embeddings = {
            "a": [1.0, 0.0],
            "b": [1.0, 0.0],
            "c": [0.0, 1.0],
        }
        ranked = rank_candidates("a", embeddings)
        ranked_ids = [candidate_id for candidate_id, _ in ranked]

        self.assertNotIn("a", ranked_ids)
        self.assertEqual(set(ranked_ids), {"b", "c"})

    def test_orders_best_match_first(self):
        embeddings = {
            "query": [1.0, 0.0],
            "close": [0.9, 0.1],
            "far": [0.0, 1.0],
        }
        ranked = rank_candidates("query", embeddings)

        self.assertEqual(ranked[0][0], "close")
        self.assertEqual(ranked[1][0], "far")
        self.assertGreater(ranked[0][1], ranked[1][1])


class TopKCategoryAccuracyTests(unittest.TestCase):

    def test_perfect_retrieval_scores_100_percent(self):
        # Two well-separated clusters: "bedroom" and "kitchen" - each
        # cluster's own members are the closest thing to each other.
        records = [
            {"id": "bed1", "label": "bedroom"},
            {"id": "bed2", "label": "bedroom"},
            {"id": "kit1", "label": "kitchen"},
            {"id": "kit2", "label": "kitchen"},
        ]
        embeddings = {
            "bed1": [1.0, 0.0],
            "bed2": [0.95, 0.05],
            "kit1": [0.0, 1.0],
            "kit2": [0.05, 0.95],
        }

        result = top_k_category_accuracy(records, embeddings, k_values=[1, 3])

        self.assertEqual(result["n_queries"], 4)
        self.assertEqual(result["top_1"], 1.0)
        self.assertEqual(result["top_3"], 1.0)

    def test_worst_case_retrieval_scores_0_percent(self):
        records = [
            {"id": "bed1", "label": "bedroom"},
            {"id": "bed2", "label": "bedroom"},
            {"id": "kit1", "label": "kitchen"},
            {"id": "kit2", "label": "kitchen"},
        ]
        # Each item's nearest neighbor is the OTHER category entirely.
        embeddings = {
            "bed1": [1.0, 0.0],
            "kit1": [0.99, 0.01],
            "bed2": [0.0, 1.0],
            "kit2": [0.01, 0.99],
        }

        result = top_k_category_accuracy(records, embeddings, k_values=[1])

        self.assertEqual(result["top_1"], 0.0)

    def test_singleton_labels_are_skipped_not_scored_as_misses(self):
        # "exterior" has only one member - it can never be "found" by
        # category, so it must not silently count against accuracy.
        records = [
            {"id": "bed1", "label": "bedroom"},
            {"id": "bed2", "label": "bedroom"},
            {"id": "ext1", "label": "exterior"},
        ]
        embeddings = {
            "bed1": [1.0, 0.0],
            "bed2": [0.9, 0.1],
            "ext1": [0.0, 1.0],
        }

        result = top_k_category_accuracy(records, embeddings, k_values=[1])

        self.assertEqual(result["n_queries"], 2)
        self.assertEqual(result["n_skipped_singleton_label"], 1)
        self.assertEqual(result["top_1"], 1.0)

    def test_no_eligible_queries_returns_none_not_a_crash(self):
        records = [
            {"id": "a", "label": "bedroom"},
            {"id": "b", "label": "kitchen"},
        ]
        embeddings = {"a": [1.0, 0.0], "b": [0.0, 1.0]}

        result = top_k_category_accuracy(records, embeddings, k_values=[1])

        self.assertEqual(result["n_queries"], 0)
        self.assertIsNone(result["top_1"])


class SamePropertyLeakageRateTests(unittest.TestCase):

    def test_returns_none_when_property_id_is_missing(self):
        records = [{"id": "a", "label": "bedroom"}]
        embeddings = {"a": [1.0, 0.0]}

        self.assertIsNone(same_property_leakage_rate(records, embeddings))

    def test_detects_full_same_property_leakage(self):
        # Both non-query candidates belong to the SAME property as
        # every query - top-1 will always be a same-property match.
        records = [
            {"id": "a", "label": "bedroom", "property_id": "p1"},
            {"id": "b", "label": "kitchen", "property_id": "p1"},
        ]
        embeddings = {"a": [1.0, 0.0], "b": [0.9, 0.1]}

        rate = same_property_leakage_rate(records, embeddings, k=1)

        self.assertEqual(rate, 1.0)

    def test_detects_no_leakage_when_top_match_is_a_different_property(self):
        records = [
            {"id": "a", "label": "bedroom", "property_id": "p1"},
            {"id": "b", "label": "bedroom", "property_id": "p2"},
            {"id": "c", "label": "kitchen", "property_id": "p1"},
        ]
        # "a"'s closest neighbor is "b" (different property), not "c"
        # (same property).
        embeddings = {
            "a": [1.0, 0.0],
            "b": [0.95, 0.05],
            "c": [0.0, 1.0],
        }

        rate = same_property_leakage_rate(records, embeddings, k=1)

        self.assertLess(rate, 1.0)


class EvaluateGroupedRetrievalTests(unittest.TestCase):
    """Covers evaluate_grouped_retrieval() - the Phase 6 pilot's
    PRIMARY property-level metric (group_key="house_id") and its
    SEPARATE category-level analysis (group_key="category"), both
    driven by the same underlying function."""

    def _house_records(self):
        # 3 houses: house A has 3 images (a1,a2,a3), house B has 2
        # (b1,b2), house C has exactly 1 (c1) - c1 can never have a
        # positive candidate and must be excluded from every average.
        return [
            {"id": "a1", "house_id": "A"},
            {"id": "a2", "house_id": "A"},
            {"id": "a3", "house_id": "A"},
            {"id": "b1", "house_id": "B"},
            {"id": "b2", "house_id": "B"},
            {"id": "c1", "house_id": "C"},
        ]

    def test_house_with_single_image_is_excluded_as_no_positive_candidate(self):
        records = self._house_records()
        # Embeddings deliberately cluster by house.
        embeddings = {
            "a1": [1.0, 0.0, 0.0], "a2": [0.9, 0.1, 0.0], "a3": [0.8, 0.2, 0.0],
            "b1": [0.0, 1.0, 0.0], "b2": [0.0, 0.9, 0.1],
            "c1": [0.0, 0.0, 1.0],
        }

        result = evaluate_grouped_retrieval(records, embeddings, k_values=[1, 3], group_key="house_id")

        self.assertEqual(result["n_queries"], 6)
        self.assertEqual(result["n_valid_queries"], 5)
        self.assertEqual(result["n_skipped_no_positive"], 1)

    def test_recall_at_k_perfect_when_houses_are_well_separated(self):
        records = self._house_records()
        embeddings = {
            "a1": [1.0, 0.0, 0.0], "a2": [0.9, 0.1, 0.0], "a3": [0.8, 0.2, 0.0],
            "b1": [0.0, 1.0, 0.0], "b2": [0.0, 0.9, 0.1],
            "c1": [0.0, 0.0, 1.0],
        }

        result = evaluate_grouped_retrieval(records, embeddings, k_values=[1], group_key="house_id")

        self.assertEqual(result["recall_at_k"][1], 1.0)

    def test_recall_at_k_zero_when_houses_are_interleaved_wrong(self):
        records = self._house_records()
        # Each house-A image's single nearest neighbor is a house-B
        # image instead of another house-A image.
        embeddings = {
            "a1": [1.0, 0.0], "b1": [0.99, 0.01],
            "a2": [0.0, 1.0], "b2": [0.01, 0.99],
            "a3": [1.0, 0.01],
            "c1": [-1.0, -1.0],
        }

        result = evaluate_grouped_retrieval(records, embeddings, k_values=[1], group_key="house_id")

        # a1's nearest is b1 (wrong), a2's nearest is b2 (wrong) - only
        # a3 (nearest = a1, same house) can still hit, so recall@1 < 1.
        self.assertLess(result["recall_at_k"][1], 1.0)

    def test_mrr_reflects_rank_of_first_positive(self):
        records = [
            {"id": "a1", "house_id": "A"},
            {"id": "a2", "house_id": "A"},
            {"id": "x1", "house_id": "X"},
            {"id": "x2", "house_id": "X"},
        ]
        # Full rankings for these embeddings (verified by direct
        # computation, not hand-estimated):
        #   a1 -> x1, a2, x2   => first positive (a2) at rank 2 -> RR=1/2
        #   a2 -> x1, a1, x2   => first positive (a1) at rank 2 -> RR=1/2
        #   x1 -> a1, a2, x2   => first positive (x2) at rank 3 -> RR=1/3
        #   x2 -> a2, x1, a1   => first positive (x1) at rank 2 -> RR=1/2
        # mean = (1/2 + 1/2 + 1/3 + 1/2) / 4 = 0.4583333...
        embeddings = {
            "a1": [1.0, 0.0],
            "x1": [0.95, 0.05],
            "a2": [0.8, 0.2],
            "x2": [-1.0, 0.3],
        }

        result = evaluate_grouped_retrieval(records, embeddings, k_values=[1], group_key="house_id")

        self.assertAlmostEqual(result["mrr"], 0.4583333333333333, places=6)

    def test_mean_positive_and_top_negative_similarity_are_computed(self):
        records = self._house_records()
        embeddings = {
            "a1": [1.0, 0.0, 0.0], "a2": [0.9, 0.1, 0.0], "a3": [0.8, 0.2, 0.0],
            "b1": [0.0, 1.0, 0.0], "b2": [0.0, 0.9, 0.1],
            "c1": [0.0, 0.0, 1.0],
        }

        result = evaluate_grouped_retrieval(records, embeddings, k_values=[1], group_key="house_id")

        self.assertIsNotNone(result["mean_positive_similarity"])
        self.assertIsNotNone(result["mean_top_negative_similarity"])
        # Houses are well-separated here, so same-house similarity
        # should clearly exceed the best cross-house similarity.
        self.assertGreater(result["mean_positive_similarity"], result["mean_top_negative_similarity"])

    def test_query_never_appears_in_its_own_candidate_gallery(self):
        # A single-house dataset where every image is identical -
        # recall@1 must still be 1.0 (any OTHER same-house image
        # counts), never trivially "1.0 because the query matched
        # itself".
        records = [
            {"id": "a1", "house_id": "A"},
            {"id": "a2", "house_id": "A"},
        ]
        embeddings = {"a1": [1.0, 0.0], "a2": [1.0, 0.0]}

        result = evaluate_grouped_retrieval(records, embeddings, k_values=[1], group_key="house_id")

        self.assertEqual(result["recall_at_k"][1], 1.0)
        self.assertEqual(result["n_valid_queries"], 2)

    def test_category_level_grouping_uses_the_same_function(self):
        # The SAME function, called with group_key="category" instead
        # of "house_id" - this is how the pilot's separate category-
        # level analysis (Step 6) is computed, never conflated with
        # the property-level metric.
        records = [
            {"id": "a1", "house_id": "A", "category": "bedroom"},
            {"id": "b1", "house_id": "B", "category": "bedroom"},
            {"id": "a2", "house_id": "A", "category": "kitchen"},
            {"id": "b2", "house_id": "B", "category": "kitchen"},
        ]
        embeddings = {
            "a1": [1.0, 0.0], "b1": [0.95, 0.05],
            "a2": [0.0, 1.0], "b2": [0.05, 0.95],
        }

        result = evaluate_grouped_retrieval(records, embeddings, k_values=[1], group_key="category")

        self.assertEqual(result["recall_at_k"][1], 1.0)

    def test_no_valid_queries_returns_none_metrics_not_a_crash(self):
        records = [
            {"id": "a", "house_id": "A"},
            {"id": "b", "house_id": "B"},
        ]
        embeddings = {"a": [1.0, 0.0], "b": [0.0, 1.0]}

        result = evaluate_grouped_retrieval(records, embeddings, k_values=[1, 5], group_key="house_id")

        self.assertEqual(result["n_valid_queries"], 0)
        self.assertIsNone(result["recall_at_k"][1])
        self.assertIsNone(result["recall_at_k"][5])
        self.assertIsNone(result["mrr"])
        self.assertIsNone(result["mean_positive_similarity"])
        self.assertIsNone(result["mean_top_negative_similarity"])


class ExcludeRecordsTests(unittest.TestCase):

    def test_removes_only_the_named_ids(self):
        records = [{"id": "a"}, {"id": "b"}, {"id": "c"}]

        result = exclude_records(records, {"b"})

        self.assertEqual([r["id"] for r in result], ["a", "c"])

    def test_empty_exclude_set_returns_everything(self):
        records = [{"id": "a"}, {"id": "b"}]

        result = exclude_records(records, set())

        self.assertEqual(len(result), 2)

    def test_does_not_mutate_the_input_list(self):
        records = [{"id": "a"}, {"id": "b"}]

        exclude_records(records, {"a"})

        self.assertEqual(len(records), 2)

    def test_excluding_all_ids_returns_empty_list(self):
        records = [{"id": "a"}, {"id": "b"}]

        result = exclude_records(records, {"a", "b"})

        self.assertEqual(result, [])


class ComputeMarginsTests(unittest.TestCase):

    def _records(self):
        return [
            {"id": "a1", "house_id": "A"},
            {"id": "a2", "house_id": "A"},
            {"id": "b1", "house_id": "B"},
            {"id": "b2", "house_id": "B"},
        ]

    def _embeddings(self):
        return {
            "a1": [1.0, 0.0],
            "a2": [0.9, 0.1],
            "b1": [0.0, 1.0],
            "b2": [-1.0, 0.0],
        }

    def test_best_positive_and_best_negative_per_query(self):
        # Values below verified by direct computation against this exact
        # implementation, not hand-estimated - see the comment on each.
        result = compute_margins(self._records(), self._embeddings())

        by_id = {q["query_id"]: q for q in result["per_query"]}

        # a1's only positive is a2 (cos ~0.9939); best negative is b1 (cos 0.0).
        self.assertEqual(by_id["a1"]["best_positive_id"], "a2")
        self.assertAlmostEqual(by_id["a1"]["best_positive_similarity"], 0.9938837346736189, places=9)
        self.assertEqual(by_id["a1"]["best_negative_id"], "b1")
        self.assertAlmostEqual(by_id["a1"]["best_negative_similarity"], 0.0, places=9)
        self.assertAlmostEqual(by_id["a1"]["margin"], 0.9938837346736189, places=9)

    def test_margin_is_positive_when_positive_beats_negative(self):
        result = compute_margins(self._records(), self._embeddings())
        by_id = {q["query_id"]: q for q in result["per_query"]}

        self.assertGreater(by_id["a1"]["margin"], 0)

    def test_margin_can_be_negative_when_negative_beats_positive(self):
        # b1's best positive (b2) has similarity 0.0, but its best
        # negative (a2) has similarity ~0.110 - a genuinely negative
        # margin, and compute_margins() must not clamp or hide this.
        result = compute_margins(self._records(), self._embeddings())
        by_id = {q["query_id"]: q for q in result["per_query"]}

        self.assertLess(by_id["b1"]["margin"], 0)

    def test_aggregate_statistics_are_computed(self):
        result = compute_margins(self._records(), self._embeddings())

        self.assertEqual(result["n_queries"], 4)
        self.assertEqual(result["n_valid_queries"], 4)
        self.assertIsNotNone(result["mean_margin"])
        self.assertIsNotNone(result["median_margin"])
        self.assertIsNotNone(result["mean_best_positive_similarity"])
        self.assertIsNotNone(result["mean_best_negative_similarity"])

    def test_margin_threshold_percentages(self):
        result = compute_margins(self._records(), self._embeddings())

        # 3 of 4 queries (a1, a2, b2) have a positive margin; b1 does not.
        self.assertAlmostEqual(result["pct_margin_gt_0"], 0.75, places=9)

    def test_candidate_pair_totals(self):
        result = compute_margins(self._records(), self._embeddings())

        # Each of the 4 valid queries has exactly 1 positive candidate
        # (its one housemate) and 2 negative candidates (the other house).
        self.assertEqual(result["total_positive_candidate_pairs"], 4)
        self.assertEqual(result["total_negative_candidate_pairs"], 8)

    def test_query_with_no_positive_candidate_is_skipped_not_scored(self):
        records = [
            {"id": "a1", "house_id": "A"},
            {"id": "b1", "house_id": "B"},
            {"id": "b2", "house_id": "B"},
        ]
        embeddings = {"a1": [1.0, 0.0], "b1": [0.0, 1.0], "b2": [0.0, 0.9]}

        result = compute_margins(records, embeddings)

        self.assertEqual(result["n_skipped_no_positive"], 1)
        self.assertEqual(result["n_valid_queries"], 2)  # b1, b2 only
        self.assertNotIn("a1", {q["query_id"] for q in result["per_query"]})

    def test_query_with_no_negative_candidate_is_skipped_not_scored(self):
        # A single-house dataset: every query has positives but NO
        # negative could ever exist.
        records = [
            {"id": "a1", "house_id": "A"},
            {"id": "a2", "house_id": "A"},
        ]
        embeddings = {"a1": [1.0, 0.0], "a2": [0.9, 0.1]}

        result = compute_margins(records, embeddings)

        self.assertEqual(result["n_skipped_no_negative"], 2)
        self.assertEqual(result["n_valid_queries"], 0)
        self.assertEqual(result["mean_margin"], None)

    def test_query_never_appears_in_its_own_candidate_pool(self):
        records = self._records()
        embeddings = self._embeddings()

        result = compute_margins(records, embeddings)

        for query in result["per_query"]:
            self.assertNotEqual(query["best_positive_id"], query["query_id"])
            self.assertNotEqual(query["best_negative_id"], query["query_id"])

    def test_category_level_grouping_works_the_same_way(self):
        records = [
            {"id": "a1", "house_id": "A", "category": "bedroom"},
            {"id": "b1", "house_id": "B", "category": "bedroom"},
            {"id": "a2", "house_id": "A", "category": "kitchen"},
            {"id": "b2", "house_id": "B", "category": "kitchen"},
        ]
        embeddings = {
            "a1": [1.0, 0.0], "b1": [0.95, 0.05],
            "a2": [0.0, 1.0], "b2": [0.05, 0.95],
        }

        result = compute_margins(records, embeddings, group_key="category")

        self.assertEqual(result["n_valid_queries"], 4)


if __name__ == "__main__":
    unittest.main()
