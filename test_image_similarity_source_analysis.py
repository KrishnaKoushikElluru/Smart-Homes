"""
Unit tests for evaluation/image_similarity/source_analysis.py's pure
analysis functions (Group A/B assignment, within-group filtering,
cross-group intrusion, source-stratified Recall@K, zero-positive
handling).

Synthetic data only - no dependency on the real properties/ dataset or
retrieval_examples.json, no model download, no network access.
"""

import unittest

from evaluation.image_similarity.source_analysis import (
    house_group,
    diagnose_ambiguity,
    within_group_recall,
    intrusion_rates,
    intrusion_rates_by_query_group,
    source_confounded_failures,
    category_by_group,
)


class HouseGroupTests(unittest.TestCase):

    def test_house_001_through_009_are_group_a(self):
        for n in range(1, 10):
            self.assertEqual(house_group(f"House_{n:03d}"), "A")

    def test_house_010_through_021_are_group_b(self):
        for n in range(10, 22):
            self.assertEqual(house_group(f"House_{n:03d}"), "B")

    def test_boundary_house_009_vs_010(self):
        self.assertEqual(house_group("House_009"), "A")
        self.assertEqual(house_group("House_010"), "B")


def _example(query_id, query_house_id, query_category, top_results):
    return {
        "query_id": query_id,
        "query_house_id": query_house_id,
        "query_category": query_category,
        "top_results": top_results,
    }


def _result(image_id, house_id, category, similarity, correct_property):
    return {
        "image_id": image_id,
        "house_id": house_id,
        "category": category,
        "similarity": similarity,
        "correct_property": correct_property,
    }


class DiagnoseAmbiguityTests(unittest.TestCase):

    def test_positive_found_within_top_k_is_never_ambiguous(self):
        examples = [
            _example("House_001/a.jpg", "House_001", "bedroom", [
                _result("House_001/b.jpg", "House_001", "bedroom", 0.9, True),
                _result("House_010/x.jpg", "House_010", "bedroom", 0.8, False),
            ]),
        ]
        diag = diagnose_ambiguity(examples, k_values=(1, 3))
        self.assertEqual(diag["ambiguous_by_k"][1], 0)
        self.assertEqual(diag["ambiguous_by_k"][3], 0)

    def test_enough_same_group_observed_to_rule_out_is_not_ambiguous(self):
        # 3 same-group items observed, none correct - definitively a
        # miss at K=1, even though we haven't seen the "true" full
        # within-group ranking beyond what's here.
        examples = [
            _example("House_001/a.jpg", "House_001", "bedroom", [
                _result("House_002/x.jpg", "House_002", "bedroom", 0.9, False),
                _result("House_003/y.jpg", "House_003", "bedroom", 0.8, False),
                _result("House_004/z.jpg", "House_004", "bedroom", 0.7, False),
            ]),
        ]
        diag = diagnose_ambiguity(examples, k_values=(1,))
        self.assertEqual(diag["ambiguous_by_k"][1], 0)  # 1 same-group item already rules out K=1

    def test_zero_same_group_observed_and_no_positive_is_ambiguous(self):
        examples = [
            _example("House_001/a.jpg", "House_001", "bedroom", [
                _result("House_010/x.jpg", "House_010", "bedroom", 0.9, False),
                _result("House_011/y.jpg", "House_011", "bedroom", 0.8, False),
            ]),
        ]
        diag = diagnose_ambiguity(examples, k_values=(1,))
        self.assertEqual(diag["ambiguous_by_k"][1], 1)


class WithinGroupRecallTests(unittest.TestCase):

    def test_filters_to_only_the_target_group_queries(self):
        examples = [
            _example("House_001/a.jpg", "House_001", "bedroom", [
                _result("House_002/x.jpg", "House_002", "bedroom", 0.9, False),
            ]),
            _example("House_010/a.jpg", "House_010", "bedroom", [
                _result("House_011/x.jpg", "House_011", "bedroom", 0.9, False),
            ]),
        ]
        result_a = within_group_recall(examples, "A", k_values=(1,))
        result_b = within_group_recall(examples, "B", k_values=(1,))
        self.assertEqual(result_a["n_valid_queries"], 1)
        self.assertEqual(result_b["n_valid_queries"], 1)

    def test_cross_group_candidates_are_excluded_from_within_group_ranking(self):
        # Query is Group A; top result is Group B (wrong group) and
        # correct - within-group filtering must NOT count Group B
        # candidates at all, so the same-house Group A positive
        # (ranked 2nd overall) becomes the TRUE within-group rank 1.
        examples = [
            _example("House_001/query.jpg", "House_001", "bedroom", [
                _result("House_010/other.jpg", "House_010", "bedroom", 0.95, False),
                _result("House_001/positive.jpg", "House_001", "bedroom", 0.90, True),
            ]),
        ]
        result = within_group_recall(examples, "A", k_values=(1,))
        self.assertEqual(result["recall_at_k"][1], 1.0)

    def test_unresolved_queries_are_excluded_from_the_denominator_not_scored_as_misses(self):
        examples = [
            # Zero Group-A candidates observed for this Group-A query -
            # genuinely unresolvable at K=1.
            _example("House_001/a.jpg", "House_001", "bedroom", [
                _result("House_010/x.jpg", "House_010", "bedroom", 0.9, False),
            ]),
        ]
        result = within_group_recall(examples, "A", k_values=(1,))
        self.assertEqual(result["n_unresolved_by_k"][1], 1)
        self.assertIsNone(result["recall_at_k"][1])  # 0/0 -> None, not silently 0.0


class IntrusionRatesTests(unittest.TestCase):

    def test_computes_fraction_of_other_group_in_top_k(self):
        examples = [
            _example("House_001/a.jpg", "House_001", "bedroom", [
                _result("House_001/b.jpg", "House_001", "bedroom", 0.9, True),
                _result("House_010/x.jpg", "House_010", "bedroom", 0.8, False),
                _result("House_002/y.jpg", "House_002", "bedroom", 0.7, False),
                _result("House_011/z.jpg", "House_011", "bedroom", 0.6, False),
            ]),
        ]
        rates = intrusion_rates(examples, k_values=(1, 2, 4))
        self.assertAlmostEqual(rates[1], 0.0)   # top-1 is Group A
        self.assertAlmostEqual(rates[2], 0.5)   # 1 of top-2 is Group B
        self.assertAlmostEqual(rates[4], 0.5)   # 2 of top-4 are Group B

    def test_by_query_group_splits_correctly(self):
        examples = [
            _example("House_001/a.jpg", "House_001", "bedroom", [
                _result("House_010/x.jpg", "House_010", "bedroom", 0.9, False),
            ]),
            _example("House_010/a.jpg", "House_010", "bedroom", [
                _result("House_001/x.jpg", "House_001", "bedroom", 0.9, False),
            ]),
        ]
        result = intrusion_rates_by_query_group(examples, k_values=(1,))
        self.assertAlmostEqual(result["A"][1], 1.0)  # Group A query's only top result is Group B
        self.assertAlmostEqual(result["B"][1], 1.0)  # Group B query's only top result is Group A


class SourceConfoundedFailuresTests(unittest.TestCase):

    def test_classifies_within_group_vs_cross_group_failures(self):
        dataset_summary = {"images_per_house": {"House_001": 2, "House_002": 2, "House_010": 2}}
        examples = [
            # Within-group failure: House_001 query, House_002 wrong result, both Group A.
            _example("House_001/a.jpg", "House_001", "bedroom", [
                _result("House_002/x.jpg", "House_002", "bedroom", 0.9, False),
            ]),
            # Cross-group failure: House_001 query (A), House_010 wrong result (B).
            _example("House_001/b.jpg", "House_001", "kitchen", [
                _result("House_010/y.jpg", "House_010", "kitchen", 0.9, False),
            ]),
        ]
        result = source_confounded_failures(examples, dataset_summary)
        self.assertEqual(result["n_failures"], 2)
        self.assertAlmostEqual(result["pct_within_group"], 0.5)
        self.assertAlmostEqual(result["pct_cross_group"], 0.5)

    def test_zero_positive_house_is_excluded_not_counted_as_a_failure(self):
        dataset_summary = {"images_per_house": {"House_011": 1, "House_001": 2}}
        examples = [
            _example("House_011/only.jpg", "House_011", "bedroom", [
                _result("House_001/x.jpg", "House_001", "bedroom", 0.9, False),
            ]),
        ]
        result = source_confounded_failures(examples, dataset_summary)
        self.assertEqual(result["n_failures"], 0)

    def test_no_failures_returns_a_minimal_dict_not_a_crash(self):
        dataset_summary = {"images_per_house": {"House_001": 2}}
        examples = [
            _example("House_001/a.jpg", "House_001", "bedroom", [
                _result("House_001/b.jpg", "House_001", "bedroom", 0.9, True),
            ]),
        ]
        result = source_confounded_failures(examples, dataset_summary)
        self.assertEqual(result["n_failures"], 0)


class CategoryByGroupTests(unittest.TestCase):

    def test_splits_category_queries_by_group_and_excludes_singleton_houses(self):
        dataset_summary = {"images_per_house": {"House_001": 2, "House_011": 1}}
        examples = [
            _example("House_001/bathroom_01.jpg", "House_001", "bathroom", [
                _result("House_001/bathroom_02.jpg", "House_001", "bathroom", 0.9, True),
            ]),
            _example("House_011/bathroom_01.jpg", "House_011", "bathroom", [
                _result("House_001/bathroom_01.jpg", "House_001", "bathroom", 0.5, False),
            ]),
            _example("House_001/kitchen_01.jpg", "House_001", "kitchen", [
                _result("House_001/kitchen_02.jpg", "House_001", "kitchen", 0.9, True),
            ]),
        ]
        result = category_by_group(examples, "bathroom", dataset_summary, k_values=(1,))
        self.assertEqual(result["A"]["n_queries"], 1)   # House_001's bathroom query
        self.assertEqual(result["B"]["n_queries"], 0)   # House_011 excluded (1 image, no positive)
        self.assertEqual(result["A"]["recall_at_k"][1], 1.0)


if __name__ == "__main__":
    unittest.main()
