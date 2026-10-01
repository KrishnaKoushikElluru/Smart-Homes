"""
search_similar_properties() - the isolated retrieval interface:

    reference image -> SigLIP2 embedding -> L2 normalize
    -> cosine similarity against cached property-image embeddings (NumPy, brute-force)
    -> max aggregation per property
    -> ranked properties

NOT wired into any Flask route or the frontend. Callers (tests,
scripts, a future route) import this module directly - see
docs/PHASE_6_SIGLIP2_SIMILARITY_SERVICE.md's "Production status".
"""

from services.image_similarity.similarity import aggregate_property_scores, rank_properties


def search_similar_properties(
    reference_image,
    cache,
    top_k=10,
    encoder=None,
    exclude_image_ids=None,
    exclude_property_ids=None,
):
    """
    reference_image: a PIL.Image, file path, or raw bytes (see
        siglip2_encoder.SiglipEncoder._load_pil_image for what's accepted).
    cache: an embedding_cache.EmbeddingCache already populated/loaded.
    encoder: an object exposing encode_image(image) -> list[float]
        (normally a siglip2_encoder.SiglipEncoder). Defaults to the
        process-wide singleton (get_default_encoder()) if not given -
        pass a fake/mock here for tests, per this phase's instruction
        to mock the encoder rather than load the real model in unit
        tests.
    exclude_image_ids: iterable of image_id strings to remove from the
        candidate pool - the data-leakage rule (e.g. excluding the
        exact reference image itself when benchmarking retrieval).
    exclude_property_ids: iterable of property_id strings to remove
        ENTIRELY from the candidate pool - for cross-property
        retrieval evaluation; not used by default production calls.

    Returns a list of {"property_id", "score", "best_image"}, sorted
    descending by score, length <= top_k. Tie-breaking: see
    similarity.rank_properties()'s documented rule (property_id
    ascending).
    """

    if encoder is None:
        from services.image_similarity.siglip2_encoder import get_default_encoder
        encoder = get_default_encoder()

    query_embedding = encoder.encode_image(reference_image)

    matrix, meta = cache.as_matrix()
    if len(meta) == 0:
        return []

    import numpy as np
    query_vector = np.asarray(query_embedding, dtype=np.float32)
    # Every row in `matrix` is already L2-normalized at index-build
    # time (SiglipEncoder.encode_image() always returns a normalized
    # vector) - so this matrix-vector product IS the cosine similarity
    # of the query against every cached image in one shot.
    scores = matrix @ query_vector

    exclude_image_ids = set(exclude_image_ids or [])
    exclude_property_ids = set(exclude_property_ids or [])

    image_scores = []
    for row_meta, score in zip(meta, scores.tolist()):
        if row_meta["image_id"] in exclude_image_ids:
            continue
        if row_meta["property_id"] in exclude_property_ids:
            continue
        image_scores.append({
            "property_id": row_meta["property_id"],
            "image_id": row_meta["image_id"],
            "score": float(score),
        })

    property_scores = aggregate_property_scores(image_scores)
    return rank_properties(property_scores, top_k=top_k)
