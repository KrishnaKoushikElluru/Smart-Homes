# Phase 6 Image-Similarity Benchmark: SigLIP2 vs DINOv2

Standalone research only. Does **not** touch SmartHomes production code
(`routes/`, `templates/`, `services/`, `app.py`, MongoDB) and is never imported
by the Flask app or the root test suite. Matches the isolation convention
already used by `../geo_coordinate_benchmark/` and `../nlp/` in this repo.

## Question being tested

```
Reference image (generated via Gemini->FLUX, or user-uploaded)
                     |
                     v
   [which pretrained image-embedding model - SigLIP2 or DINOv2 -
    retrieves the most visually/architecturally similar property
    photos, by cosine similarity over L2-normalized embeddings?]
```

## Critical finding first: there is no real-estate dataset to benchmark against

Before writing any embedding code, this benchmark inspected the live
`properties` MongoDB collection and `static/images/properties/`. There are 8
image files across 4 property documents, but a byte-for-byte hash check shows
they are only **5 distinct images**, and **none of them depict a real house,
apartment, or room** - they are personal test photos and one downloaded
wallpaper, uploaded while manually exercising the property-listing upload
form:

| File(s) | What it actually shows | Stored category label |
|---|---|---|
| `WIN_20241125_13_57_15_Pro.jpg` | Dorm-style room: bunk beds, hanging clothes, a person standing | *(none)* |
| `WIN_20241125_13_57_16_Pro.jpg` == `2b98d812...jpg` | Same dorm room, different frame | `"exterior"` |
| `WIN_20231207_22_49_20_Pro.jpg` == `c40b2b54...jpg` | Selfie of two people indoors | `"bedroom"` |
| `WIN_20240919_13_26_25_Pro.jpg` == `fbfcaf0e...jpg` | Selfie of three people lying down | `"living_room"` |
| `8918826087604660bd2ccfae7bca5230.jpg` | Downloaded Radha-Krishna wallpaper illustration | `"other"` |

The stored category labels do not describe the actual image content - they
are placeholder values clicked through while testing the upload feature.
Treating them as ground truth (e.g. "the wallpaper is a `living_room`") would
be fabricating labels, which the task this benchmark was built for explicitly
forbids. **See `dataset.py`'s module docstring and
`docs/PHASE_6_IMAGE_SIMILARITY_BENCHMARK.md` for the full writeup.**

Consequently: Steps 3-6 of the original task (a manually-labeled real-estate
evaluation set, Top-1/3/5/10 category-retrieval accuracy, qualitative
good/bad-retrieval examples, a model-combination recommendation) cannot be
honestly completed with today's data. This benchmark instead:

1. Fully builds and validates the embedding pipeline (Step 2) - reusable
   as-is once real, honestly-labeled property photos exist.
2. Measures real, dataset-independent numbers: model load time, embedding
   dimension, per-image embedding latency, approximate memory, total runtime.
3. Runs a **pipeline sanity check** (not a real-estate accuracy benchmark)
   over the 5 distinct non-property files that do exist: do the two photos
   of the *same* physical dorm room embed more similarly to each other than
   to an unrelated selfie or the wallpaper, for each model?

## Files

- `dataset.py` - the critical-finding writeup above (in code, as a docstring)
  plus `build_pipeline_smoke_manifest()` (labels the 5 real files by their
  TRUE content) and `load_manifest()` (the generic format a future genuine
  labeled dataset should use - no code changes needed elsewhere once one
  exists).
- `models.py` - the ONLY file in this repo that imports torch/transformers or
  downloads a model checkpoint. Loads pretrained SigLIP2
  (`google/siglip2-base-patch16-224`) and DINOv2 (`facebook/dinov2-base`) -
  no fine-tuning, no training - and extracts an L2-normalized image embedding
  per image.
- `metrics.py` - pure-Python (stdlib `math` only, no numpy/torch) cosine
  similarity, L2 normalization, leave-one-out Top-K category-retrieval
  accuracy, and a same-property "leakage" diagnostic. Dependency-free by
  design so it's unit-tested in the project's normal test suite
  (`../../test_image_similarity_metrics.py`) with synthetic embeddings - no
  model download or network access needed to verify this logic.
- `benchmark.py` - the runnable entry point. Without `--manifest`, runs the
  pipeline sanity check described above. With `--manifest path/to/file.json`
  (a list of `{"id", "path", "label", "property_id"}` objects), runs the full
  Top-1/3/5/10 retrieval-accuracy evaluation instead - ready to use the
  moment a genuine labeled dataset exists.
- `requirements.txt` - isolated dependencies (torch, transformers, Pillow,
  psutil) - intentionally NOT added to the project's root `requirements.txt`
  or Flask `.venv`.
- `results/benchmark_results.json` - the last run's raw output.

## How to run

```bash
pip install -r evaluation/image_similarity/requirements.txt
python evaluation/image_similarity/benchmark.py
```

First run downloads both checkpoints from the Hugging Face Hub (network
access + several hundred MB of disk) - this is why it must never happen
automatically in Flask startup or the test suite.

## Model combination

Per the task instructions, this benchmark does NOT compute a combined
SigLIP2+DINOv2 score. See
`docs/PHASE_6_IMAGE_SIMILARITY_BENCHMARK.md`'s "Next step" section for
whether a future combination experiment looks worthwhile.

---

# Phase 6 Step 1 — PILOT benchmark (real dataset: 8 houses, 39 images)

This section documents a SEPARATE, later run of this same benchmark code
against a genuine, real-property image set the user collected specifically
for this purpose (`properties/House_<N>/*.jpeg`, at the repo root - not
`static/images/properties/`, which is the unrelated test-upload data
described above and left exactly as it was). **This is a development/pilot
benchmark, not the final SmartHomes image-similarity evaluation** - see
"Limitations" and "Next step" below.

## 1. Objective

Verify, on a small but genuine real-estate dataset, that: the dataset
pipeline works; embeddings can be generated correctly; property-level
retrieval evaluation works; SigLIP2 and DINOv2 can be compared under
identical conditions; retrieval behavior is interpretable; and the
benchmark is structurally ready to scale to 20-50 houses later. **Not** to
make a final production model choice - 8 houses is explicitly too small for
that, and every result below is reported as a "pilot observation."

## 2. Pilot dataset

**8 houses, 39 images** (`properties/House_1` through `House_8`; 12 further
directories, `House_9` through `House_20`, exist as empty placeholders for
future houses and contain no images - reported, not treated as an error).
Every one of the 39 files opened and verified successfully with Pillow (0
unreadable). All are JPEG. Discovered and validated by
`dataset.scan_pilot_dataset()`, never hand-typed.

| House | Images |
|---|---|
| House_1 | 4 |
| House_2 | 4 |
| House_3 | 3 |
| House_4 | 5 |
| House_5 | 4 |
| House_6 | 4 |
| House_7 | 11 |
| House_8 | 4 |

## 3. Dataset structure

Each image's `house_id` comes from its parent directory name (authoritative,
never guessed). Each image's `category` comes from its own filename,
normalized (case-folded; a trailing `_<digits>` suffix stripped, since this
dataset consistently uses it to mean "another photo of the same room" -
e.g. `Bed_Room_1.jpeg` and `Bed_Room.jpeg` both become `bed_room`) but
**never remapped onto a different vocabulary** - e.g. `sit_out` is kept as
`sit_out`, not guessed to mean `balcony` or `exterior`, and `bed_room` /
`master_bedroom` / `common_bed_room` are kept as three distinct categories
even though they are near-synonyms, because merging them would mean
inventing a mapping the filenames don't explicitly support. See
`dataset.normalize_category_from_filename()`.

```
Categories:
living_room: 11
bed_room: 9
kitchen_room: 9
master_bedroom: 2
common_bed_room: 2
sit_out: 2
balcony: 1
bath_room: 1
devotional_room: 1
parking_or_sit_out: 1
```

Category metadata is therefore available and used for a **separate**
category-level analysis (§6/§11/§12), clearly distinguished from the
PRIMARY property-level metric throughout - they are never conflated.

**Dataset issue found and reported, not silently fixed:**
`House_6/Bed_Room.jpeg` and `House_6/Living_Room.jpeg` are **byte-identical**
(the same photo, saved under two different room-category filenames within
the same house). Both were preserved in the dataset (per instructions, no
existing image was deleted or modified) and both appear in the manifest as
separate entries, but this means the `House_6/Bed_Room.jpeg` ↔
`House_6/Living_Room.jpeg` retrieval pair is a **trivial, non-visual**
match for any embedding model (cosine similarity ≈ 1.0 for both models,
confirmed in §11/§12) - it should not be read as evidence of genuine
visual-similarity understanding. This affects 2 of the 39 queries.

## 4. Property-level evaluation protocol

For each query image (all 39 images are used as a query exactly once):

- **Candidate gallery** = every other image in the dataset. The query image
  itself is never a candidate for itself (`metrics.rank_candidates()`
  excludes it structurally, not by chance).
- **Positive candidates** = every OTHER image from the SAME `house_id`,
  regardless of room category (a bedroom photo's positive candidates
  include that house's kitchen/living-room photos too - property-level
  ground truth is house identity, not room type; see §10's qualitative
  notes on what this means in practice).
- **Negative candidates** = every image from a DIFFERENT house.

No train/test split was performed (this is retrieval evaluation, not
training - no model here is fine-tuned). A house with only one image would
have no possible positive candidate; the dataset has none (`House_3` is the
smallest at 3 images), but the code (`metrics.evaluate_grouped_retrieval()`)
handles this case explicitly (`n_skipped_no_positive`) rather than silently
scoring an impossible-to-win query as a miss.

## 5. Leakage prevention

- The query image never appears in its own candidate gallery (structural
  guarantee in `rank_candidates()`, unit-tested in
  `test_image_similarity_metrics.py`).
- No image is excluded from the gallery just because it shares a house with
  the query - property-level retrieval is specifically testing whether
  OTHER same-house images can be found, so this is the evaluation's whole
  point, not leakage.
- Images are matched to exactly one `house_id` each (directory-derived, no
  cross-house reassignment possible) - `test_image_similarity_dataset.py`
  covers this explicitly.
- No train/fine-tune step exists anywhere in this pipeline for leakage to
  occur through in the first place - inference only, pretrained weights only.

## 6. Category-level analysis (SEPARATE from property-level - see §11/§12)

Computed with the same `evaluate_grouped_retrieval()` function, called with
`group_key="category"` instead of `group_key="house_id"`. A query's
category must have at least one other member for it to count (4 categories
- `balcony`, `bath_room`, `devotional_room`, `parking_or_sit_out` - have
only 1 image each and are excluded from category-level averages, exactly
like the property-level rule in §4).

## 7. Models

Unchanged from the original Phase 6 benchmark (§"Files" above) -
`models.py`'s existing `load_siglip2()` / `load_dinov2()` /
`embed_image()` were reused as-is, with zero modifications, for this pilot.

## 8. Embedding extraction

`image -> each model's own AutoImageProcessor -> model (torch.no_grad(), CPU, pretrained) -> image embedding -> L2 normalization` - identical to §"Preprocessing"/"Embedding methodology" above in this same file's earlier section.

## 9. Similarity calculation

Cosine similarity over L2-normalized embeddings (`metrics.cosine_similarity()`
- for unit vectors this is exactly the dot product, computed the same way
regardless). Raw cosine scores are not compared across models as if
calibrated identically (see §12's plainly lower absolute DINOv2 similarity
values vs SigLIP2's - this reflects each model's own embedding-space
geometry, not "DINOv2 thinks everything is 0.3 as similar").

## 10. Metrics

- **Recall@K** (K = 1, 3, 5, 10): fraction of valid queries where at least
  one positive candidate appears in the top K ranked results.
- **MRR**: mean, over valid queries, of `1 / rank of the first positive
  candidate` in the full ranking.
- **Mean positive similarity**: mean cosine similarity, pooled over every
  (query, positive-candidate) pair.
- **Mean top-negative similarity**: mean, over valid queries, of the
  similarity of that query's single best-ranked NEGATIVE candidate - how
  visually confusable the hardest wrong-house image is.
- `n_queries` / `n_valid_queries` / `n_skipped_no_positive` reported
  alongside every metric block (see §4).

All four are implemented in `metrics.evaluate_grouped_retrieval()` and unit
-tested with synthetic embeddings in
`test_image_similarity_metrics.py::EvaluateGroupedRetrievalTests` (8 tests) -
no model download needed to verify this logic.

## 11. SigLIP2 results (pilot, 8 houses / 39 images)

Device: **CPU** (no GPU available on the machine this ran on). Embedding
dimension: **768**. Model load: **11.34s**. Total embedding time (39
images): **32.20s** (mean **0.826s**/image). Retrieval computation: **1.46s**.
Approx. memory delta for this model: **~757 MB**.

| | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|---|
| Property-level (39 valid queries) | 0.564 | 0.692 | 0.872 | 0.974 | 0.671 |
| Category-level (35 valid queries) | 0.657 | 0.886 | 0.943 | 0.971 | 0.770 |

Mean positive similarity (property-level): 0.820. Mean top-negative
similarity: 0.869 (i.e. the hardest wrong-house candidate is, on average,
*more* similar than the true positives are - SigLIP2's absolute similarity
scores run high and tightly clustered across this whole dataset; rank
order, not the raw score gap, is what recall/MRR above actually measure).

## 12. DINOv2 results (pilot, 8 houses / 39 images)

Device: **CPU**. Embedding dimension: **768**. Model load: **3.13s**
(loaded second in this process - see §"Limitations" for why this number is
not a clean cold-start figure). Total embedding time: **34.12s** (mean
**0.875s**/image). Retrieval computation: **1.21s**. Approx. memory delta
for this model: **~340 MB** (noticeably lighter than SigLIP2's).

| | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|---|
| Property-level (39 valid queries) | 0.179 | 0.410 | 0.564 | 0.641 | 0.350 |
| Category-level (35 valid queries) | 0.657 | 0.771 | 0.829 | 0.943 | 0.737 |

Mean positive similarity (property-level): 0.238. Mean top-negative
similarity: 0.496.

## 13. Comparison

| Metric | SigLIP2 | DINOv2 |
|---|---|---|
| Images | 39 | 39 |
| Houses | 8 | 8 |
| Embedding dimension | 768 | 768 |
| Avg embedding latency/image | 0.826s | 0.875s |
| Recall@1 (property) | 0.564 | 0.179 |
| Recall@3 (property) | 0.692 | 0.410 |
| Recall@5 (property) | 0.872 | 0.564 |
| Recall@10 (property) | 0.974 | 0.641 |
| Recall@1 (category) | 0.657 | 0.657 |
| MRR (property) | 0.671 | 0.350 |
| Mean positive similarity | 0.820 | 0.238 |
| Mean top-negative similarity | 0.869 | 0.496 |
| Device | CPU | CPU |
| Model load time | 11.34s | 3.13s* |
| Total runtime (both models, this pilot) | 192.0s | |

\* confounded by running second in the same process - see Limitations.

**Pilot observation, not a production conclusion**: on THIS 8-house/39-image
pilot, SigLIP2 shows a substantially higher property-level recall/MRR than
DINOv2, while the two are statistically tied at category-level Recall@1.
This gap is large enough to be worth carrying into the next, larger
evaluation round - but 8 houses is far too small a sample to generalize
from confidently, and this must be re-measured on 20-50 houses (§16)
before it informs any production decision.

## 14. Qualitative observations

Full top-5 results for all 39×2 queries are in
`results/retrieval_examples.json`; a representative, non-cherry-picked
subset (spanning "found at rank 1", "found lower in top-5", and "not found
in top-5" for each model) is in `results/pilot_summary.md`. Highlights:

**Successful same-house retrieval (SigLIP2)**: `House_1/Bed_Room_1.jpeg`'s
top-1 match is `House_1/Bed_Room.jpeg` (0.847) - genuinely the same room,
different angle. `House_2/Bath_room.jpeg`'s top-3 are all `House_2`
photos (bathroom → kitchen → bedroom → living room, in similarity order) -
a real "this photoset has a consistent look" signal, not room-type matching.

**Difficult / partial retrieval (SigLIP2)**: `House_1/Bed_Room.jpeg`'s true
positive (`House_1/kitchen_room.jpeg`) only appears at rank 5 - ranks 1-4
are bedroom photos from OTHER houses (0.888, 0.885, 0.874, 0.874) that are
more visually similar in room type than the true positive is in property
identity. This is the property-vs-category tension the protocol (§4) is
explicitly built to surface.

**Visually-similar-but-wrong-house failures (SigLIP2)**: `House_3/
Kitchen_Room.jpeg`'s entire top-5 are kitchen photos from five DIFFERENT
houses (0.917 down to 0.883) - zero House_3 images appear. Kitchens across
this dataset are, per SigLIP2's embedding space, more similar to each other
by category than any of them are to their own house's other rooms.

**Trivial "success" flagged as an artifact, not a finding (both models)**:
`House_6/Bed_Room.jpeg` ↔ `House_6/Living_Room.jpeg` score ≈1.000 for BOTH
models - this is the byte-identical duplicate from §3, not evidence of
visual understanding.

**DINOv2's harder cases**: several `House_1` and `House_2` queries (e.g.
`House_1/Living_Room.jpeg`, `House_1/kitchen_room.jpeg`,
`House_2/Bath_room.jpeg`) find NO same-house image anywhere in their top-5
under DINOv2, while SigLIP2 succeeds on the same queries - consistent with
§13's large property-level recall gap on this pilot.

## 15. Limitations

1. **8 houses / 39 images is a pilot, not a production-ready sample size.**
   Every number above is explicitly a "pilot observation."
2. One dataset artifact (§3): `House_6`'s duplicate photo inflates 2 of 39
   queries' recall trivially.
3. Category vocabulary is filename-derived and intentionally NOT merged
   across near-synonyms (`bed_room` / `master_bedroom` / `common_bed_room`;
   `sit_out` / `parking_or_sit_out`) - a future manual pass could
   consolidate these into this project's existing
   `services/media_service.py` category vocabulary, but that remapping
   was not invented here (see §3).
4. DINOv2's model-load time (§12) is confounded by loading second in the
   same process (SigLIP2 was still resident) - not a clean cold-start
   number; same caveat as the original (non-pilot) benchmark run above.
5. CPU-only (no GPU on this machine) - absolute latency numbers would very
   likely be lower, and the relative gap between models may not hold, on
   GPU-backed production hardware.
6. Some houses have as few as 3 images (`House_3`) and one has 11
   (`House_7`) - group sizes are uneven, which the metrics (§10) handle
   correctly (via `n_valid_queries`) but which still means per-house
   statistical power varies a lot within this one pilot.
7. This pilot still does not answer "does this generalize beyond these 8
   specific houses' photography style/lighting/camera" - see §16.

## 16. Next step

1. **Expand the dataset to 20-50 distinct houses** (the empty `House_9`
   through `House_20` placeholders already exist for this) before drawing
   any production conclusion - re-run `python evaluation/image_similarity/
   benchmark.py --pilot` unchanged; no code changes are needed to scale up.
2. Manually resolve the `House_6` duplicate-photo artifact (§3/§15.2) -
   either by the user replacing one of the two files with a real distinct
   photo, or by explicitly documenting it as intentional.
3. Consider (not yet do) a human pass to consolidate near-synonym
   categories (§15.3) onto `services/media_service.py`'s existing category
   vocabulary, once there's enough data per category to make that
   worthwhile.
4. Only after a larger run confirms (or overturns) this pilot's property-
   level gap: consider the model-combination experiment explicitly left
   unimplemented per instructions (§"Model combination" above).
5. Only after that: design the actual production integration - unchanged
   from the original (non-pilot) report's §16 above; nothing in this pilot
   changes that recommendation's sequencing.

## Pilot files

- `results/pilot_results.json` - full machine-readable results (dataset
  summary, both models' metrics, representative examples).
- `results/retrieval_examples.json` - complete top-5 results for every one
  of the 39×2 queries (not just the representative subset).
- `results/pilot_summary.md` - auto-generated human-readable summary
  (dataset table, comparison table, representative qualitative examples) -
  regenerated by every `--pilot` run.

## How to run the pilot

```bash
pip install -r evaluation/image_similarity/requirements.txt
python evaluation/image_similarity/benchmark.py --pilot
```

---

# Phase 6 Step 1 — Duplicate sensitivity, margin analysis, and dataset expansion

This section documents a LATER round of work on top of the pilot above,
using the exact same 8-house/39-image pilot dataset (no images were added,
removed, renamed, or altered) plus a check for a planned 20-house
expansion. **Historical pilot findings above are unchanged and preserved as
written** - this section only adds analysis, it does not revise the pilot.

## 1. Duplicate sensitivity (Part A)

The `House_6/Bed_Room.jpeg` / `House_6/Living_Room.jpeg` duplicate flagged
in the pilot (§3 above) was explicitly re-verified with a cryptographic
hash (SHA-256, not the MD5 used for the original quick scan):

| File | Size | SHA-256 |
|---|---|---|
| `properties/House_6/Bed_Room.jpeg` | 139,818 bytes | `0ca7881210665e452322001a15bcf02ebdd6aedf9a4525a82676e1ea0fd805b5` |
| `properties/House_6/Living_Room.jpeg` | 139,818 bytes | `0ca7881210665e452322001a15bcf02ebdd6aedf9a4525a82676e1ea0fd805b5` |

**Confirmed byte-identical** (identical size, identical SHA-256). The pair
was **not deleted or modified** - `evaluation/image_similarity/benchmark.py
--margin-analysis` instead runs the property-level benchmark twice: RUN A
over all 39 images (identical to the pilot's original numbers), and RUN B
with the pair excluded from evaluation only (`metrics.exclude_records()` -
a pure in-memory filter; the source files on disk are untouched).

| Metric | SigLIP2 All | SigLIP2 Excl. Duplicate | Abs. Diff | DINOv2 All | DINOv2 Excl. Duplicate | Abs. Diff |
|---|---|---|---|---|---|---|
| Recall@1 | 0.564 | 0.541 | 0.024 | 0.179 | 0.135 | 0.044 |
| Recall@3 | 0.692 | 0.649 | 0.044 | 0.410 | 0.405 | 0.005 |
| Recall@5 | 0.872 | 0.838 | 0.034 | 0.564 | 0.514 | 0.051 |
| Recall@10 | 0.974 | 0.946 | 0.028 | 0.641 | 0.622 | 0.019 |
| MRR | 0.671 | 0.639 | 0.031 | 0.350 | 0.321 | 0.029 |

**Conclusion: the pilot result is NOT materially dependent on the trivial
duplicate.** Every absolute difference is small (≤0.05), and SigLIP2's
lead over DINOv2 is present and large in BOTH runs. The duplicate pair only
directly affects 2 of the 39 queries (both trivially "solved" by both
models, similarity ≈1.000 - see §2 below), and removing them changes
overall recall by a few percentage points at most, in the expected
direction (slightly lower without the "free" trivial match) for both
models roughly proportionally.

Full data: `results/pilot_margin_analysis.json` / `.md`.

## 2. Margin analysis (Parts B/C)

For every query image: `best_positive_similarity` (its single closest
same-house candidate), `best_negative_similarity` (its single closest
different-house candidate), `margin = best_positive − best_negative`.
**Raw similarity values are not compared between SigLIP2 and DINOv2** (they
are not calibrated against each other) - only each model's own ranking/
separation behavior is meaningful.

| Metric | SigLIP2 | DINOv2 |
|---|---|---|
| Queries (all valid - every house has ≥2 images) | 39 | 39 |
| Total positive candidate pairs | 196 | 196 |
| Total negative candidate pairs | 1286 | 1286 |
| Mean best-positive similarity | 0.881 | 0.390 |
| Mean best-negative similarity | 0.869 | 0.496 |
| **Mean margin** | **0.012** | **−0.106** |
| Median margin | 0.006 | −0.102 |
| % margin > 0 | 56.4% | 17.9% |
| % margin ≥ 0.05 | 28.2% | 12.8% |
| % margin ≥ 0.10 | 2.6% | 10.3% |

**Important nuance beyond the headline Recall@1 numbers**: SigLIP2's
positive margin is usually *thin* - mean margin is only 0.012, and only
2.6% of queries clear a 0.10 margin. SigLIP2 "wins" more often than DINOv2
(56.4% vs 17.9% of queries have margin > 0, which is exactly Recall@1 by
construction), but most of those wins are close calls, not decisive
separations. DINOv2's negative mean margin (−0.106) shows it more often
ranks a wrong-house image above the true same-house one on this pilot.

### Hard/strong queries (Part C) - deterministic selection, not cherry-picked

**SigLIP2 strongest:** `House_2/Living_Room.jpeg` (margin 0.133, genuine -
not duplicate-related) is the single strongest query, ahead of both
duplicate-pair queries (margin 0.095 each, flagged `duplicate_related`) -
i.e. SigLIP2's best result on this pilot is NOT the trivial duplicate.

**SigLIP2 hardest:** `House_6/Kitchen_room.jpeg` (margin −0.102, flagged
duplicate-related because its own best positive happens to be one of the
duplicate pair) and `House_3/Kitchen_Room.jpeg` (margin −0.084, genuine) -
kitchens across different houses are consistently confusable for SigLIP2.

**DINOv2 strongest:** dominated by the duplicate pair (margin 0.511 each -
far ahead of the next genuine entry, `House_7/Master_bedroom_1.jpeg` at
0.225) - DINOv2's single best "win" on this pilot is the trivial duplicate,
not a genuine visual-similarity finding.

**DINOv2 hardest:** `House_1/Bed_Room_1.jpeg` (margin −0.473), `House_3/
Kitchen_Room.jpeg` (−0.417), `House_5/Kitchen_Room.jpeg` (−0.395) - all
genuine (non-duplicate) failures, all considerably worse than SigLIP2's
hardest cases.

Full per-query data (all 39 queries × both models) in
`results/pilot_margin_analysis.json`; the 5-strongest/5-hardest tables with
full detail (best positive/negative image, both similarities, margin,
duplicate flag) are in `results/pilot_margin_analysis.md`.

## 3. 20-house benchmark — NOT YET AVAILABLE

`properties/House_9` through `properties/House_20` exist as directories but
contain **zero images** as of this analysis (verified directly, not
assumed - `dataset.scan_pilot_dataset()` reports `n_houses_empty: 12`,
unchanged from the original pilot). Per instructions, no fake, copied, or
auto-generated images were created to fill them.

**This benchmark is ready to run the moment real images are added** - no
code changes are needed. `dataset.scan_pilot_dataset()` already discovers
houses/images dynamically (it does not assume a fixed count), and both
`--pilot` and `--margin-analysis` will automatically pick up however many
houses/images exist at run time. Re-running at that point will populate
this section (and §4-6 below) with real 20-house numbers.

## 4. Pilot vs expanded benchmark — NOT YET AVAILABLE

Cannot be produced until §3's dataset exists. Placeholder structure this
section will use once it can be filled in:

```
                8 Houses (pilot)   20 Houses (expanded)
                ----------------   --------------------
Images                39                  ?
Recall@1               ?                  ?
Recall@3               ?                  ?
Recall@5               ?                  ?
Recall@10              ?                  ?
MRR                    ?                  ?
Mean margin             ?                  ?
Median margin           ?                  ?
Margin > 0              ?                  ?
```
(for both SigLIP2 and DINOv2)

## 5. Interpretation

On the 8-house/39-image pilot: SigLIP2 shows a consistent, duplicate-
independent property-level retrieval advantage over DINOv2 (§1), but the
margin analysis (§2) shows that advantage is often a narrow one, not an
overwhelming separation - "SigLIP2 usually wins by a little" is a more
accurate summary than "SigLIP2 clearly solves this." **Observed on this
benchmark, not proven in general.** No further interpretation is offered
here pending the 20-house data (§3/§4), which is the next real test of
whether this pattern holds.

## 6. Limitations

1. Everything in §1/§2 above is still measured on the SAME 8-house/39-image
   pilot as before - it re-analyzes the existing result, it does not add
   new data.
2. The 20-house expansion (§3) this analysis was meant to also cover is not
   yet possible - `House_9`-`House_20` are still empty.
3. Margin values are specific to each model's own embedding-space geometry
   (§2) and must never be compared as if they were calibrated probabilities
   between SigLIP2 and DINOv2 - only within-model comparisons (this pilot
   vs a future larger run, same model) are meaningful.
4. CPU-only measurements throughout (no GPU on this machine) - unchanged
   caveat from the original pilot report.
5. As before: 8 houses / 39 images remains too small a sample for a
   production model decision. The margin analysis in §2, if anything,
   reinforces this - SigLIP2's average winning margin (0.012) is small
   enough that a slightly different sample of houses could plausibly
   narrow or reverse it. **The evidence gathered so far is not yet strong
   enough to move to production integration** (see also the original
   pilot's §15/§16 above, which already said the same thing before this
   analysis).

## Duplicate sensitivity & margin analysis files

- `results/pilot_margin_analysis.json` - full machine-readable output:
  dataset summary, duplicate verification, the RUN A/RUN B sensitivity
  table, and per-model margin analysis + hard/strong queries (including
  every individual query's full per-query record, not just the top 5s).
- `results/pilot_margin_analysis.md` - human-readable version of the same.

## How to run

```bash
python evaluation/image_similarity/benchmark.py --margin-analysis
```

---

# Phase 6 — Dataset Standardization & Expanded Benchmark (21 houses / 84 images)

This section documents a THIRD round of work: the team collected additional
real property photos (a second batch, in a different naming style), the
combined dataset was standardized onto one consistent naming convention, and
the exact same benchmark protocol above was re-run on the larger dataset.
**All historical pilot findings above (8 houses/39 images, and the duplicate/
margin analysis on that same 39-image set) are preserved as written and are
not revised by this section** - this is a new, later measurement, not a
correction of the earlier ones.

## 1. Standardized naming convention

**Before standardization**, `properties/` contained TWO naming styles:
`House_1`..`House_9` (the original pilot batch, filenames like
`Bed_Room.jpeg`, `Living_Room_1.jpeg`) and `HOUSE1`..`HOUSE12` (a newer batch
collected by the team, filenames like `bathroom.jpg`, `living.jpeg`).

**Inspection before any renaming** (`evaluation/image_similarity/
rename_dataset.py`'s dry run, `results/dataset_rename_manifest.json`):
84 image files across 21 house directories. Byte-for-byte SHA-256 hashing
confirmed `HOUSE1`..`HOUSE12` are NOT the same properties as `House_1`..
`House_9` re-uploaded under a different name - every hash in one batch is
absent from the other. They are 21 genuinely distinct properties, not 9.

**After standardization**, every house directory is `House_<NNN>` (zero-
padded, 3 digits) and every image filename is `<category>_<NN>.<original
extension>` (lowercase snake_case category, zero-padded 2-digit view
number). Original bytes were never touched - renaming was a pure filesystem
move (`os.rename`), verified afterward by re-hashing every file and
confirming every SHA-256 and byte size is unchanged (see §8).

## 2. House / view semantics

- **House folder mapping**: old-style houses kept their existing relative
  order (`House_1`→`House_001` ... `House_9`→`House_009`); new-style houses
  continue the numbering from `House_010` onward in THEIR own embedded
  number order (`HOUSE1`→`House_010` ... `HOUSE12`→`House_021`). This was a
  deliberate choice to avoid a real collision: naively mapping by embedded
  number alone would have sent both `House_1` and `HOUSE1` to `House_001`,
  silently merging two different real properties. Full mapping in
  `results/dataset_rename_manifest.json`.
- **View numbers** (`_01`, `_02`, ...) mean "same room, different photographed
  angle" - NEVER a different room. `Living_Room.jpeg`, `Living_Room_1.jpeg`,
  `Living_Room_2.jpeg` → `living_room_01.jpg`, `_02`, `_03` (same living
  room, three angles). Numbering always normalizes to start at 01, even when
  the original files only had `_1`/`_2` suffixes with no bare/zero file
  (e.g. House_007's `Master_bedroom_1.jpeg`/`Master_Bedroom_2.jpeg` →
  `master_bedroom_01.jpeg`/`_02.jpeg`).
- **Category mapping** (built from the exact tokens found on disk, not
  invented): `bed_room`/`bedroom` → `bedroom`; `living_room`/`living` →
  `living_room`; `kitchen_room`/`kitchen` → `kitchen`; `bath_room`/`bathroom`
  → `bathroom`; `master_bedroom` and `common_bed_room` kept as their own
  distinct categories (`master_bedroom`, `common_bedroom`) - never merged
  into plain `bedroom`, per instructions. `sit_out`, `balcony`,
  `devotional_room` map to themselves.
- **Extensions were preserved exactly as found** - `.jpg` stays `.jpg`,
  `.jpeg` stays `.jpeg`; nothing was recompressed or converted.

## 3. Ambiguous filenames — flagged, not guessed

Two original filenames were genuinely compound/ambiguous room names and
were **not** force-mapped to either component category:

- `House_6/Parking or sit_out.jpeg` (now `House_006/needs_review_01.jpeg`)
- `House_9/sit_out or balcony.jpeg` (now `House_009/needs_review_01.jpeg`)

Both were renamed with the placeholder category `needs_review` (view number
still assigned deterministically) - the images are fully preserved and
still participate in property-level evaluation (their HOUSE identity is not
in question), but they are **excluded from category-level evaluation**
(their room-type metadata isn't reliable enough to group by). This needs a
human decision, not an automated guess.

## 4. Final dataset size

**21 houses, 84 images** (up from the original pilot's 8 houses/39 images).

| House | Images | | House | Images | | House | Images |
|---|---|---|---|---|---|---|---|
| House_001 | 4 | | House_008 | 4 | | House_015 | 3 |
| House_002 | 4 | | House_009 | 4 | | House_016 | 2 |
| House_003 | 3 | | House_010 | 3 | | House_017 | 4 |
| House_004 | 5 | | House_011 | 1 | | House_018 | 4 |
| House_005 | 4 | | House_012 | 4 | | House_019 | 4 |
| House_006 | 4 | | House_013 | 4 | | House_020 | 4 |
| House_007 | 11 | | House_014 | 4 | | House_021 | 4 |

Min images/house: **1** (`House_011` - only a single bedroom photo; correctly
excluded from property-level evaluation as "no possible positive candidate",
not silently scored as a miss). Max: **11** (`House_007`). Mean: **4.00**.
Median: **4**. Per instructions, no house was padded, balanced, or dropped
to make the distribution more even.

Category totals: `bedroom` 21, `living_room` 22, `kitchen` 19, `bathroom`
11, `common_bedroom` 2, `master_bedroom` 2, `sit_out` 2, `balcony` 2,
`devotional_room` 1, `needs_review` 2 (excluded from category-level - §3).

Full detail: `results/dataset_summary.md`.

## 5. Duplicate findings

Exactly **one** byte-identical duplicate group in the full 84-image
dataset (re-verified via independent SHA-256 recomputation, not just
trusting the scan's cached hash) - the same one found in the original
8-house pilot, now under its standardized name:

`House_006/bedroom_01.jpeg` ≡ `House_006/living_room_01.jpeg`
(SHA-256 `0ca7881210665e...fd805b5`, 139,818 bytes, confirmed identical).

No NEW duplicates were introduced by the second (HOUSE1-12) batch.

## 6. Evaluation protocol (unchanged)

Identical to the original pilot: SigLIP2 (`google/siglip2-base-patch16-224`,
loaded via `AutoModel`/`get_image_features()` - see the original pilot
section above for why `AutoModel` rather than the newer `Siglip2Model`
class) and DINOv2 (`facebook/dinov2-base`, `pooler_output`), both pretrained-
only, L2-normalized embeddings, cosine similarity, leave-one-out property-
level retrieval (positive = same house, any room type; negative = every
other house; query excluded from its own gallery). No checkpoints changed,
no fine-tuning, no new models introduced.

## 7. SigLIP2 results (21 houses / 84 images)

| | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|---|
| Property-level (83 valid queries) | 0.434 | 0.590 | 0.663 | 0.831 | 0.550 |
| Category-level (81 valid queries) | 0.593 | 0.901 | 0.963 | 0.963 | - |

Margin analysis (property-level, all 84 images, full dataset): mean best-
positive similarity 0.854, mean best-negative similarity 0.869, **mean
margin −0.015**, median margin −0.016, 43.4% of queries have margin > 0
(= Recall@1), 13.3% ≥ 0.05, 1.2% ≥ 0.10. 318 total positive candidate
pairs, 6,571 total negative candidate pairs.

Device: CPU. Embedding dimension: 768. Model load: 2.66s (cached weights).
Avg embedding latency: 0.296s/image.

## 8. DINOv2 results (21 houses / 84 images)

| | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|---|
| Property-level (83 valid queries) | 0.072 | 0.217 | 0.337 | 0.434 | 0.204 |
| Category-level (81 valid queries) | 0.716 | 0.840 | 0.877 | 0.938 | - |

Margin analysis: mean best-positive similarity 0.339, mean best-negative
similarity 0.591, **mean margin −0.252**, median margin −0.227, 7.2% of
queries have margin > 0, 7.2% ≥ 0.05, 4.8% ≥ 0.10. Same candidate-pair
totals as SigLIP2 (318 positive / 6,571 negative - identical dataset).

Device: CPU. Embedding dimension: 768. Model load: 2.25s. Avg embedding
latency: 0.317s/image.

**Note the category-level reversal**: at Recall@1, DINOv2 (0.716) now
edges out SigLIP2 (0.593) - the opposite of the original 8-house pilot,
where category Recall@1 was exactly tied (0.657 vs 0.657). At Recall@3/5/10
SigLIP2 still leads on category-level too. See §11 for discussion - this is
a genuinely new, non-obvious observation from the expanded dataset, not
something the smaller pilot could have shown.

## 9. Duplicate-exclusion sensitivity (RUN A vs RUN B, 21-house dataset)

| Metric | SigLIP2 All | SigLIP2 Excl. Dup | Diff | DINOv2 All | DINOv2 Excl. Dup | Diff |
|---|---|---|---|---|---|---|
| Recall@1 | 0.434 | 0.420 | 0.014 | 0.072 | 0.049 | 0.023 |
| Recall@3 | 0.590 | 0.568 | 0.022 | 0.217 | 0.210 | 0.007 |
| Recall@5 | 0.663 | 0.642 | 0.021 | 0.337 | 0.321 | 0.016 |
| Recall@10 | 0.831 | 0.815 | 0.017 | 0.434 | 0.407 | 0.026 |
| MRR | 0.550 | 0.533 | 0.017 | 0.204 | 0.186 | 0.018 |

Same conclusion as the original pilot: **the duplicate does not materially
drive the result** - every difference is small (≤0.026), well within what
one trivial pair would be expected to contribute out of 84 images.

Full data: `results/pilot_margin_analysis.json` / `.md`.

## 10. Previous 8-house pilot vs 21-house expanded benchmark

```
                    8 Houses (pilot)    21 Houses (expanded)
                    ----------------    ---------------------
Images                     39                    84
Recall@1  (SigLIP2)      0.564                 0.434
Recall@1  (DINOv2)       0.179                 0.072
Recall@3  (SigLIP2)      0.692                 0.590
Recall@3  (DINOv2)       0.410                 0.217
Recall@5  (SigLIP2)      0.872                 0.663
Recall@5  (DINOv2)       0.564                 0.337
Recall@10 (SigLIP2)      0.974                 0.831
Recall@10 (DINOv2)       0.641                 0.434
MRR       (SigLIP2)      0.671                 0.550
MRR       (DINOv2)       0.350                 0.204
Mean margin (SigLIP2)    0.012                -0.015
Mean margin (DINOv2)    -0.106                -0.252
Median margin (SigLIP2)  0.006                -0.016
Median margin (DINOv2)  -0.102                -0.227
Margin > 0  (SigLIP2)    56.4%                 43.4%
Margin > 0  (DINOv2)     17.9%                  7.2%
```

**Both models' absolute recall dropped** on the larger dataset. This is
expected, not a red flag: property-level retrieval gets strictly harder as
more houses are added, because each query now has ~20 other houses' worth
of negative candidates instead of ~7 - purely mechanically, the single best
negative (a max over a larger pool) tends to score higher, which is exactly
why mean margin went negative for both models even though nothing about the
embeddings themselves changed. **Observed on this benchmark:**

1. **Did SigLIP2's lead remain?** Yes, clearly - at every Recall@K and on
   MRR, SigLIP2 is still well ahead of DINOv2.
2. **Did the lead shrink?** In absolute percentage-point terms, the Recall@1
   gap narrowed slightly (0.385 → 0.362 points), but...
3. **Did the lead increase?** ...in *relative* terms it widened: SigLIP2's
   Recall@1 is now ~6.0× DINOv2's (was ~3.15× in the pilot).
4. **Did either model become unstable?** No crashes, no missing data (both
   models processed all 84 images and produced valid embeddings for every
   one); DINOv2's margin distribution shifted further negative but not
   erratically - it degraded smoothly, same direction as SigLIP2.
5. **Did hard queries change?** Yes, and consistently across both models:
   bathroom photos from the newer (HOUSE1-12) batch (`House_014`,
   `House_017`, `House_019`, `House_021`) now dominate BOTH models' hardest-
   query lists - a genuinely new finding the 8-house pilot could not have
   surfaced (it had far fewer bathroom photos). See §11.
6. **Did duplicate exclusion materially affect the original pilot?** No -
   confirmed again on the larger dataset (§9), consistent with the original
   pilot's own conclusion.
7. **Did category performance differ from property-level performance?**
   Yes, sharply - category-level Recall@1 (0.59-0.72) is now noticeably
   HIGHER than property-level Recall@1 (0.07-0.43) for both models. This
   makes sense: finding "any other kitchen photo, from any house" is an
   easier task than finding "specifically this house's other photos" -
   property identity is a harder, more specific signal than room category.

**No production winner is declared from this.** SigLIP2's lead is
consistent and has now been observed on two independently-checked dataset
sizes, which is stronger evidence than the 8-house pilot alone - but 21
houses remains a modest sample, and the newly-surfaced bathroom-confusion
pattern (§11) shows there are still specific, systematic failure modes
worth understanding before any production commitment.

## 11. Qualitative retrieval findings (21-house dataset)

Full top-10 results for every one of the 84×2 queries are in
`results/retrieval_examples.json` (bumped from top-5 to top-10 for this
round, specifically so "not found even in top-10" failures - explicitly
required for this analysis - are directly visible, not just inferred from
a Recall@10 number).

- **Clear success (SigLIP2)**: `House_001/bedroom_02.jpeg` → top-1
  `House_001/bedroom_01.jpeg` (0.847) - two angles of the same actual room,
  correctly matched, exactly the "multiple angles of the same room" case
  this dataset is full of.
- **Difficult case (SigLIP2)**: `House_001/bedroom_01.jpeg`'s top-1 is
  `House_004/bedroom_01.jpeg` (0.888, WRONG house, same category) - a
  same-room-type-but-wrong-property confusion, exactly the failure mode
  property-level evaluation is designed to catch (category-level alone
  would have scored this a "success").
- **Failure, correct house not in top-10 (SigLIP2)**: `House_003/
  kitchen_01.jpeg` - its entire top-10 is other houses' kitchens
  (`House_004` 0.917, `House_009` 0.905, `House_006` 0.896, ...); `House_003`
  never appears. Kitchens across this dataset are frequently more similar
  to each other, by SigLIP2, than to their own house's other rooms.
- **Clear success, genuine (not the trivial duplicate) (DINOv2)**: `House_007/
  common_bedroom_02.jpeg` → top-1 `House_007/master_bedroom_01.jpeg`
  (0.698) - correct property, different room type, still found.
- **Same-category, wrong-property (DINOv2)**: `House_001/kitchen_01.jpeg`
  → top-1 `House_008/kitchen_01.jpeg` (0.612, wrong house).
- **Failure, correct house not in top-10 (DINOv2)**: `House_001/
  bedroom_01.jpeg` - top-10 dominated by unrelated living rooms/kitchens
  from other houses (`House_020` 0.521, `House_021` 0.477, `House_007`
  0.443, ...); `House_001`'s own other bedroom photo never appears in the
  top 10 despite existing in the dataset.
- **Multiple angles of the same room (both models)**: `House_004/
  living_room_02.jpeg` → top-1 `House_004/living_room_01.jpeg` (correct,
  SigLIP2) demonstrates the intended "different angle, same room, same
  house" positive case working as designed; `House_004/bedroom_02.jpeg` →
  top-1 `House_008/bedroom_01.jpeg` (WRONG house, SigLIP2) shows the same
  multi-angle setup can still fail when another house's bedroom is visually
  closer than the query's own second angle.

Representative (deterministically selected, not cherry-picked) examples
for both models are also in `results/pilot_summary.md`.

## 12. Limitations

1. 21 houses is larger than the original pilot but still a modest sample -
   the same "observed on this benchmark, not proven in general" caveat
   applies, arguably even more so now that a new failure pattern (bathroom
   confusion) has emerged that a still-larger sample might explain or
   contradict.
2. Two images (`needs_review` category, §3) have uncertain room-type
   metadata and were excluded from category-level evaluation - a human
   should resolve what they actually depict.
3. `House_011` has only 1 image and contributes nothing to property-level
   evaluation (no possible positive candidate) - not an error, just a
   real, expected consequence of an uneven, unpadded, unbalanced dataset.
4. Margin values dropped for BOTH models as the negative pool grew (§10) -
   this is a property of the evaluation protocol (more candidates → a
   larger max), not evidence the embeddings got worse; comparing margins
   across different dataset SIZES (8-house vs 21-house) needs this caveat
   even more than comparing within one dataset size.
5. CPU-only measurements, as before.
6. The newly-observed bathroom cross-house confusion (§11) is a concrete,
   specific, and consistent pattern across both models and worth
   investigating further (e.g. do these bathroom photos share unusual
   visual similarity - same tile style, same generic composition - for a
   reason unrelated to model quality?) before drawing conclusions about
   either model's real-world bathroom-retrieval capability.
7. As before: **no production model decision is made here.** SigLIP2's
   lead is now supported by two independently-run dataset sizes with
   consistent direction, which is more evidence than before, but the
   sample is still modest and a new, unexplained failure pattern just
   emerged - the honest conclusion is "stronger but not yet sufficient
   evidence," not "sufficient evidence."

## Standardization & expanded-benchmark files

- `results/dataset_rename_manifest.json` - the complete pre-rename ->
  post-rename mapping for every one of the 84 images (original house/
  filename, standardized house/filename, category, view number, SHA-256
  and size before renaming).
- `results/dataset_summary.md` - houses, images, per-house/per-category
  counts, min/max/mean/median images-per-house.
- `results/pilot_results.json` / `pilot_summary.md` - re-generated on the
  21-house dataset (property-level + category-level metrics, resource
  measurements, qualitative examples) - same files/format as the original
  pilot, now reflecting the expanded data.
- `results/retrieval_examples.json` - complete top-10 (bumped from top-5)
  results for all 84×2 queries.
- `results/pilot_margin_analysis.json` / `.md` - re-generated duplicate
  verification, RUN A/RUN B sensitivity, margin analysis, and hard/strong
  queries on the 21-house dataset.

## How to reproduce

```bash
# 1. Inspect + (re-)standardize the dataset (safe: dry run by default)
python evaluation/image_similarity/rename_dataset.py
python evaluation/image_similarity/rename_dataset.py --execute   # only after reviewing the dry run

# 2. Re-run the exact same benchmark protocol
python evaluation/image_similarity/benchmark.py --pilot
python evaluation/image_similarity/benchmark.py --margin-analysis
```

---

# Phase 6 — Error Analysis of the 21-House Benchmark

Analysis-only pass over the EXISTING 21-house results above - no model was re-run,
no checkpoint or metric implementation changed (`evaluation/image_similarity/
error_analysis.py` is pure post-processing of `retrieval_examples.json` /
`pilot_results.json` / `pilot_margin_analysis.json`, plus direct visual inspection
of specific images). Full detail in each linked file; this section is the summary.

## Most important finding: dataset provenance

Direct visual inspection of the `House_010`-`House_021` batch (all 12 houses, 2+
categories sampled each) found a **visible "magicbricks" watermark in every single
sampled image**, with none found in three sampled images from the original
`House_001`-`House_009` batch. This strongly suggests the newer batch was sourced
from a real-estate listing site rather than personally photographed. **12 of
SigLIP2's 14 top-10 retrieval failures (85.7%) are confusions entirely within this
watermarked batch** - a rate far above its 57% share of houses. This is flagged as
an unresolved, open item for the team (see `results/failure_taxonomy.md` and
`results/model_assessment.md` Goal 12, item 4/7) - it is not something this analysis
can resolve on its own, and nothing in the dataset was changed because of it.

## Valid query accounting

84 total images = 84 potential queries. **83 valid property-level queries** (1
excluded: `House_011` has only 1 image, so it has no possible same-house positive
candidate - correctly excluded by the existing metric, not scored as a miss; no
other house has only 1 image). The existing `metrics.evaluate_grouped_retrieval()`
implementation already handles this correctly - **no bug found, nothing changed.**

## Needs-review images

Both `needs_review` images were inspected directly (`results/needs_review_analysis.md`):
`House_006`'s (was `"Parking or sit_out.jpeg"`) shows a covered entrance/storage
passage that doesn't clearly match either original candidate - kept `needs_review`,
LOW confidence for any label. `House_009`'s (was `"sit_out or balcony.jpeg"`) shows
a furnished, railed high-floor balcony - `balcony` proposed, MEDIUM confidence.
Neither file was renamed.

## Bathroom & kitchen failures dominate

SigLIP2's top-10 failure rate by category: **bathroom 45.5%** (5/11), **kitchen
36.8%** (7/19), bedroom 10% (2/20), every other category 0%. DINOv2's bathroom
Recall@1 is 0.0 (0/11) and Recall@10 only 0.091. Visual inspection
(`results/bathroom_analysis.md`) found the watermarked batch's bathroom photos
share near-identical camera framing, tiling, and lighting conventions - consistent
with listing photography rather than personal photos, and a plausible explanation
for the cross-house confusion (see "dataset provenance" above).

## Per-house and failure-taxonomy detail

`results/per_house_analysis.md` ranks all 21 houses by SigLIP2 top-10 failure
count; the hardest (`House_014`, `House_018` - 0.0 Recall@1, 3/4 failures each) and
easiest (`House_002`, `House_007`, `House_009` - Recall@1 ≥ 0.75) are identified with
full per-house Recall@K, avg rank, and failure counts for both models.
`results/failure_taxonomy.md` classifies all 14 SigLIP2 failures by evidence-based
codes (A=same-category-wrong-house: 14/14; D=house has ≤3 images: 3/14;
E=both houses in the watermarked batch: 12/14) - no failure was forced into a
category without support, and none needed the "Unclear" fallback.

## Model comparison, revisited (`results/model_assessment.md`)

SigLIP2's property-level lead over DINOv2 holds at both 8-house and 21-house sizes
and widens in relative terms (~3.15× → ~6.0× on Recall@1); the duplicate does not
materially affect either model or the ranking between them (≤0.026 difference on
every metric). Category-level Recall@1 actually now favors DINOv2 (0.716 vs 0.593) -
underscoring that property-level and category-level measure genuinely different
things, and property-level is the one that matches SmartHomes' actual requirement
("find similar properties," not "find similar room types").

## Production readiness (GREEN / YELLOW / RED - see `results/model_assessment.md` Goal 12)

**GREEN**: property-level signal consistent across dataset sizes; duplicate not
material; SigLIP2 currently the leading candidate. **YELLOW**: dataset size still
modest for a confident (not just preliminary) call; the bathroom/kitchen failure
pattern is characterized but its root cause not fully isolated from the provenance
question. **RED**: the watermarked-batch provenance question is unresolved and is
this analysis's single biggest open item - it should be resolved with the team
before placing full confidence in the 21-house numbers.

**No production integration was performed or recommended. This remains analysis only.**

## Error-analysis files

- `results/needs_review_analysis.md` - Goal 2.
- `results/bathroom_analysis.json` / `.md` - Goals 3-4.
- `results/siglip2_failure_analysis.json` / `.md` - Goal 5.
- `results/per_house_analysis.md` - Goal 6.
- `results/failure_taxonomy.md` - Goal 7 (includes the manual watermark finding).
- `results/model_assessment.md` - Goals 8-12.

## How to reproduce

```bash
python evaluation/image_similarity/error_analysis.py
```
(Pure post-processing of already-existing result files - completes in well under a
second, no model download or embedding computation.)
