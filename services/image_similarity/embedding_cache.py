"""
Local/offline embedding cache for the SigLIP2 property-similarity
service.

Associates, for every indexed image: property_id, image identifier/
path, model identifier, the embedding itself, embedding dimension,
created_at, and an optional `source` tag (e.g. "mongodb_smoke_test" -
see mongo_smoke_index.py - vs. the benchmark's own untagged/None
source) - exactly the fields this phase's task spec asked for.

Why local/offline for now: inspection of the production MongoDB
property schema (services/property_services.py, routes/
property_routes.py) found no existing persistence layer for image
embeddings - property documents only have an unused
`search.embedding: None` placeholder field (singular, not per-image).
Per instructions, this phase does not introduce a new production
MongoDB schema; a local cache is the smaller, reversible choice, and
this class is deliberately structured (one `add()` call per image,
one `save()`/`load()` pair) so swapping the storage backend to Mongo
later would only mean rewriting save()/load(), not any caller of this
class.

Storage format: one .npz (numpy's compressed array format) holding the
embedding matrix, plus a parallel JSON sidecar with per-row metadata
(everything except the embedding itself) - row i of the matrix
corresponds to metadata[i].
"""

import json
import os
from datetime import datetime, timezone


class EmbeddingCache:

    def __init__(self):
        self.records = []  # each: property_id, image_id, image_path, model_id, embedding (list[float]), embedding_dim, created_at, source

    def add(self, property_id, image_id, image_path, model_id, embedding, source=None):
        self.records.append({
            "property_id": property_id,
            "image_id": image_id,
            "image_path": image_path,
            "model_id": model_id,
            "embedding": list(embedding),
            "embedding_dim": len(embedding),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source": source,
        })

    def __len__(self):
        return len(self.records)

    def __iter__(self):
        return iter(self.records)

    def get(self, image_id):
        """Returns the record for `image_id`, or None if not cached."""
        for record in self.records:
            if record["image_id"] == image_id:
                return record
        return None

    def has_current(self, image_id, model_id):
        """True if `image_id` is cached AND was embedded with THIS
        model_id - a model_id mismatch (e.g. the encoder's checkpoint
        changed) means the cached entry is stale and must be
        re-embedded, not silently reused."""
        record = self.get(image_id)
        return record is not None and record["model_id"] == model_id

    def remove(self, image_id):
        """Removes any existing record for `image_id` (used before
        re-adding a fresher embedding for the same image - e.g. after
        a model_id mismatch)."""
        self.records = [r for r in self.records if r["image_id"] != image_id]

    def save(self, npz_path, meta_path):
        import numpy as np

        directory = os.path.dirname(npz_path)
        if directory:
            os.makedirs(directory, exist_ok=True)

        if self.records:
            matrix = np.array([record["embedding"] for record in self.records], dtype=np.float32)
        else:
            matrix = np.zeros((0, 0), dtype=np.float32)
        np.savez_compressed(npz_path, embeddings=matrix)

        meta = [{key: value for key, value in record.items() if key != "embedding"} for record in self.records]
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump(meta, f, indent=2)

    @classmethod
    def load(cls, npz_path, meta_path):
        import numpy as np

        cache = cls()
        matrix = np.load(npz_path)["embeddings"]
        with open(meta_path, "r", encoding="utf-8") as f:
            meta = json.load(f)

        for index, record_meta in enumerate(meta):
            cache.records.append({**record_meta, "embedding": matrix[index].tolist()})

        return cache

    def filter_by_source(self, source):
        """Returns a NEW EmbeddingCache containing only records whose
        `source` field exactly matches `source` - defense-in-depth
        isolation between differently-sourced indexes (e.g. ensures a
        mongodb_smoke_test record can never leak into a
        mongodb_production retrieval, even if a cache file were ever
        loaded from the wrong path by mistake)."""

        filtered = EmbeddingCache()
        filtered.records = [dict(record) for record in self.records if record.get("source") == source]
        return filtered

    def filter_by_property_ids(self, property_ids):
        """Returns a NEW EmbeddingCache containing only records whose
        `property_id` is in `property_ids` (any iterable of strings).

        This is the integration point between NLP/MongoDB hard
        filtering and SigLIP2 ranking (see routes/design_routes.py's
        find_similar()): callers restrict the cache to a candidate set
        BEFORE calling retrieval.search_similar_properties(), so the
        similarity matrix multiply only ever runs over candidates that
        already satisfy the user's explicit hard requirements - never
        "rank everything, then filter afterward". Composes with
        filter_by_source() (apply both, in either order) since each
        only ever narrows the record set."""

        allowed = set(property_ids)
        filtered = EmbeddingCache()
        filtered.records = [dict(record) for record in self.records if record.get("property_id") in allowed]
        return filtered

    def as_matrix(self):
        """Returns (numpy float32 matrix [n, dim], list of metadata
        dicts aligned by row - same order, embedding key excluded).
        Used by retrieval.py for the brute-force NumPy comparison step
        (Step 16: 84 embeddings is small enough that a single matrix
        multiply against the query is the whole "index")."""

        import numpy as np

        if not self.records:
            return np.zeros((0, 0), dtype=np.float32), []

        matrix = np.array([record["embedding"] for record in self.records], dtype=np.float32)
        meta = [{key: value for key, value in record.items() if key != "embedding"} for record in self.records]
        return matrix, meta
