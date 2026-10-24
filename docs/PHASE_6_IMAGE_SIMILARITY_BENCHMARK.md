# Phase 6 — Image Similarity, Step 1: Offline Model Benchmark (SigLIP2 vs DINOv2)

Status: **research only**. Nothing in this phase is wired into production search,
ranking, or the `/design` route. See `evaluation/image_similarity/` for the
standalone benchmark code this report describes.

## 1. Objective

Determine which pretrained image-embedding model — **SigLIP2**
(`google/siglip2-base-patch16-224`) or **DINOv2** (`facebook/dinov2-base`) — is
better suited to finding visually/architecturally similar real-estate property
photos, given a reference image obtained either by:

1. **Generation**: user prompt → Gemini (semantic understanding) → FLUX.2 Klein
   4B → generated reference image, or
2. **Upload**: user-selected file → validated → reference image as-is.

Both paths already converge on one `reference_image_url` in the existing
`/design` page (see `static/design_reference_state.js`). This benchmark does
**not** touch that flow — it only evaluates candidate embedding models offline.

## 2. Existing property-image architecture (as inspected, before any code was written)

- **Storage mechanism**: `services/media_service.py`'s `save_images()` writes
  uploaded property photos to `static/images/properties/<uuid4>.<ext>` (a flat
  directory of validated JPG/JPEG/PNG/WebP files, filenames never derived from
  the original upload — see `IMAGE_DIRECTORY`, `_unique_filename()`). Content is
  validated with `PIL.Image.verify()`, not by trusting the extension.
- **MongoDB schema** (`services/property_services.py` + the document built in
  `routes/property_routes.py`, collection `properties`): each property document
  has
  ```
  media: {
    images: [<filename>, ...],                # static/images/properties/<filename>
    image_meta: [{filename, category, is_cover}, ...],
    videos: [...], floor_plan, brochure, virtual_tour_url
  },
  search: { keywords: [...], embedding: None }  # <- an embedding slot already
                                                  #    exists in the schema,
                                                  #    unused today
  ```
  `image_meta.category` is chosen from a fixed list in `services/media_service.py`
  (`exterior`, `living_room`, `bedroom`, `kitchen`, `bathroom`, `balcony`,
  `garden`, `parking`, `floor_plan`, `other`) — the right vocabulary for a real
  evaluation set, once real photos exist (see §14).
- **Image generation flow** (unrelated storage path): `services/image_service.py`
  returns a `PIL.Image` as a base64 data URL — generated images are **not**
  written to `static/images/properties/` and have no `image_meta`/category at
  all today.

## 3. Dataset / evaluation set — critical finding

The live MongoDB `properties` collection has **7 property documents**, of which
**4 have at least one image**, totaling **8 files**. A byte-for-byte MD5 check
of every file found they are only **5 distinct images** — 3 of the 8 files are
exact re-uploads of images already used under a different property/category:

| File(s) | Property / stored category | What it **actually** shows |
|---|---|---|
| `WIN_20241125_13_57_15_Pro.jpg` | (no `image_meta`) | Dorm-style room: bunk beds, hanging clothes, a person standing holding a phone |
| `WIN_20241125_13_57_16_Pro.jpg` == `2b98d81297a547e69270a2697520525b.jpg` | stored category: `"exterior"` | Same dorm room as above, a different frame — **not an exterior** |
| `WIN_20231207_22_49_20_Pro.jpg` == `c40b2b54fc9d46ffbb72a58d6bc287a3.jpg` | stored category: `"bedroom"` | Close-up selfie of two people indoors — **not a bedroom** |
| `WIN_20240919_13_26_25_Pro.jpg` == `fbfcaf0ecb844fa6bc60a327f4ac8561.jpg` | stored category: `"living_room"` | Blurry selfie of three people lying down — **not a living room** |
| `8918826087604660bd2ccfae7bca5230.jpg` | stored category: `"other"` | A downloaded Radha-Krishna devotional-art wallpaper — **not a photo of any property at all** |

**None of the 8 files depict a real house, apartment, room, or exterior.**
These are personal test photos and one stock wallpaper, uploaded while
manually exercising the property-listing upload form during earlier
development — not genuine seller-submitted listing photos. The stored
`category` labels on the 3 re-uploaded files do not match their actual visual
content at all; they are placeholder values clicked through while testing the
form, not real annotations.

Per this task's own instruction — *"If there are insufficient existing
property images, report that limitation instead of inventing a dataset"* —
**this benchmark does not construct a labeled real-estate evaluation set from
this data.** Doing so (e.g. treating the wallpaper as a "living room") would
be fabricating ground-truth labels, which was explicitly disallowed. No
external/stock real-estate images were sourced either, since that wasn't
authorized for this phase.

**Consequence for Steps 3–6 of the original task**: a genuine
manually-labeled real-estate evaluation set, Top-1/3/5/10 category-retrieval
accuracy, property-specific good/bad qualitative examples, and a model-
combination recommendation **cannot be honestly produced today.** What this
report gives instead:

- A fully built, reusable benchmark pipeline (§6–§7) that requires **zero
  code changes** once a genuine labeled dataset exists — just point
  `benchmark.py --manifest path/to/real_dataset.json` at it.
- Real, dataset-size-independent measurements: model load time, embedding
  dimension, per-image latency, approximate memory (§9).
- A **pipeline sanity check** (§10) over the 5 distinct non-property files
  that do exist — explicitly not a real-estate accuracy benchmark, used only
  to confirm the embedding pipeline itself behaves sensibly (e.g. two photos
  of the literal same physical room should embed closer to each other than to
  unrelated content).

## 4. Models tested

| | Checkpoint | Notes |
|---|---|---|
| SigLIP2 | `google/siglip2-base-patch16-224` | Pretrained only, no fine-tuning. Loaded via `AutoModel` (see §14 for why — this checkpoint's own `config.json` declares `"model_type": "siglip"`, and forcing the newer `Siglip2Model` class onto it fails with a weight-shape mismatch; `AutoModel`/`SiglipModel` is the correct class for this fixed-resolution checkpoint). |
| DINOv2 | `facebook/dinov2-base` | Pretrained only, no fine-tuning. Loaded via `Dinov2Model`; image embedding = `pooler_output` (CLS-token representation). |

Both loaded through `transformers==4.57.6` (see §14 — the environment's
pre-existing `transformers==4.45.0` does not support SigLIP2 at all; it was
upgraded system-wide, isolated from the Flask app's own `.venv`, which never
had torch/transformers installed in the first place).

## 5. Preprocessing

Each model's own Hugging Face `AutoImageProcessor` (SigLIP2: resize to
224×224 + SigLIP normalization; DINOv2: resize shortest edge to 256 + ImageNet
normalization via `BitImageProcessor`) — no custom resizing/cropping code was
written; this benchmark deliberately uses each model's officially paired
preprocessing rather than a single shared pipeline, since forcing one model's
preprocessing onto the other would bias the comparison.

## 6. Embedding methodology

```
image -> PIL.Image (RGB) -> model's own AutoImageProcessor -> model (torch.no_grad(), pretrained weights, CPU)
      -> image embedding:
           SigLIP2: model.get_image_features(**inputs)
           DINOv2:  model(**inputs).pooler_output
      -> L2 normalization (evaluation/image_similarity/metrics.l2_normalize)
```

`evaluation/image_similarity/models.py` is the only file in the whole repo
that imports torch/transformers or downloads a checkpoint. `metrics.py` (the
math below) has zero ML dependencies by design, so it is covered by
`test_image_similarity_metrics.py` (18 tests) in the **normal** test suite —
no model download or network access happens there.

## 7. Similarity calculation

`cosine_similarity(query_embedding, candidate_embedding)` over the
L2-normalized vectors, implemented in pure Python
(`evaluation/image_similarity/metrics.py`). Per this task's instruction, raw
cosine scores are **not** compared across the two models as if calibrated the
same way — §11/§12 report each model's own score distribution separately, and
§13's comparison is by retrieval *behavior* (which neighbor ranked first,
whether it's the right one), not by whose cosine numbers are numerically
higher.

Retrieval always uses **leave-one-out**: for a given query image, every other
image is a candidate (see `metrics.rank_candidates`) — with only 5 distinct
images total, holding out anything more than the query itself would leave too
little data to rank against. `metrics.same_property_leakage_rate()` exists to
flag if a model is keying on property identity (lighting, camera, wall color)
rather than genuine visual-category similarity; it wasn't meaningfully
exercisable here since none of the 5 distinct images share a `property_id`
after deduplication (the only same-property pairs in the raw 8-file data were
exact-duplicate re-uploads, which `build_pipeline_smoke_manifest()`
deliberately deduplicates out — see §3/§14).

## 8. Retrieval metrics

**Not computed as Top-1/3/5/10 accuracy** — with only 5 distinct images and no
genuine category labels (§3), a Top-10 metric is meaningless (there aren't 10
candidates, let alone 10 *relevant* ones), and Top-1/3/5 against fabricated
labels would be scientifically invalid. `evaluation/image_similarity/
metrics.py`'s `top_k_category_accuracy()` function **implements** this metric
correctly (verified by `test_image_similarity_metrics.py` against synthetic
embeddings) and `benchmark.py --manifest ...` will compute real Top-1/3/5/10
numbers automatically the moment a genuine labeled manifest is supplied — see
§16.

## 9. Latency / resource measurements

Measured on this machine (Windows, CPU-only — `torch.cuda.is_available()` is
`False`), single process, models loaded sequentially (SigLIP2 first, then
DINOv2, in the same Python process):

| | SigLIP2 | DINOv2 |
|---|---|---|
| Embedding dimension | 768 | 768 |
| Model load time | 1.67s | **240.2s** (see caveat below) |
| Per-image embedding latency (mean / min / max) | 0.63s / 0.37s / 1.64s | 0.40s / 0.35s / 0.49s |
| Approx. process memory before this model's load | 20.9 MB | 716.0 MB |
| Approx. process memory after embedding all 5 images | 1071.0 MB | 1055.4 MB |
| Approx. memory delta attributable to this model | ~1050 MB | ~339 MB |

Total benchmark runtime (both models, this run): **311.2s**, of which DINOv2's
240.2s load dominates.

**Caveats, stated plainly rather than smoothed over:**
- DINOv2's 240s load time is almost certainly inflated by running *second* in
  the same process — `before_load` memory for DINOv2 (716 MB) shows SigLIP2's
  model was still resident (this benchmark does not unload models between
  runs), so the 240s likely reflects memory-pressure/paging on this machine
  rather than an inherent property of DINOv2 itself. Both checkpoints use the
  `.safetensors` format (ruled out as the cause). A cleaner load-time
  comparison would load each model in its own fresh process — noted as a
  concrete next step (§16), not yet done.
- An earlier run of this same benchmark recorded a `max` per-image latency of
  ~15,960 seconds (4.4 hours) on one image — this was the machine going idle/
  asleep mid-run, not real inference time; that run's numbers were discarded
  and are not reported here. The numbers in the table above are from a clean,
  uninterrupted run.
- No GPU was available on this machine; all numbers are CPU-only and would
  not directly predict GPU-served latency in production.

## 10. Qualitative examples (pipeline sanity check, NOT a real-estate benchmark)

Over the 5 distinct real files (labeled by their **true** content — dorm-room
photo / personal selfie / wallpaper — never by the misleading stored
categories), each image's single nearest neighbor by cosine similarity:

**SigLIP2** — 4 of 4 eligible queries (excluding the singleton wallpaper,
which has no same-category partner to find) correctly matched same-content:

| Query | Nearest neighbor | Cosine sim | Correct? |
|---|---|---|---|
| dorm-room photo #1 | dorm-room photo #2 | 0.972 | ✅ |
| dorm-room photo #2 | dorm-room photo #1 | 0.972 | ✅ |
| selfie #1 (2 people) | selfie #2 (3 people) | 0.839 | ✅ |
| selfie #2 (3 people) | selfie #1 (2 people) | 0.839 | ✅ |
| wallpaper (singleton) | selfie #2 | 0.574 | N/A — no correct answer exists |

**DINOv2** — 2 of 4 eligible queries correctly matched same-content:

| Query | Nearest neighbor | Cosine sim | Correct? |
|---|---|---|---|
| dorm-room photo #1 | dorm-room photo #2 | 0.913 | ✅ |
| dorm-room photo #2 | dorm-room photo #1 | 0.913 | ✅ |
| selfie #1 (2 people) | dorm-room photo #2 | 0.332 | ❌ (expected selfie #2) |
| selfie #2 (3 people) | dorm-room photo #2 | 0.379 | ❌ (expected selfie #1) |
| wallpaper (singleton) | selfie #2 | 0.105 | N/A |

Interesting, but **explicitly not generalizable**: on this tiny, non-real-
estate sample, SigLIP2 grouped the two visually-related indoor selfies
together while DINOv2 did not (DINOv2's top-1 for both selfies was the dorm
room instead). This could reflect a genuine difference in what each model's
embedding space emphasizes (SigLIP2 is trained with image-text contrastive
supervision and may weight overall scene/color similarity more; DINOv2 is
trained self-supervised on patch-level structure and may weight
texture/composition differently) — or could just as easily be an artifact of
these 5 specific, non-property images. **Do not treat this as evidence about
real-estate photo retrieval.**

## 11. SigLIP2 results

See §9 (resource measurements) and §10 (qualitative sanity check) — no
category-labeled retrieval-accuracy numbers exist yet (§3, §8). Full
Top-1/3/5/10 numbers will appear here once run with `--manifest` against a
genuine labeled dataset.

## 12. DINOv2 results

See §9 (resource measurements) and §10 (qualitative sanity check) — same
caveat as §11.

## 13. Comparison

| | SigLIP2 | DINOv2 |
|---|---|---|
| Embedding dim | 768 | 768 |
| Per-image latency | Comparable, ~0.6s mean | Comparable, ~0.4s mean (slightly faster) |
| Memory footprint (own delta) | ~1050 MB | ~339 MB (noticeably lighter) |
| Pipeline sanity-check hit rate (4 eligible pairs, non-property images) | 4/4 | 2/4 |

DINOv2 has a meaningfully smaller memory footprint per this run. SigLIP2's
sanity-check hit rate was better on this tiny sample, but per §10 that is not
strong enough evidence — sample size 4 pairs, zero real property photos — to
recommend one model over the other for real-estate retrieval specifically.

## 14. Limitations

1. **No genuine real-estate images exist in this repository/database today**
   (§3) — the single largest limitation of this entire benchmark. Every
   number in §8/§11/§12 that would normally come from real-estate Top-K
   accuracy is simply absent, by design, rather than faked.
2. Sample size for even the qualitative sanity check is 5 distinct images (4
   scoreable pairs) — far too small to be statistically meaningful for
   anything.
3. `google/siglip2-base-patch16-224`'s checkpoint metadata is misleading:
   `config.json` declares `"model_type": "siglip"`, and the newer
   `Siglip2Model` transformers class fails to load it (verified directly — a
   `torch.Size([768, 3, 16, 16])` vs `([768, 768])` weight-shape mismatch).
   This benchmark uses `AutoModel` (which correctly resolves to `SiglipModel`)
   instead — this is very likely intentional on Google's part (SigLIP2's
   *fixed-resolution* variants keep the original Conv2d patch embedding; only
   the NaFlex variants use the new architecture), but is worth flagging since
   it is easy to get this wrong silently.
4. `transformers==4.45.0` (the version already present on this machine before
   this benchmark) does not support SigLIP2 at all; this benchmark required
   upgrading it to `4.57.6`, done in a way that does not affect the Flask
   app (its own `.venv` never had torch/transformers installed) — see §16.
5. DINOv2's 240s load-time measurement is confounded by running second in the
   same process (§9) and should not be read as a clean per-model number.
6. CPU-only measurements (no GPU on this machine) — production latency on a
   GPU-backed server would very likely be substantially lower for both
   models and the *relative* difference between them may not hold.
7. The `search.embedding` field already reserved (but unused, `None`) in the
   property schema (§2) hints this was anticipated architecturally, which is
   convenient for a future real integration but has no bearing on which model
   to pick.

## 15. Recommendation for production

**No production model choice can be honestly recommended yet.** The
infrastructure (§4–§9) is built, correct, and ready to produce real Top-K
retrieval metrics the moment genuine, honestly-labeled property images exist
— but making a "SigLIP2 vs DINOv2 for real estate" call today would mean
basing it on either non-property test photos or fabricated labels, both of
which this task explicitly ruled out. This is itself the honest, evidence-
based conclusion this phase was asked to produce.

If forced to pick a *starting point* for the next phase's real evaluation
purely on infrastructure grounds (not accuracy): DINOv2's smaller memory
footprint (§13) makes it marginally cheaper to serve, and it needs no
`AutoModel`/checkpoint-metadata workaround (§14.3) — but this is not a
substitute for measuring both against real data.

## 16. Next step

1. **Collect a genuine, honestly-labeled real-estate image set** before any
   further step in this phase — either real property photos from this
   project's own users (once there are enough), or an explicitly-approved
   external real-estate image dataset (not sourced automatically by this
   benchmark, since that wasn't authorized here). Label using the vocabulary
   already in `services/media_service.py`'s `IMAGE_CATEGORIES` (`exterior`,
   `living_room`, `bedroom`, `kitchen`, `bathroom`, `balcony`, `garden`,
   `parking`, `floor_plan`, `other`) so labels stay consistent with the
   existing upload feature.
2. Build a manifest JSON (`[{"id", "path", "label", "property_id"}, ...]`,
   per `dataset.load_manifest()`'s documented format) from that set and run
   `python evaluation/image_similarity/benchmark.py --manifest <path>` — no
   code changes needed; this produces real Top-1/3/5/10 accuracy,
   `same_property_leakage_rate()`, and the property-specific
   good/bad-retrieval qualitative analysis Steps 5 and 8 of the original task
   ask for.
3. Re-measure load time with each model in its own fresh process (§9,
   §14.5) for a clean, uncontaminated load-time comparison.
4. Only *after* both models have real Top-K numbers on real data: consider
   the model-combination experiment (concatenated or score-averaged SigLIP2 +
   DINOv2 embeddings) explicitly left unimplemented per this task's
   instructions ("do NOT automatically create a combined score... First
   determine individual performance").
5. Only after that: design the actual production integration (an index/
   nearest-neighbor store, when embeddings get computed for uploaded/
   generated images, how `/design`'s "Find Similar Homes" button — currently
   a placeholder, see `static/design_reference_state.js` — calls it). None of
   this is implemented in this phase, per instructions.
