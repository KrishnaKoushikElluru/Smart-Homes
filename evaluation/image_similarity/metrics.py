"""
Phase 6 image-similarity benchmark - pure-logic metrics module.

Deliberately dependency-free (stdlib `math` only, no numpy/torch/
transformers, no network access) so this file - and the tests that
exercise it (../../test_image_similarity_metrics.py) - can be imported
and run as part of the project's NORMAL test suite without triggering
any model download or heavy ML dependency. The actual model-loading /
embedding-extraction code that needs torch+transformers lives in
models.py instead and is never imported here or by the root test
suite.

Everything in this file operates on plain Python floats/lists so it is
trivially testable with synthetic, hand-constructed embeddings - no
real model call is required to verify this logic is correct.
"""

import math


def l2_normalize(vector):
    """Returns a new list: `vector` scaled to unit L2 norm. A
    zero-vector is returned unchanged (never divides by zero) - this
    can legitimately happen for a degenerate/all-zero embedding and
    should not crash the benchmark."""

    norm = math.sqrt(sum(component * component for component in vector))

    if norm == 0.0:
        return list(vector)

    return [component / norm for component in vector]


def cosine_similarity(a, b):
    """Cosine similarity between two equal-length vectors. Does NOT
    assume the inputs are already L2-normalized - always divides by
    both norms, so it is safe to call on raw embeddings too (though
    this benchmark always normalizes first, per the task spec)."""

    if len(a) != len(b):
        raise ValueError(
            f"cosine_similarity: vectors must be the same length, got {len(a)} and {len(b)}"
        )

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


def rank_candidates(query_id, embeddings):
    """Ranks every OTHER entry in `embeddings` (a dict of id -> vector)
    by cosine similarity to `embeddings[query_id]`, descending. Always
    excludes the query itself from its own candidate list - this is
    the leave-one-out protocol this benchmark uses throughout (see
    docs/PHASE_6_IMAGE_SIMILARITY_BENCHMARK.md's "Similarity
    calculation" section for why: with only a handful of real images
    available, holding out anything more than the query itself would
    leave too little data to evaluate against).

    Returns a list of (candidate_id, similarity) tuples, best first.
    """

    query_vector = embeddings[query_id]

    scored = [
        (candidate_id, cosine_similarity(query_vector, candidate_vector))
        for candidate_id, candidate_vector in embeddings.items()
        if candidate_id != query_id
    ]

    scored.sort(key=lambda pair: pair[1], reverse=True)

    return scored


def top_k_category_accuracy(records, embeddings, k_values):
    """Leave-one-out Top-K retrieval accuracy, evaluated by CATEGORY
    LABEL: for each record used as a query, count it a "hit" at K if
    any of the top-K ranked candidates (excluding the query itself)
    shares the same `label` as the query.

    `records` is a list of {"id", "label"} dicts (a "property_id" key
    is allowed but ignored here - see same_property_rate() for that).
    `embeddings` maps id -> vector (any length; not required to be
    normalized here, since rank_candidates()/cosine_similarity() above
    normalize internally via the cosine formula).

    Returns {k: accuracy} for each k in `k_values`, plus "n_queries".
    Skips (and reports as skipped) any query whose label has no other
    member in the whole record set at all - such a query can never be
    "hit" by definition, and silently counting it as a miss would
    understate accuracy for reasons that have nothing to do with model
    quality (see docs/PHASE_6_IMAGE_SIMILARITY_BENCHMARK.md's dataset-
    size caveats).
    """

    label_by_id = {record["id"]: record["label"] for record in records}

    label_counts = {}
    for label in label_by_id.values():
        label_counts[label] = label_counts.get(label, 0) + 1

    eligible_ids = [
        record_id for record_id, label in label_by_id.items()
        if label_counts.get(label, 0) > 1
    ]

    hits = {k: 0 for k in k_values}

    for query_id in eligible_ids:
        query_label = label_by_id[query_id]
        ranked = rank_candidates(query_id, embeddings)
        ranked_labels = [label_by_id[candidate_id] for candidate_id, _ in ranked]

        for k in k_values:
            top_k_labels = ranked_labels[:k]
            if query_label in top_k_labels:
                hits[k] += 1

    n_queries = len(eligible_ids)

    result = {
        "n_queries": n_queries,
        "n_skipped_singleton_label": len(label_by_id) - n_queries,
    }

    for k in k_values:
        result[f"top_{k}"] = (hits[k] / n_queries) if n_queries else None

    return result


def evaluate_grouped_retrieval(records, embeddings, k_values, group_key):
    """Leave-one-out retrieval evaluation, grouping "positive" candidates
    by whatever field `group_key` names on each record (e.g. "house_id"
    for the PRIMARY property-level metric this Phase 6 pilot uses, or
    "category" for the SEPARATE, secondary category-level analysis -
    see docs: these two are never the same thing and must not be
    conflated).

    For each query image Q belonging to group G:
        - candidate gallery = every OTHER image (Q itself never appears
          in its own gallery - see rank_candidates())
        - positive candidates = candidates also in group G
        - negative candidates = candidates in any other group

    Definitions (documented explicitly, per the task's own instruction
    to be precise about what Recall@K means here):
        recall_at_k[k] = fraction of valid queries where AT LEAST ONE
            positive candidate appears in the top K ranked candidates.
        mrr = mean, over valid queries, of 1 / (rank of the FIRST
            positive candidate in the full ranking).
        mean_positive_similarity = mean cosine similarity, pooled over
            every (query, positive-candidate) pair across all valid
            queries (not averaged per-query first).
        mean_top_negative_similarity = mean, over valid queries, of the
            similarity of that query's single BEST-RANKED negative
            candidate - a measure of how visually confusable the
            hardest wrong-group candidate is.

    A query is "valid" only if its group has at least one OTHER member
    in the full record set (otherwise no positive candidate could ever
    exist for it, by construction - it is excluded from every average
    below and counted in `n_skipped_no_positive` instead of silently
    scored as a miss, matching top_k_category_accuracy()'s existing
    convention above).
    """

    group_by_id = {record["id"]: record[group_key] for record in records}

    group_counts = {}
    for group in group_by_id.values():
        group_counts[group] = group_counts.get(group, 0) + 1

    valid_ids = [
        record_id for record_id, group in group_by_id.items()
        if group_counts.get(group, 0) > 1
    ]

    hits = {k: 0 for k in k_values}
    reciprocal_ranks = []
    positive_similarities = []
    top_negative_similarities = []

    for query_id in valid_ids:
        query_group = group_by_id[query_id]
        ranked = rank_candidates(query_id, embeddings)

        first_positive_rank = None
        for rank, (candidate_id, _similarity) in enumerate(ranked, start=1):
            if group_by_id[candidate_id] == query_group:
                first_positive_rank = rank
                break
        if first_positive_rank is not None:
            reciprocal_ranks.append(1.0 / first_positive_rank)

        for k in k_values:
            top_k_groups = [group_by_id[candidate_id] for candidate_id, _ in ranked[:k]]
            if query_group in top_k_groups:
                hits[k] += 1

        positive_similarities.extend(
            similarity for candidate_id, similarity in ranked
            if group_by_id[candidate_id] == query_group
        )

        negative_similarities = [
            similarity for candidate_id, similarity in ranked
            if group_by_id[candidate_id] != query_group
        ]
        if negative_similarities:
            top_negative_similarities.append(max(negative_similarities))

    n_valid = len(valid_ids)

    def _mean(values):
        return (sum(values) / len(values)) if values else None

    return {
        "n_queries": len(records),
        "n_valid_queries": n_valid,
        "n_skipped_no_positive": len(records) - n_valid,
        "recall_at_k": {
            k: ((hits[k] / n_valid) if n_valid else None)
            for k in k_values
        },
        "mrr": _mean(reciprocal_ranks),
        "mean_positive_similarity": _mean(positive_similarities),
        "mean_top_negative_similarity": _mean(top_negative_similarities),
    }


def same_property_leakage_rate(records, embeddings, k=1):
    """Diagnostic (NOT an accuracy metric): of each query's top-K
    ranked candidates, what fraction come from the SAME property_id as
    the query? A high rate here would be a red flag that a model is
    keying on property-specific visual traits (lighting, wall color,
    camera used) rather than genuine room-category similarity - the
    "avoid data leakage" concern called out in the task spec. Records
    without a property_id are skipped entirely (returns None) rather
    than silently treated as "no leakage".
    """

    if any("property_id" not in record for record in records):
        return None

    property_by_id = {record["id"]: record["property_id"] for record in records}

    same_property_hits = 0
    total = 0

    for query_id in property_by_id:
        ranked = rank_candidates(query_id, embeddings)
        top_k = ranked[:k]

        if not top_k:
            continue

        total += len(top_k)
        same_property_hits += sum(
            1 for candidate_id, _ in top_k
            if property_by_id[candidate_id] == property_by_id[query_id]
        )

    if total == 0:
        return None

    return same_property_hits / total


def exclude_records(records, exclude_ids):
    """Pure filter: returns a new list of records with any record whose
    "id" is in `exclude_ids` removed. Never mutates `records` or touches
    disk - used for evaluation-time exclusion (e.g. Part A's duplicate-
    sensitivity RUN B), never for actually deleting/renaming an image on
    disk, which this benchmark's dataset must never do."""

    exclude_ids = set(exclude_ids)
    return [record for record in records if record["id"] not in exclude_ids]


def compute_margins(records, embeddings, group_key="house_id"):
    """For every query image, finds its single BEST (highest-similarity)
    positive candidate and single BEST negative candidate, and the
    margin between them (best_positive - best_negative). Positive =
    same `group_key` value as the query; negative = different value;
    the query itself is always excluded from its own candidate pool
    (via rank_candidates()).

    A query is skipped (not scored, not silently counted as a 0-margin
    miss) if it has no positive candidates OR no negative candidates
    at all - both are real edge cases (a group with only 1 member; a
    dataset with only 1 group) this function must not crash on or
    misreport.

    Returns:
        {
            "n_queries": total records,
            "n_valid_queries": records with >=1 positive AND >=1 negative,
            "n_skipped_no_positive": ...,
            "n_skipped_no_negative": ...,
            "per_query": [
                {
                    "query_id", "group": <house_id/category value>,
                    "best_positive_id", "best_positive_similarity",
                    "best_negative_id", "best_negative_similarity",
                    "margin",
                    "n_positive_candidates", "n_negative_candidates",
                },
                ...
            ],
            "mean_best_positive_similarity", "mean_best_negative_similarity",
            "mean_margin", "median_margin",
            "pct_margin_gt_0", "pct_margin_ge_0_05", "pct_margin_ge_0_10",
            "total_positive_candidate_pairs", "total_negative_candidate_pairs",
        }

    Every per-query "n_positive_candidates"/"n_negative_candidates" is
    the count for THAT query specifically (varies with house size); the
    two "total_..._candidate_pairs" fields at the top level sum those
    across all valid queries, matching what Part B of the task asks to
    report ("number of positive candidates"/"number of negative
    candidates").
    """

    group_by_id = {record["id"]: record[group_key] for record in records}

    per_query = []
    n_skipped_no_positive = 0
    n_skipped_no_negative = 0

    for record in records:
        query_id = record["id"]
        query_group = group_by_id[query_id]
        ranked = rank_candidates(query_id, embeddings)

        positives = [(cid, sim) for cid, sim in ranked if group_by_id[cid] == query_group]
        negatives = [(cid, sim) for cid, sim in ranked if group_by_id[cid] != query_group]

        if not positives:
            n_skipped_no_positive += 1
            continue
        if not negatives:
            n_skipped_no_negative += 1
            continue

        # `ranked` is already sorted best-first, so the first positive/
        # negative encountered is the best one for each.
        best_positive_id, best_positive_similarity = positives[0]
        best_negative_id, best_negative_similarity = negatives[0]

        per_query.append({
            "query_id": query_id,
            "group": query_group,
            "best_positive_id": best_positive_id,
            "best_positive_similarity": best_positive_similarity,
            "best_negative_id": best_negative_id,
            "best_negative_similarity": best_negative_similarity,
            "margin": best_positive_similarity - best_negative_similarity,
            "n_positive_candidates": len(positives),
            "n_negative_candidates": len(negatives),
        })

    def _mean(values):
        return (sum(values) / len(values)) if values else None

    def _median(values):
        if not values:
            return None
        ordered = sorted(values)
        mid = len(ordered) // 2
        if len(ordered) % 2 == 1:
            return ordered[mid]
        return (ordered[mid - 1] + ordered[mid]) / 2.0

    margins = [q["margin"] for q in per_query]
    n_valid = len(per_query)

    def _pct(predicate):
        return (sum(1 for m in margins if predicate(m)) / n_valid) if n_valid else None

    return {
        "n_queries": len(records),
        "n_valid_queries": n_valid,
        "n_skipped_no_positive": n_skipped_no_positive,
        "n_skipped_no_negative": n_skipped_no_negative,
        "per_query": per_query,
        "mean_best_positive_similarity": _mean([q["best_positive_similarity"] for q in per_query]),
        "mean_best_negative_similarity": _mean([q["best_negative_similarity"] for q in per_query]),
        "mean_margin": _mean(margins),
        "median_margin": _median(margins),
        "pct_margin_gt_0": _pct(lambda m: m > 0),
        "pct_margin_ge_0_05": _pct(lambda m: m >= 0.05),
        "pct_margin_ge_0_10": _pct(lambda m: m >= 0.10),
        "total_positive_candidate_pairs": sum(q["n_positive_candidates"] for q in per_query),
        "total_negative_candidate_pairs": sum(q["n_negative_candidates"] for q in per_query),
    }
