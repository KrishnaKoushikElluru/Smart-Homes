"""
MongoDB SMOKE-TEST embedding index builder.

IMPORTANT - READ BEFORE USING ANYTHING IN THIS FILE:

The images currently stored in the production MongoDB `properties`
collection are random/test images uploaded during earlier development
(confirmed by direct visual inspection in an earlier phase of this
project - see evaluation/image_similarity/dataset.py's module
docstring, which describes the SAME finding for the equivalent
static/images/properties/ test-upload data). They do NOT represent
real houses.

This module exists ONLY to verify the engineering pipeline:

    MongoDB property document -> image file -> PIL/RGB
        -> SigLIP2 embedding -> L2 normalize -> cached, tagged source="mongodb_smoke_test"

It must NEVER be used to:
  - measure or report similarity QUALITY,
  - compute Recall@K / MRR / any benchmark metric,
  - compare against the 21-house/84-image benchmark
    (evaluation/image_similarity/ - completely untouched by this file),
  - claim these images represent real, visually meaningful properties.

Every record this module writes into the cache carries
`source="mongodb_smoke_test"` specifically so nothing downstream can
mistake it for benchmark-quality data - see docs/PHASE_6_SIGLIP2_
MONGODB_INTEGRATION.md for the full A/B/C (benchmark / smoke test /
production readiness) distinction.

REUSE, NOT REIMPLEMENTATION: this module reuses the project's existing
MongoDB access layer (services.property_services.PropertyService,
already connected via services.mongo_service.MongoService at Flask
startup - see app.py) rather than opening its own MongoClient
connection, and reuses services/image_similarity/'s own encoder,
embedding_cache, and similarity modules exactly as already benchmarked
- no second SigLIP2 implementation, no new model.

INCREMENTAL INDEXING: build_mongodb_smoke_index() reuses a cached
embedding for an image only if BOTH the image_id AND the model_id
match what's already cached (EmbeddingCache.has_current()) - a
different model_id (e.g. a future checkpoint change) causes that
image to be re-embedded, never silently served a stale vector.
"""

import os
import sys
import time
from pathlib import Path

# Allows this file to be run directly (python services/image_similarity/
# mongo_smoke_index.py) as well as imported normally as a package
# member - matches the same pattern already used by index_builder.py
# and benchmark_compare.py in this same directory.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from services import media_service


def find_eligible_property_documents(property_service):
    """Returns every property document that has at least one image in
    `media.images` - reuses PropertyService.get_all_properties()
    (the existing Mongo access layer) rather than querying MongoDB
    directly, and filters in Python so no new query method needs to be
    added to PropertyService for this smoke test."""

    documents = property_service.get_all_properties()
    return [doc for doc in documents if doc.get("media", {}).get("images")]


def iter_property_images(documents, static_folder):
    """Yields (property_id, image_id, image_path) for every image
    referenced by `documents`. property_id = the property's MongoDB
    _id, as a string (this phase's dataset uses folder-based
    "House_NNN" ids instead - see services/image_similarity/
    index_builder.py - so string ObjectIds are a DIFFERENT id space,
    never confused with those). image_id = "<property_id>/<filename>",
    matching the "<property>/<file>" convention already used
    elsewhere in this project's similarity code. image_path resolves
    to the actual file under static/images/properties/ (see
    services/media_service.py's IMAGE_DIRECTORY), reusing that
    existing storage convention rather than inventing a new one."""

    images_dir = os.path.join(static_folder, media_service.IMAGE_DIRECTORY)

    for document in documents:
        property_id = str(document["_id"])
        for filename in document["media"]["images"]:
            image_path = os.path.join(images_dir, filename)
            yield property_id, f"{property_id}/{filename}", image_path


def build_mongodb_smoke_index(property_service, static_folder, cache=None, encoder=None):
    """Builds (or incrementally updates, if `cache` is given) a
    MongoDB-sourced embedding cache. Returns (cache, report).

    Every record added here has source="mongodb_smoke_test" - see this
    module's docstring for why that tag matters. Does not modify any
    MongoDB document or any image file - purely reads and embeds.
    """

    from services.image_similarity.embedding_cache import EmbeddingCache
    from services.image_similarity.siglip2_encoder import SiglipEncoder

    cache = cache if cache is not None else EmbeddingCache()
    encoder = encoder or SiglipEncoder()

    documents = find_eligible_property_documents(property_service)
    failures = []
    n_images_found = 0
    n_reused = 0
    n_embedded = 0

    overall_start = time.perf_counter()

    for property_id, image_id, image_path in iter_property_images(documents, static_folder):
        n_images_found += 1

        if cache.has_current(image_id, encoder.model_id):
            n_reused += 1
            continue

        try:
            embedding = encoder.encode_image(image_path)
        except Exception as exc:  # noqa: BLE001 - report per-image, never abort the whole build
            failures.append({"image_id": image_id, "path": image_path, "error": str(exc)})
            continue

        cache.remove(image_id)  # drop any stale (e.g. wrong model_id) entry before re-adding
        cache.add(property_id, image_id, image_path, encoder.model_id, embedding, source="mongodb_smoke_test")
        n_embedded += 1

    total_seconds = time.perf_counter() - overall_start

    report = {
        "source": "mongodb_smoke_test",
        "model": encoder.model_id,
        "device": encoder.device,
        "model_load_seconds": encoder.load_seconds,
        "n_documents_discovered": len(documents),
        "n_images_found": n_images_found,
        "n_images_embedded_this_run": n_embedded,
        "n_images_reused_from_cache": n_reused,
        "n_failures": len(failures),
        "failures": failures,
        "embedding_dim": encoder.embedding_dim,
        "total_seconds": total_seconds,
    }

    return cache, report


def main():
    """Standalone CLI entry point - connects to the REAL MongoDB using
    this project's existing connection convention (MONGO_URI from
    secret.env), builds/updates the smoke-test index, and saves it to
    services/image_similarity/cache/mongodb_smoke_test/. Never run
    automatically - a human runs this explicitly, exactly like
    services/image_similarity/index_builder.py's own CLI."""

    import json

    from dotenv import load_dotenv
    load_dotenv(str(Path(__file__).resolve().parent.parent.parent / "secret.env"))

    from services.mongo_service import MongoService
    from services.property_services import PropertyService
    from services.image_similarity.embedding_cache import EmbeddingCache

    mongo_uri = os.getenv("MONGO_URI")
    if not mongo_uri:
        print("MONGO_URI is not configured (secret.env) - cannot run the MongoDB smoke-test index builder.")
        return

    mongo_service = MongoService(mongo_uri)
    property_service = PropertyService(mongo_service)

    cache_dir = os.path.join(os.path.dirname(__file__), "cache", "mongodb_smoke_test")
    npz_path = os.path.join(cache_dir, "mongodb_smoke_index.npz")
    meta_path = os.path.join(cache_dir, "mongodb_smoke_index_meta.json")

    existing_cache = None
    if os.path.isfile(npz_path) and os.path.isfile(meta_path):
        existing_cache = EmbeddingCache.load(npz_path, meta_path)

    static_folder = os.path.join(os.path.dirname(__file__), "..", "..", "static")

    cache, report = build_mongodb_smoke_index(property_service, static_folder, cache=existing_cache)

    os.makedirs(cache_dir, exist_ok=True)
    cache.save(npz_path, meta_path)

    report_path = os.path.join(cache_dir, "mongodb_smoke_index_report.json")
    with open(report_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, default=str)

    print(json.dumps(report, indent=2, default=str))
    print(f"\nIndex saved to {npz_path} and {meta_path}")
    print(f"Report saved to {report_path}")

    mongo_service.close()


if __name__ == "__main__":
    main()
