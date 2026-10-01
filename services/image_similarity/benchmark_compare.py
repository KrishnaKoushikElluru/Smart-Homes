"""
Step 13 verification: re-run property-level retrieval on the 21-house
dataset using THIS production-oriented service's embeddings, and
compare against the historical evaluation/image_similarity/ benchmark
result (SigLIP2, Recall@1=0.434, @3=0.590, @5=0.663, @10=0.831,
MRR=0.550).

Computes TWO things from the SAME freshly-built embedding cache, to
separate "did the embeddings change" from "did the evaluation
methodology change":

1. IMAGE-LEVEL metric (identical protocol/code to the historical
   benchmark: evaluation/image_similarity/metrics.evaluate_grouped_retrieval,
   group_key="house_id") - if this matches the historical numbers, the
   embeddings themselves are confirmed consistent with the earlier run.

2. PROPERTY-LEVEL-AGGREGATION metric (this service's actual retrieval
   design: exclude only the query image itself - Step 10's data-
   leakage rule - then MAX-aggregate remaining candidates per
   property, rank properties, check whether the query's own property
   is in the top-K ranked properties) - this is mathematically NOT
   identical to (1) for K>1 (see docs/PHASE_6_SIGLIP2_SIMILARITY_SERVICE.md's
   "Benchmark consistency" section for the worked example and proof of
   why) - any difference here is an EXPECTED methodological difference,
   not a bug, as long as (1) matches the historical numbers.

Does not modify the dataset or the historical benchmark files.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from services.image_similarity.embedding_cache import EmbeddingCache
from services.image_similarity.similarity import aggregate_property_scores, rank_properties

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
K_VALUES = (1, 3, 5, 10)

HISTORICAL_SIGLIP2 = {
    "recall_at_1": 0.434,
    "recall_at_3": 0.590,
    "recall_at_5": 0.663,
    "recall_at_10": 0.831,
    "mrr": 0.550,
}


def load_cache():
    npz_path = os.path.join(CACHE_DIR, "siglip2_index.npz")
    meta_path = os.path.join(CACHE_DIR, "siglip2_index_meta.json")
    return EmbeddingCache.load(npz_path, meta_path)


def image_level_metric(cache):
    """Identical protocol to the historical benchmark - reuses
    evaluation/image_similarity/metrics.py's own function directly, so
    there is exactly one implementation of this well-tested metric in
    the whole project, not a second copy that could silently drift."""

    from evaluation.image_similarity.metrics import evaluate_grouped_retrieval

    records = [{"id": r["image_id"], "house_id": r["property_id"]} for r in cache.records]
    embeddings = {r["image_id"]: r["embedding"] for r in cache.records}

    return evaluate_grouped_retrieval(records, embeddings, list(K_VALUES), group_key="house_id")


def property_level_metric(cache):
    """This service's actual retrieval design: for each query image,
    exclude ONLY that exact image (Step 10), max-aggregate the
    remaining candidates by property, rank properties, and check
    whether the query's own property lands in the top-K. A house with
    only 1 image (House_011) is skipped - after excluding the query
    itself, it would have zero remaining images of its own, so it can
    never be its own positive candidate (same reasoning the historical
    benchmark already uses for the image-level metric)."""

    from services.image_similarity.similarity import cosine_similarity

    records = cache.records
    by_property = {}
    for r in records:
        by_property.setdefault(r["property_id"], []).append(r)

    hits_at_k = {k: 0 for k in K_VALUES}
    reciprocal_ranks = []
    n_queries = len(records)
    n_valid = 0

    for query in records:
        if len(by_property[query["property_id"]]) <= 1:
            continue  # no possible same-property positive after self-exclusion
        n_valid += 1

        image_scores = []
        for candidate in records:
            if candidate["image_id"] == query["image_id"]:
                continue  # Step 10: exclude the exact reference image itself
            score = cosine_similarity(query["embedding"], candidate["embedding"])
            image_scores.append({
                "property_id": candidate["property_id"],
                "image_id": candidate["image_id"],
                "score": score,
            })

        property_scores = aggregate_property_scores(image_scores)
        ranked = rank_properties(property_scores)  # full ranking, not top_k-limited, so MRR/all K are correct

        rank_of_own_property = next(
            (i + 1 for i, entry in enumerate(ranked) if entry["property_id"] == query["property_id"]),
            None,
        )

        if rank_of_own_property is not None:
            reciprocal_ranks.append(1.0 / rank_of_own_property)
            for k in K_VALUES:
                if rank_of_own_property <= k:
                    hits_at_k[k] += 1

    return {
        "n_queries": n_queries,
        "n_valid_queries": n_valid,
        "recall_at_k": {k: (hits_at_k[k] / n_valid if n_valid else None) for k in K_VALUES},
        "mrr": (sum(reciprocal_ranks) / len(reciprocal_ranks)) if reciprocal_ranks else None,
    }


def main():
    cache = load_cache()
    print(f"Loaded {len(cache)} cached embeddings.\n")

    image_result = image_level_metric(cache)
    print("=== Image-level metric (identical protocol to the historical benchmark) ===")
    print(json.dumps({k: v for k, v in image_result.items() if k not in ("recall_at_k",)}, indent=2))
    print("recall_at_k:", image_result["recall_at_k"])
    print("mrr:", image_result["mrr"])

    print("\nComparison against historical SigLIP2 numbers:")
    for k in K_VALUES:
        historical = HISTORICAL_SIGLIP2[f"recall_at_{k}"]
        new = image_result["recall_at_k"][k]
        diff = abs(new - historical) if new is not None else None
        print(f"  Recall@{k}: historical={historical:.3f} new={new:.3f} diff={diff:.4f}")
    print(f"  MRR: historical={HISTORICAL_SIGLIP2['mrr']:.3f} new={image_result['mrr']:.3f} "
          f"diff={abs(image_result['mrr'] - HISTORICAL_SIGLIP2['mrr']):.4f}")

    property_result = property_level_metric(cache)
    print("\n=== Property-level-aggregation metric (this service's actual retrieval design) ===")
    print(json.dumps(property_result, indent=2))

    output = {
        "image_level_metric": image_result,
        "property_level_metric": property_result,
        "historical_siglip2": HISTORICAL_SIGLIP2,
    }
    output_path = os.path.join(CACHE_DIR, "benchmark_comparison.json")
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, default=str)
    print(f"\nFull comparison written to {output_path}")


if __name__ == "__main__":
    main()
