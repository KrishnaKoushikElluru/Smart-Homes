"""
Phase 6 (production): background SigLIP2 embedding generation for REAL
registered properties.

    property registered with images (routes/property_routes.py,
    submit_listing() - AFTER media_service.save_images() succeeds)
            |
            v  (returns IMMEDIATELY - see start_background_embedding())
    for each saved image filename:
            |
            v
    services.image_similarity.siglip2_encoder.SiglipEncoder - REUSED,
    the exact same encoder already used by the 21-house benchmark
    (evaluation/image_similarity/) and the MongoDB smoke test
    (mongo_smoke_index.py) - no second SigLIP2 implementation.
            |
            v
    L2-normalized 768-d embedding
            |
            v
    services.image_similarity.embedding_cache.EmbeddingCache, tagged
    source="mongodb_production" - a SEPARATE cache file
    (PRODUCTION_NPZ_PATH / PRODUCTION_META_PATH) from the smoke test's
    (source="mongodb_smoke_test", services/image_similarity/cache/
    mongodb_smoke_test/) - never read together, never merged.

EXECUTION MODEL: mirrors services/nearby_facility_service.py's Stage 1
background pattern exactly - a plain daemon threading.Thread, explicit
dependency injection (property_id/image_filenames/static_folder are
passed in as plain arguments while a real Flask request context still
exists; the thread itself never touches current_app/request/g), never
blocks property registration, never lets an uncaught exception escape
the background thread. No Celery/Redis/task-queue dependency - Python
stdlib threading only, matching this project's existing scope.

WHY A PROCESS-WIDE LOCK, NOT MONGODB'S ATOMICITY: unlike
nearby_facility_service (which persists directly to MongoDB - atomic
per-document), this reuses embedding_cache.py's existing local
.npz/.json file abstraction (Phase 6's own established choice - no new
MongoDB schema for embeddings; see embedding_cache.py's docstring for
why). Two properties registered concurrently would otherwise race on
load-modify-save of the SAME cache file. _CACHE_LOCK serializes that
whole critical section within this process. This is not a throughput
loss beyond what already exists: SiglipEncoder itself already holds
its own lock around every encode_image() call, so real inference work
across properties was already fully serialized process-wide - holding
_CACHE_LOCK for the same duration adds no new bottleneck, just extends
one existing serialization point to also cover the cache read/write.
Sufficient for this project's current single-process deployment
(matches every other concurrency assumption already made throughout
this phase); a future multi-process deployment would need to swap the
cache backend, not the caller-facing API of this module.
"""

from __future__ import annotations

import os
import threading
from typing import Optional

PRODUCTION_SOURCE = "mongodb_production"

PRODUCTION_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "cache", "mongodb_production",
)
PRODUCTION_NPZ_PATH = os.path.join(PRODUCTION_CACHE_DIR, "production_index.npz")
PRODUCTION_META_PATH = os.path.join(PRODUCTION_CACHE_DIR, "production_index_meta.json")

_CACHE_LOCK = threading.Lock()


def _load_or_create_cache(npz_path, meta_path):
    from services.image_similarity.embedding_cache import EmbeddingCache

    if os.path.isfile(npz_path) and os.path.isfile(meta_path):
        return EmbeddingCache.load(npz_path, meta_path)
    return EmbeddingCache()


def embed_property_images(
    property_id,
    image_filenames,
    static_folder,
    npz_path: Optional[str] = None,
    meta_path: Optional[str] = None,
    encoder=None,
):
    """
    Synchronous core: embeds every filename in `image_filenames`
    (as already saved by media_service.save_images() for this
    property), tags each record source="mongodb_production", and
    persists into the production EmbeddingCache at (npz_path,
    meta_path) - defaults to PRODUCTION_NPZ_PATH/PRODUCTION_META_PATH.
    Safe to call directly (scripts, tests) without the background
    wrapper below.

    DEDUPLICATION (Step 9): reuses embed_property_images image_id =
    "<property_id>/<filename>" - the same convention
    mongo_smoke_index.py already uses. Skips (does not re-encode) any
    image already cached under the CURRENT encoder.model_id
    (EmbeddingCache.has_current()); a model_id change triggers
    re-embedding. Since media_service.save_images() always generates a
    fresh uuid4 filename per upload, a genuinely changed image is
    automatically a new image_id - there is no "same filename, new
    content" case to special-case here.

    NEVER RAISES (Step 8): a per-image failure (corrupt file, decode
    error, encoder error) is recorded in the returned report's
    "failures" list and processing continues with the remaining
    images - one bad image must never lose the rest of a property's
    embeddings, and this function itself never propagates an exception
    to its caller (the background wrapper needs no extra try/except of
    its own for the per-image case; it exists purely as a last-resort
    net for something unrelated crashing, e.g. a corrupt cache file).

    Returns a report dict: {"property_id", "n_images", "n_embedded",
    "n_reused", "n_failed", "failures", "model", "embedding_dim"}.
    """

    from services import media_service
    from services.image_similarity.siglip2_encoder import get_default_encoder

    npz_path = npz_path or PRODUCTION_NPZ_PATH
    meta_path = meta_path or PRODUCTION_META_PATH
    encoder = encoder or get_default_encoder()

    report = {
        "property_id": property_id,
        "n_images": len(image_filenames or []),
        "n_embedded": 0,
        "n_reused": 0,
        "n_failed": 0,
        "failures": [],
        "model": getattr(encoder, "model_id", None),
        "embedding_dim": None,
    }

    if not image_filenames:
        return report

    images_dir = os.path.join(static_folder, media_service.IMAGE_DIRECTORY)

    with _CACHE_LOCK:
        cache = _load_or_create_cache(npz_path, meta_path)

        for filename in image_filenames:
            image_id = f"{property_id}/{filename}"
            image_path = os.path.join(images_dir, filename)

            if cache.has_current(image_id, encoder.model_id):
                report["n_reused"] += 1
                continue

            try:
                embedding = encoder.encode_image(image_path)
            except Exception as exc:  # noqa: BLE001 - report per-image, never abort the batch
                report["n_failed"] += 1
                report["failures"].append({"image_id": image_id, "error": str(exc)})
                continue

            cache.remove(image_id)  # drop any stale (e.g. wrong model_id) entry before re-adding
            cache.add(property_id, image_id, image_path, encoder.model_id, embedding, source=PRODUCTION_SOURCE)
            report["n_embedded"] += 1
            report["embedding_dim"] = len(embedding)

        cache.save(npz_path, meta_path)

    return report


def remove_property_image_embeddings(
    property_id,
    image_filenames,
    npz_path: Optional[str] = None,
    meta_path: Optional[str] = None,
):
    """
    Edit Listing's "remove/replace an existing image" counterpart to
    embed_property_images() above - deletes the production-index
    records for exactly the given filenames of `property_id` (e.g. an
    image the owner removed, or the OLD file of a replaced image),
    leaving every other embedding (this property's remaining images,
    and every other property) completely untouched.

    Synchronous and fast (no model involved, just a cache edit) - the
    caller (routes/property_routes.py's update_listing()) runs this
    directly in the request, not on a background thread, since there
    is no SigLIP2 inference here to keep off the request path - only
    NEW images need the background worker (start_background_embedding()
    below).

    Safe no-op if the production index hasn't been built yet, or if a
    given image was never embedded in the first place (e.g. it failed
    embedding originally, or the index just hasn't caught up yet) -
    removing a non-existent record is not an error.
    """

    from services.image_similarity.embedding_cache import EmbeddingCache

    npz_path = npz_path or PRODUCTION_NPZ_PATH
    meta_path = meta_path or PRODUCTION_META_PATH

    if not image_filenames:
        return

    if not (os.path.isfile(npz_path) and os.path.isfile(meta_path)):
        return

    with _CACHE_LOCK:
        cache = EmbeddingCache.load(npz_path, meta_path)

        for filename in image_filenames:
            cache.remove(f"{property_id}/{filename}")

        cache.save(npz_path, meta_path)


def _run_embedding_in_background(property_id, image_filenames, static_folder, npz_path, meta_path):
    """The actual thread target. embed_property_images() already never
    raises for a per-image failure - this try/except is an intentional
    last-resort safety net for the one execution context where an
    uncaught exception truly has nowhere sane to go: by the time this
    runs, the HTTP request that triggered it has already returned its
    response (see services/nearby_facility_service.py's identical
    reasoning for its own background worker)."""

    try:
        embed_property_images(
            property_id,
            image_filenames,
            static_folder,
            npz_path=npz_path,
            meta_path=meta_path,
        )
    except Exception as exc:
        print(f"Production embedding background worker crashed for property {property_id}: {exc}")


def start_background_embedding(
    property_id,
    image_filenames,
    static_folder,
    npz_path: Optional[str] = None,
    meta_path: Optional[str] = None,
):
    """
    Stage-1-style entry point (mirrors
    services.nearby_facility_service.start_background_enrichment()):
    starts SigLIP2 embedding generation for property_id's images on a
    plain daemon thread and returns IMMEDIATELY - property registration
    (routes/property_routes.py) never waits for SigLIP2 to load or run.

    EXPLICIT DEPENDENCY INJECTION, NOT FLASK CONTEXT: property_id,
    image_filenames, and static_folder are passed in as plain arguments
    while a real Flask request context still exists; the spawned
    thread never reads current_app/request/g, which would not exist by
    the time a background thread actually runs (the request that
    spawned it may already have returned its response).

    A property with no images is a no-op (returns None, no thread
    started) - nothing to embed. Does not raise.
    """

    if not image_filenames:
        return None

    thread = threading.Thread(
        target=_run_embedding_in_background,
        args=(property_id, image_filenames, static_folder, npz_path, meta_path),
        daemon=True,
        name=f"production-embedding-{property_id}",
    )
    thread.start()

    return thread
