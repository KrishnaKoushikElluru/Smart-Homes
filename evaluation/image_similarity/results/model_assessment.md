# Model Assessment — 21-House Benchmark (Goals 9–12)

Analysis-only. Uses the EXISTING benchmark results (`pilot_results.json`,
`pilot_margin_analysis.json`, `retrieval_examples.json`) - no model was re-run, no
checkpoint changed, no metric implementation changed.

## Goal 9 — Model comparison (21 houses / 84 images)

### Property-level (PRIMARY metric for SmartHomes)

| | Recall@1 | Recall@3 | Recall@5 | Recall@10 | MRR |
|---|---|---|---|---|---|
| SigLIP2 | 0.434 | 0.590 | 0.663 | 0.831 | 0.550 |
| DINOv2 | 0.072 | 0.217 | 0.337 | 0.434 | 0.204 |

### Category-level (secondary, explanatory)

| | Recall@1 | Recall@3 | Recall@5 | Recall@10 |
|---|---|---|---|---|
| SigLIP2 | 0.593 | 0.901 | 0.963 | 0.963 |
| DINOv2 | 0.716 | 0.840 | 0.877 | 0.938 |

### Margin (property-level, all 84 images)

| | Mean margin | Median margin | Margin > 0 | Margin ≥ 0.05 | Margin ≥ 0.10 |
|---|---|---|---|---|---|
| SigLIP2 | −0.015 | −0.016 | 43.4% | 13.3% | 1.2% |
| DINOv2 | −0.252 | −0.227 | 7.2% | 7.2% | 4.8% |

### Property retrieval vs. category retrieval - why this distinction matters

- **Property retrieval** answers: *"given this photo, which OTHER photos are of the
  SAME physical house?"* - regardless of room type. This is what SmartHomes actually
  needs: reference image → visually similar **properties**, so a user can find other
  listings that look like the one they're picturing.
- **Category retrieval** answers a different, easier question: *"given this photo of
  a kitchen, which OTHER photo is also a kitchen?"* - regardless of which house it's
  from. This is a room-type classifier's job, not a property-similarity job.
- These are NOT the same, and the 21-house data shows exactly why they diverge:
  DINOv2 now has a HIGHER category-level Recall@1 (0.716) than SigLIP2 (0.593), yet a
  dramatically LOWER property-level Recall@1 (0.072 vs 0.434). DINOv2 is relatively
  good at "this is generically a bathroom" and poor at "this is specifically THIS
  house." SigLIP2 shows the opposite balance. **Property-level is the metric that
  matters for the SmartHomes use case; category-level is reported only because it
  helps explain WHY failures happen (see bathroom_analysis.md, failure_taxonomy.md).**

## Goal 8 — Duplicate sensitivity (existing results, not re-run)

From `pilot_margin_analysis.json` (RUN A = all 84 images, RUN B = the known
`House_006/bedroom_01.jpeg` ≡ `House_006/living_room_01.jpeg` pair excluded):

| Metric | SigLIP2 All | SigLIP2 Excl. Dup | Diff | DINOv2 All | DINOv2 Excl. Dup | Diff |
|---|---|---|---|---|---|---|
| Recall@1 | 0.434 | 0.420 | 0.014 | 0.072 | 0.049 | 0.023 |
| Recall@3 | 0.590 | 0.568 | 0.022 | 0.217 | 0.210 | 0.007 |
| Recall@5 | 0.663 | 0.642 | 0.021 | 0.337 | 0.321 | 0.016 |
| Recall@10 | 0.831 | 0.815 | 0.017 | 0.434 | 0.407 | 0.026 |
| MRR | 0.550 | 0.533 | 0.017 | 0.204 | 0.186 | 0.018 |

**Does it materially affect SigLIP2?** No - largest diff 0.022 (Recall@3).
**Does it materially affect DINOv2?** No - largest diff 0.026 (Recall@10), similarly small.
**Does the ranking between models change?** No - SigLIP2 leads DINOv2 by a wide
margin on every metric in BOTH runs; excluding the duplicate does not close the gap
meaningfully in either direction.

## Goal 10 — 8-house pilot vs. 21-house expanded benchmark

```
                    8 Houses (pilot)    21 Houses (expanded)
Images                     39                    84
Recall@1  SigLIP2         0.564                 0.434
Recall@1  DINOv2          0.179                 0.072
Recall@3  SigLIP2         0.692                 0.590
Recall@3  DINOv2          0.410                 0.217
Recall@5  SigLIP2         0.872                 0.663
Recall@5  DINOv2          0.564                 0.337
Recall@10 SigLIP2         0.974                 0.831
Recall@10 DINOv2          0.641                 0.434
MRR       SigLIP2         0.671                 0.550
MRR       DINOv2          0.350                 0.204
```

**Why absolute recall decreased**: two compounding, DIFFERENT reasons, both
evidenced (not just assumed):

1. **Mechanical / expected**: each query's negative pool grew from ~7 other houses'
   images (8-house pilot) to ~20 other houses' worth (21-house). Recall@K and margin
   are both sensitive to gallery size - the best-ranked NEGATIVE is a maximum over
   more candidates, so it mechanically tends to score higher even if the embeddings
   themselves are unchanged. This alone would predict SOME recall drop.
2. **Dataset-specific, evidenced by direct visual inspection (new this analysis)**:
   the entire second batch (`House_010`-`House_021`, 12 of 21 houses) shows a visible
   "magicbricks" watermark in every sampled image and a visually homogeneous,
   listing-photography style - see `failure_taxonomy.md`'s manual-inspection
   section. 12 of SigLIP2's 14 top-10 failures (85.7%) are confusions BETWEEN two
   houses that are BOTH in this batch, a rate far higher than the batch's 57% share
   of all houses would predict by chance alone. This means the recall drop is not
   purely a "bigger gallery" mechanical effect - a meaningful part of it is this
   batch's photos looking unusually similar to EACH OTHER specifically.

**Does SigLIP2's relative advantage persist?** Yes, clearly, on every property-level
metric at every K. In relative terms it is now LARGER: SigLIP2's Recall@1 is ~6.0×
DINOv2's (was ~3.15× in the 8-house pilot).

**Did DINOv2 degrade more strongly?** Yes, on property-level - DINOv2's Recall@1
dropped by 59.8% relatively (0.179→0.072) vs. SigLIP2's 23.0% (0.564→0.434). DINOv2's
mean margin fell further into negative territory too (−0.106→−0.252 vs. SigLIP2's
0.012→−0.015).

**Do the results support continuing with SigLIP2 as the leading candidate?**
**Observed on the SmartHomes benchmark**: yes - SigLIP2 leads on every property-level
metric, at both dataset sizes, and the margin/DINOv2-degradation evidence adds
weight rather than contradicting it. This is not proof of general superiority (see
Goal 12) - it is a consistent, repeated observation on this specific benchmark.

## Goal 11 — Qualitative visual review (10 representative examples, not cherry-picked)

All drawn directly from `retrieval_examples.json`; selection criteria stated for each.

1. **SigLIP2 clear success**: `House_001/bedroom_02.jpeg` → top-1
   `House_001/bedroom_01.jpeg` (0.847, correct). Two angles of the literal same room.
2. **SigLIP2 difficult success**: `House_004/bedroom_02.jpeg` → top-1
   `House_008/bedroom_01.jpeg` (WRONG house) but correct property DOES appear later
   in top-10 - a genuinely close call, not a clean win.
3. **SigLIP2 top-10 failure**: `House_003/kitchen_01.jpeg` - top-10 entirely other
   houses' kitchens (`House_004` 0.917 → `House_009` 0.905 → `House_006` 0.896 →
   ...); `House_003` never appears.
4. **DINOv2 clear success (genuine, not the trivial duplicate)**:
   `House_007/common_bedroom_02.jpeg` → top-1 `House_007/master_bedroom_01.jpeg`
   (0.698, correct property, different room type).
5. **DINOv2 difficult case**: `House_005/sit_out_01.jpeg` → top-1
   `House_005/bedroom_01.jpeg` (0.480, correct property but very different room
   type - only a modest margin over the best wrong-house candidate).
6. **Same-category, wrong-property retrieval**: `House_001/bedroom_01.jpeg`
   (SigLIP2) → top-1 `House_004/bedroom_01.jpeg` (0.888, WRONG house, same
   category=bedroom) - exactly the failure mode property-level evaluation exists to
   catch; category-level scoring alone would have called this correct.
7. **Bathroom failure**: `House_014/bathroom_01.jpg` (SigLIP2) → top-1
   `House_018/bathroom_01.jpg` (0.887, wrong house, same category) - full top-5 is
   `House_018, House_019, House_017, House_021, House_010` bathrooms, ALL from the
   watermarked batch, `House_014`'s own second angle... (House_014 in fact only has
   1 bathroom photo) never appears.
8. **Multiple angles of the same room, success**: `House_004/living_room_02.jpeg` →
   top-1 `House_004/living_room_01.jpeg` (correct, SigLIP2) - the "different angle,
   same room" positive case working exactly as the protocol intends.
9. **Hardest property**: `House_014` (SigLIP2 Recall@1 = 0.0, 3 of 4 queries fail in
   top-10; see `per_house_analysis.md`). Query `House_014/bathroom_01.jpg`'s top-5
   are ALL other watermarked-batch bathrooms (0.887 down to 0.851) with no
   `House_014` image anywhere in the top-10.
10. **Easiest property**: `House_002` (SigLIP2 Recall@1 = 1.0 across all 4 valid
    queries). Query `House_002/living_room_01.jpeg` → top-1
    `House_002/bedroom_01.jpeg` (0.893, correct), top-2 `House_002/kitchen_01.jpeg`
    (0.842, correct) - the model finds House_002's OTHER rooms well ahead of any
    other house's living room (next result: `House_009`, 0.779).

## Goal 12 — Production readiness assessment

**GREEN = sufficiently understood, YELLOW = needs investigation, RED = unresolved blocker.**

| # | Question | Status | Basis |
|---|---|---|---|
| 1 | Is the dataset large enough for a PRELIMINARY model selection? | **YELLOW** | 21 houses/84 images gives a consistent signal across two dataset sizes, which is more than a single small pilot - but still modest, and half the dataset (the watermarked batch) has an unresolved provenance question (#4). "Preliminary," not "confident," is the honest label. |
| 2 | Is the property-level signal consistent across 8 and 21 houses? | **GREEN** | Yes - SigLIP2 leads DINOv2 on every property-level metric at both sizes, and the relative gap widened, not reversed or vanished (Goal 10). |
| 3 | Is the duplicate materially affecting results? | **GREEN** | No - RUN A vs. RUN B differs by ≤0.026 on every metric for both models (Goal 8 / `pilot_margin_analysis.json`); SigLIP2's lead over DINOv2 holds in both runs. |
| 4 | Are there unresolved data-quality problems? | **RED** | Yes - the House_010-House_021 batch (12 of 21 houses, 57% of the dataset) shows a "magicbricks" watermark in every sampled image, strongly suggesting an external/listing source rather than personal photography. Whether these represent 12 genuinely distinct properties is not verifiable from the images and needs the team to confirm. This is a blocker for treating the 21-house numbers as clean, not just a note. |
| 5 | Are there systematic failure modes? | **YELLOW** | Yes, and now characterized: bathroom (45.5% SigLIP2 failure rate) and kitchen (36.8%) dominate; both concentrate almost entirely (12/14 = 85.7%) within the watermarked batch (Goal 5/7). This is well-understood as a PATTERN but its ROOT CAUSE (photography style vs. genuine visual confusability vs. dataset provenance) is not yet fully separated from #4. |
| 6 | Is SigLIP2 currently the leading candidate? | **GREEN** | Yes, per the actual measured evidence at both dataset sizes (Goal 9/10) - stated as an observation on this benchmark, not a general claim. |
| 7 | What evidence is still missing before production integration? | **RED** (as an open item, not a single measurement) | (a) Team confirmation of what House_010-House_021's images actually are and whether they're genuinely 12 distinct properties; (b) a dataset with more houses AND without the watermark/provenance confound, to isolate whether the bathroom/kitchen failure pattern is intrinsic to the visual task or an artifact of this specific batch; (c) the two `needs_review` images resolved by a human (`needs_review_analysis.md`); (d) GPU-latency numbers (everything so far is CPU-only, explicitly not representative of production latency). |

**No overall score or ranking is produced, per instructions.** The single most
important unresolved item is #4/#7(a) - the dataset provenance question - since it
affects how much confidence to place in every other number in this report.
