# Phase 6 — SigLIP2 ↔ MongoDB Integration (Smoke Test, Not Production Quality)

## A. Benchmark (unchanged, untouched by this phase)

**21 houses / 84 real-estate images** (`properties/House_001`–`House_021`).
Used for quantitative model evaluation — Recall@K, MRR, margin analysis,
source-stratification, all documented under `evaluation/image_similarity/`.
**Nothing in that directory, the dataset, or the historical results was
modified by this phase.**

## B. MongoDB smoke test (this phase)

### Inspection findings

- **MongoDB connection**: `services/mongo_service.py`'s `MongoService`
  (database `smarthomes`), instantiated once at Flask startup (`app.py`) and
  handed to `services/property_services.py`'s `PropertyService`, stored at
  `app.extensions["property_service"]`. This phase reuses `PropertyService`
  directly — no second MongoDB connection was opened.
- **Property schema**: each document has `_id` (a MongoDB `ObjectId`),
  `listing.status`, and `media.images` — a plain list of filenames (no URLs,
  no GridFS, no base64). `media.image_meta` additionally carries
  `{filename, category, is_cover}` per image (see `services/media_service.py`).
- **Image storage**: images are plain files on disk at
  `static/images/properties/<filename>` (`media_service.IMAGE_DIRECTORY`) —
  the same directory the property-registration upload flow
  (`routes/property_routes.py`) already writes to. Not GridFS, not S3, not
  base64-in-document.
- **Property identity**: the MongoDB `ObjectId` string (`str(doc["_id"])`) —
  a **different ID space** from the offline benchmark dataset's folder-based
  `"House_NNN"` identifiers. The two are never confused: this integration's
  `property_id` values are always real ObjectId strings.
- **Existing reference-image flow**: `templates/design.html` +
  `static/design_reference_state.js` already implement Generate/Upload →
  one `referenceImage.url` (either a `data:image/png;base64,...` URI for a
  generated image, or a `/static/images/design_references/<uuid>.<ext>` URL
  for an uploaded one) — both converge on the SAME state before "Find
  Similar Homes" is enabled. Reused as-is; not redesigned.
- **Existing "Find Similar Homes" backend**: **none** — `findSimilarHomes()`
  was a placeholder that only displayed a static "not available yet"
  message. It also referenced an undefined `referenceImage` variable (a
  leftover from an earlier refactor to a `referenceState` object) — a
  latent bug that would have thrown `ReferenceError` the moment the
  placeholder was ever replaced with a real call. **Fixed as part of wiring
  the real endpoint** (this function had to be rewritten regardless).
- The comment already left in the codebase for this TODO named the intended
  route exactly: `/design/find_similar` — reused verbatim rather than
  inventing a different path.

### What was built

```
Reference image (Generate OR Upload — unchanged flow)
      ↓
POST /design/find_similar   (routes/design_routes.py)
      ↓
SigLIP2 embedding (services/image_similarity/siglip2_encoder.py — REUSED, not reimplemented)
      ↓
L2 normalization (same module)
      ↓
MongoDB candidate embeddings (services/image_similarity/embedding_cache.py, source="mongodb_smoke_test")
      ↓
cosine similarity (services/image_similarity/similarity.py — REUSED)
      ↓
MAX aggregation per property (same module, same function as the benchmark)
      ↓
ranked property IDs (services/image_similarity/retrieval.py — REUSED)
```

**No second SigLIP2 implementation, no new scoring formula, no new vision
model.** Every piece under `services/image_similarity/` from the prior
phase (encoder, normalization, cosine similarity, property aggregation,
ranking, tie-break rule) is reused unchanged; this phase only adds the
MongoDB-specific *data source* (`mongo_smoke_index.py`) and the Flask route
that wires it to the existing frontend.

### New files

- `services/image_similarity/mongo_smoke_index.py` — scans MongoDB property
  documents (via the existing `PropertyService`), resolves each image's file
  path (via the existing `media_service.IMAGE_DIRECTORY` convention), embeds
  it with the existing encoder, and stores it in an `EmbeddingCache` with
  **`source="mongodb_smoke_test"`** on every record. Supports incremental
  indexing: an image already cached under the *same* `model_id` is reused,
  not re-embedded (`EmbeddingCache.has_current()`); a different `model_id`
  triggers re-embedding (`EmbeddingCache.remove()` + re-`add()`).
- `routes/design_routes.py`: `POST /design/find_similar` — accepts
  `{reference_image_url, source}` (the existing frontend contract), resolves
  the reference image locally (base64-decode for generated images; a
  path-traversal-guarded static-file read for uploaded ones — this string
  arrives in a POST body and is never trusted blindly), loads the
  **pre-built** MongoDB smoke-test cache (never re-embeds candidates during
  a request), and returns `{"success", "source": "mongodb_smoke_test",
  "results": [{"property_id", "score", "best_image"}, ...]}`. `services.
  image_similarity` is imported **lazily inside the route function** — torch/
  transformers are never loaded at Flask startup or on any other request
  path, only the first time this specific endpoint is actually called.
- `templates/design.html`: `findSimilarHomes()` rewritten to call the real
  endpoint (fixing the undefined-variable bug), with a loading state, error
  handling, and a staleness guard (a mode switch mid-request discards a
  late-arriving result, matching the existing `generateImage()`/
  `uploadReferenceImage()` pattern). Results render in a new
  `#findSimilarResults` container, styled to match the existing
  `templates/rentals.html` results-card visual language — **every** result
  card is prefixed with a `Similarity pipeline test` badge and the response
  triggers an explanatory note, so these are never presented as real houses.

### Data safety (Step 7)

The current MongoDB images are development test uploads, not real
properties (same finding already documented for the equivalent
`static/images/properties/` test data in
`evaluation/image_similarity/dataset.py`). This integration:
- tags every MongoDB-sourced embedding `source="mongodb_smoke_test"`,
- never writes to any MongoDB property document (`mongo_smoke_index.py` only
  *reads* via `PropertyService.get_all_properties()`),
- never modifies, renames, or resizes any image file,
- never mixes these embeddings into the 21-house benchmark's cache or
  results (separate cache directory: `services/image_similarity/cache/
  mongodb_smoke_test/`, vs. the benchmark's own `cache/siglip2_index.*`),
- labels every returned result in the UI with a visible
  "Similarity pipeline test" badge plus an explanatory note.

## C. Production readiness

Real house images have **not yet** been populated into MongoDB. Therefore:

```
Similarity engineering pipeline: integrated
Real-property similarity quality: not yet evaluated in production
```

### Future real-house flow (no architectural rewrite needed)

```
Real property registered (routes/property_routes.py, unchanged)
    ↓
real house images saved to static/images/properties/ (unchanged - services/media_service.py)
    ↓
services/image_similarity/mongo_smoke_index.py's SAME functions
(find_eligible_property_documents / iter_property_images / build_mongodb_smoke_index)
run again — property_id is always the real ObjectId, never hardcoded
    ↓
new embeddings added to the SAME EmbeddingCache abstraction
(tag with source="mongodb_production" instead of "mongodb_smoke_test"
once images are verified real — a one-line change at the call site,
not an architecture change)
    ↓
eligible for /design/find_similar's existing retrieval pipeline, unchanged
```

Nothing in `mongo_smoke_index.py`, `embedding_cache.py`, `retrieval.py`, or
the Flask route hardcodes a property ID, an image filename, or a document
count — every one of them iterates whatever `PropertyService.
get_all_properties()` returns at run time.

### Future image-registration hook (inspected, not wired yet)

The cleanest place for an automatic "embed on upload" hook would be
`routes/property_routes.py`'s property-registration handler, right after
`media_service.save_images()` succeeds (around
`routes/property_routes.py:879` in the current file) — that is the one place
a newly-uploaded image's final filename and property `_id` are both already
known together. **Not wired in this phase**, per instructions: doing so
safely would mean either running SigLIP2 synchronously inside a registration
request (adding multi-second latency to every listing submission) or
introducing a background task queue (new infrastructure this phase
explicitly avoids). The manual `mongo_smoke_index.py` utility plus the
search pipeline is the complete, correct scope for now; automatic embedding
generation on registration is a deliberate, separate future step.

## Security / privacy

No API keys, no external inference APIs, no image bytes ever leave this
machine, no image content or secrets are logged anywhere in this
integration. The `/design/find_similar` response never includes raw
embeddings or other model internals (verified by a dedicated test — see
`test_design_routes.py::FindSimilarRouteTests::
test_never_exposes_raw_embeddings_or_model_internals`).
