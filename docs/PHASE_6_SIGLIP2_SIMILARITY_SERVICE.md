# Phase 6 — SigLIP2 Image-Similarity Service (Isolated, Not Yet In Production)

## Model

`google/siglip2-base-patch16-224`, loaded via `AutoModel` (see
`services/image_similarity/siglip2_encoder.py`'s module docstring for why
`AutoModel` rather than the newer `Siglip2Model` class — this checkpoint's own
`config.json` declares `"model_type": "siglip"`; its fixed-resolution variant
keeps the original SigLIP Conv2d patch-embedding architecture, and forcing
`Siglip2Model` fails with a weight-shape mismatch, verified directly during
an earlier phase of this same project). Pretrained only — no fine-tuning, no
training. Image-only inputs — no text prompts, no zero-shot classification.

## Purpose

Image-image visual similarity for property retrieval: given a reference
image (generated via Gemini→FLUX, or user-uploaded — see
`static/design_reference_state.js`), find visually similar **properties**
from a candidate set, not just visually similar individual room photos.

## Pipeline

```
Reference image
      ↓
SigLIP2 image encoder (get_image_features(), vision tower only)
      ↓
L2 normalized embedding (float32)
      ↓
cosine similarity (dot product of two unit vectors)
      ↓
image-level matches (against every cached candidate image)
      ↓
max aggregation per property
      ↓
ranked properties (deterministic tie-break: property_id ascending)
```

## Why max aggregation

A property/house has multiple room photos (living room, bedroom, kitchen,
...). The reference image most naturally corresponds to ONE room type most
strongly — a bedroom reference should match a property via its bedroom
photo, not get penalized because that property's kitchen photo looks
nothing like a bedroom. `property_score = max(image similarity across all
of that property's images)` is the simplest retrieval baseline that
captures this: a property is "similar" if it has at least one image that
strongly matches the reference, regardless of how many other, less-similar
rooms it also has. This phase deliberately does NOT implement a learned or
weighted multi-image aggregation — max is the documented, minimal baseline
per instructions.

## Architecture

```
services/image_similarity/
    similarity.py          pure ranking/aggregation logic (stdlib only, no numpy/torch)
    siglip2_encoder.py      lazy-loaded, process-cached SigLIP2 encoder (the ONLY file here importing torch/transformers)
    embedding_cache.py       local .npz + JSON embedding cache (property_id, image_id, model_id, embedding, dim, created_at)
    retrieval.py             search_similar_properties() - the isolated retrieval interface
    index_builder.py          offline script: scans properties/, encodes, saves the cache
    benchmark_compare.py      Step 13 verification script (see "Benchmark consistency" below)
    requirements.txt          isolated deps: torch, transformers, numpy
    cache/                    generated artifacts (siglip2_index.npz, siglip2_index_meta.json, index_build_report.json, benchmark_comparison.json)
```

### Isolation

Nothing in `app.py` or any `routes/` module imports `services/image_similarity/`.
`app.py` only imports specific named service modules by name (verified by
inspection — it never does a broad `import services` or auto-discovers
submodules), so the model is **never loaded at Flask startup or on any
existing request path**. Loading only happens the first time
`encode_image()`/`encode_images()` is actually called, from a script or test
that explicitly imports this module.

### Dependencies

`torch`, `transformers`, `numpy` are declared in
`services/image_similarity/requirements.txt` — **deliberately NOT added to
the project's root `requirements.txt`**, matching the same isolation
convention already established for `evaluation/image_similarity/`'s own
`requirements.txt`. `Pillow` is already a root dependency and is reused
as-is (not re-declared). This keeps the main Flask app's install footprint
unchanged; installing the similarity service's dependencies is an explicit,
separate step (`pip install -r services/image_similarity/requirements.txt`).

### Model lifecycle

`SiglipEncoder` lazily loads the model+processor on first
`encode_image()`/`encode_images()` call and caches them for the instance's
lifetime; `get_default_encoder()` provides a process-wide singleton so the
model is loaded at most once per process. A lock guards both the one-time
load and each inference call (Hugging Face model objects aren't guaranteed
thread-safe for concurrent forward passes; a single lock is the smallest
correct thing for this project's current request volume — not unnecessary
infrastructure). Device is auto-selected (`cuda` if available, else `cpu`)
and observable via `encoder.device` (`None` until first loaded).

### Embedding cache

Local `.npz` (embedding matrix) + JSON sidecar (per-row metadata:
`property_id`, `image_id`, `image_path`, `model_id`, `embedding_dim`,
`created_at`) — no new MongoDB schema was introduced. Inspection of the
production property schema (`services/property_services.py`, `routes/
property_routes.py`) found only an unused, singular `search.embedding: None`
placeholder field already present on property documents — no existing
per-image embedding persistence layer to build on. `EmbeddingCache`'s
`save()`/`load()` are isolated enough that moving to MongoDB later only
means rewriting those two methods, not any caller.

### Property IDs in this phase

The offline dataset (`properties/House_<NNN>/`) uses folder-based property
IDs (`"House_007"`), **not** the real MongoDB `ObjectId` strings production
property documents use. This phase's retrieval results (`property_id`
field) therefore refer to the offline benchmark dataset, not live listings —
consistent with "not yet connected to production search/UI." Connecting
this to real property documents would need a property_id mapping step, not
attempted here.

## Dataset

21 houses / 84 images (`properties/House_001`–`House_021`). Known,
previously-documented characteristics that still apply and are NOT resolved
by this phase:

- `House_011` has only one image — contributes no valid same-property
  positive candidate once the query image itself is excluded (Step 10's
  leakage rule); this service's own `benchmark_compare.py` (property-level
  metric) confirms exactly 1 of 84 queries is skipped for this reason,
  matching the historical benchmark's `n_skipped_no_positive: 1`.
- One byte-identical duplicate image pair exists
  (`House_006/bedroom_01.jpeg` ≡ `House_006/living_room_01.jpeg`).
- `House_010`–`House_021` ("Group B") contain visible Magicbricks
  watermarks in sampled images; `House_001`–`House_009` ("Group A") do not.
  A source/style confound remains **possible** (not proven) — see the prior
  source-stratified analysis (`evaluation/image_similarity/results/
  source_stratified_analysis.md`) for the full evidence.
- The benchmark is small (84 images, 21 houses). **Results should not be
  treated as general performance guarantees** — they are observations on
  this specific benchmark, at this specific size, with this specific
  dataset composition.

## Current benchmark (historical, evaluation/image_similarity/)

SigLIP2, property-level, 21-house / 84-image benchmark (the baseline this
service's numbers are compared against below; an earlier 8-house/39-image
pilot exists too — see `evaluation/image_similarity/README.md` for that
full history):

| Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|
| 0.434 | 0.590 | 0.663 | 0.831 | 0.550 |

## Benchmark consistency (Step 13)

`services/image_similarity/benchmark_compare.py` re-encoded all 84 images
with this service's own `SiglipEncoder` (a fresh, independent
implementation, not a copy-paste of the evaluation module's code) and
computed two things from the same fresh embeddings:

**1. Image-level metric** (identical protocol/code to the historical
benchmark — literally calls `evaluation/image_similarity/metrics.
evaluate_grouped_retrieval()`, not a reimplementation):

| | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|---|
| Historical | 0.434 | 0.590 | 0.663 | 0.831 | 0.550 |
| New (this service's embeddings) | 0.434 | 0.590 | 0.663 | 0.831 | 0.550 |
| Diff | 0.0003 | 0.0004 | 0.0003 | 0.0003 | 0.0000 |

**Confirmed consistent** — differences are floating-point rounding noise
(4th decimal place), not a real discrepancy. The new encoder implementation
produces embeddings that reproduce the historical benchmark almost exactly.

**2. Property-level-aggregation metric** (this service's actual retrieval
design — exclude only the query image itself, max-aggregate remaining
candidates per property, rank properties, check if the query's own property
lands in the top-K):

| | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|---|
| Image-level (historical protocol) | 0.434 | 0.590 | 0.663 | 0.831 | 0.550 |
| Property-level (this service) | 0.434 | 0.602 | 0.723 | 0.892 | 0.563 |

**This difference is expected and explained, not a bug**: the two protocols
are mathematically NOT equivalent for K>1. Image-level Recall@K asks "does a
same-property image appear in the top-K *individually-ranked* images (out
of all 83 others)?" — a house with several *other* houses each contributing
multiple strong-but-not-best images can individually occupy several of
those top-K slots. Property-level Recall@K asks "does the query's own
property rank in the top-K when every *other* property is represented only
by its single best-matching image?" — a house with many images can now only
ever occupy ONE competing slot, however many strong photos it has. This
structurally makes property-level Recall@K@(K>1) **greater than or equal
to** image-level Recall@K on the same embeddings (a short proof: image-level
Recall@K "success" requires the query's best same-property image to
individually outrank all-but-fewer-than-K other individual images; property-
level success only requires it to outrank all-but-fewer-than-K other
*properties'* best images — a strictly easier condition when any competing
property contributes more than one image above the threshold). **Recall@1
is provably identical between the two protocols** (both reduce to "does the
query's best same-property image beat literally every other individual
image" — confirmed empirically above: 0.434 = 0.434, exact to 4 decimals).

No metric definition was changed to force a match — this discrepancy is
fully attributable to the aggregation methodology itself, verified by
holding the embeddings fixed and only changing the evaluation protocol.

## Production status

**Similarity service isolated; not yet connected to production
search/UI.** No Flask route calls this module. No frontend code references
it. No production property document was read or modified. This phase is
retrieval infrastructure only — see the parent Phase 6 analysis documents
for the full evaluation history this service is built on top of.

## Performance

CPU-only (`torch.cuda.is_available()` was `False` on the development
machine this was built/tested on) — no GPU required, and none was used.
Brute-force cosine comparison (`NumPy matrix @ query vector`) is used for
the 84-image dataset — no FAISS, no vector database, per instructions
("only introduce FAISS/vector DB when the property/image count justifies
it" — 84 does not).

## Security

No API keys, no external inference APIs, no external image transmission —
everything runs locally against files already on disk. No image content or
secrets are logged anywhere in this module.
