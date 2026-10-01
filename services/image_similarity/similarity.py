"""
Pure ranking/aggregation logic for the SigLIP2 property-similarity
service - deliberately dependency-free (stdlib `math` only, no numpy/
torch), matching the isolation convention already used by
evaluation/image_similarity/metrics.py in this same project, so these
functions are directly unit-testable with synthetic data and mocked
encoders, with no model download or heavy dependency required.

The encoder (siglip2_encoder.py) and bulk embedding comparison
(retrieval.py) use numpy where it matters for performance (comparing
one query against many cached candidates) - by the time results reach
this module, everything is already plain Python floats/lists.
"""

import math


class ZeroNormError(ValueError):
    """Raised when attempting to L2-normalize a zero vector - a
    zero-norm embedding is degenerate (e.g. a fully-uniform/corrupted
    input) and must never be silently normalized into NaN/undefined
    values."""


def l2_normalize(vector):
    """Returns a NEW list: `vector` scaled to unit L2 norm. Raises
    ZeroNormError (never silently divides by zero) if the vector's
    norm is exactly zero."""

    norm = math.sqrt(sum(component * component for component in vector))
    if norm == 0.0:
        raise ZeroNormError("cannot L2-normalize a zero vector")
    return [component / norm for component in vector]


def cosine_similarity(a, b):
    """Cosine similarity between two ALREADY L2-NORMALIZED vectors -
    for unit vectors this is exactly the dot product (matching this
    service's own spec: `float(np.dot(query_embedding, candidate_embedding))`).
    Does NOT re-normalize its inputs - callers are expected to have
    already normalized via l2_normalize() first. This keeps the hot
    path (comparing one query against many cached candidates) a plain
    dot product, not a repeated norm computation."""

    if len(a) != len(b):
        raise ValueError(f"cosine_similarity: vectors must be the same length, got {len(a)} and {len(b)}")
    return sum(x * y for x, y in zip(a, b))


def aggregate_property_scores(image_scores):
    """image_scores: an iterable of {"property_id", "image_id", "score"}
    dicts (extra keys are ignored). Aggregates to ONE score per
    property using MAX similarity - see docs/PHASE_6_SIGLIP2_SIMILARITY_SERVICE.md's
    "Why max aggregation" section for the rationale. The highest-
    scoring image's id is kept alongside the score so callers can
    show "which room matched".

    Returns: {property_id: {"score": float, "best_image": image_id}}
    """

    best_by_property = {}
    for entry in image_scores:
        property_id = entry["property_id"]
        score = entry["score"]
        current = best_by_property.get(property_id)
        if current is None or score > current["score"]:
            best_by_property[property_id] = {"score": score, "best_image": entry["image_id"]}
    return best_by_property


def rank_properties(property_scores, top_k=None):
    """property_scores: {property_id: {"score", "best_image"}} - the
    output of aggregate_property_scores(). Returns a list of
    {"property_id", "score", "best_image"} sorted by score DESCENDING,
    truncated to `top_k` if given.

    TIE-BREAKING RULE (deterministic, documented per instructions):
    equal scores are broken by property_id ASCENDING (lexicographic).
    This makes ranking output fully reproducible across runs/platforms/
    dict-ordering, rather than leaving ties to incidental insertion
    order.
    """

    ranked = [
        {"property_id": property_id, "score": info["score"], "best_image": info["best_image"]}
        for property_id, info in property_scores.items()
    ]
    ranked.sort(key=lambda entry: (-entry["score"], entry["property_id"]))
    if top_k is not None:
        ranked = ranked[:top_k]
    return ranked
