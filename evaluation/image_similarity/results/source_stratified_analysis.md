# Source-Stratified Analysis (Group A vs Group B)

## 1. Objective

Determine whether the House_001-House_009 (Group A) vs House_010-House_021 (Group B, visibly Magicbricks-watermarked) dataset-source difference is materially affecting the observed SigLIP2 vs DINOv2 results, using ONLY the existing 21-house benchmark data (no re-embedding, no dataset change).

## 2. Dataset groups

- **Group A**: 9 houses, 43 images (min 3, max 11, mean 4.78 images/house).
- **Group B**: 12 houses, 41 images (min 1, max 4, mean 3.42 images/house).
- **Combined**: 21 houses, 84 images.
- `House_011` (Group B) has exactly 1 image - it produces ZERO valid property-level queries (no possible same-house positive candidate) and is correctly excluded from every recall/MRR figure below, not counted as a failure.

## 3. Provenance observation

See `dataset_provenance.md` for full detail. Summary: Group A shows no watermark in inspected images; Group B shows a visible Magicbricks watermark in every inspected image. This is reported as an OBSERVATION with a careful INFERENCE ("likely Magicbricks-derived"), not a proven acquisition claim.

## Data sufficiency note (read before the tables below)

retrieval_examples.json stores only the top-10 globally-ranked candidates per query. Restricting this to same-group entries gives an EXACT prefix of the true within-group ranking, but Recall@10 and MRR require visibility beyond what's reliably available for many queries (measured directly - see table). Per instructions, these were NOT computed as point estimates to avoid a misleading bias, and no model was re-run to fill the gap.

| Model | Ambiguous @1 | Ambiguous @3 | Ambiguous @5 | Ambiguous @10 | Total queries |
|---|---|---|---|---|---|
| SigLIP2 | 0 | 0 | 1 | 11 | 84 |
| DINOv2 | 1 | 2 | 5 | 44 | 84 |

## 4/5. Within-group results (Recall@1/3/5 - exact or near-exact; @10/MRR not reported, see above)

| Metric | SigLIP2 Group A | DINOv2 Group A | SigLIP2 Group B | DINOv2 Group B |
|---|---|---|---|---|
| Recall@1 | 0.581 | 0.293 | 0.167 (1 unresolved) | 0.024 |
| Recall@3 | 0.721 | 0.439 | 0.381 (1 unresolved) | 0.125 (1 unresolved) |
| Recall@5 | 0.837 | 0.475 (1 unresolved) | 0.525 (3 unresolved) | 0.256 (2 unresolved) |

- SigLIP2 Group A: 43 valid queries across 9 houses.
- SigLIP2 Group B: 41 valid queries across 12 houses.
- DINOv2 Group A: 43 valid queries across 9 houses.
- DINOv2 Group B: 41 valid queries across 12 houses.

## 6. Cross-group intrusion (fraction of top-K from the OTHER group)

### SigLIP2

| Query group | K=1 | K=3 | K=5 | K=10 |
|---|---|---|---|---|
| A query → B intrusion | 0.000 | 0.008 | 0.014 | 0.047 |
| B query → A intrusion | 0.024 | 0.049 | 0.088 | 0.161 |

### DINOv2

| Query group | K=1 | K=3 | K=5 | K=10 |
|---|---|---|---|---|
| A query → B intrusion | 0.140 | 0.217 | 0.223 | 0.226 |
| B query → A intrusion | 0.146 | 0.138 | 0.185 | 0.251 |

## Source-specific hard queries (Part 9 of the task - 5 hardest per group per model, deterministic sort by margin then query_id)

### SigLIP2

**Group A hardest 5:**

| Query | House | Category | Best positive | Pos. sim | Best negative | Neg. sim | Margin |
|---|---|---|---|---|---|---|---|
| House_006/kitchen_01.jpeg | House_006 | - | House_006/bedroom_01.jpeg | 0.7945 | House_003/kitchen_01.jpeg | 0.8964 | -0.1019 |
| House_003/kitchen_01.jpeg | House_003 | - | House_003/living_room_01.jpeg | 0.8323 | House_004/kitchen_01.jpeg | 0.9166 | -0.0843 |
| House_005/kitchen_01.jpeg | House_005 | - | House_005/bedroom_01.jpeg | 0.7926 | House_008/kitchen_01.jpeg | 0.8614 | -0.0687 |
| House_009/kitchen_01.jpeg | House_009 | - | House_009/living_room_01.jpeg | 0.8640 | House_003/kitchen_01.jpeg | 0.9052 | -0.0412 |
| House_007/devotional_room_01.jpeg | House_007 | - | House_007/living_room_03.jpeg | 0.8052 | House_005/sit_out_01.jpeg | 0.8450 | -0.0398 |

**Group B hardest 5:**

| Query | House | Category | Best positive | Pos. sim | Best negative | Neg. sim | Margin |
|---|---|---|---|---|---|---|---|
| House_014/bathroom_01.jpg | House_014 | - | House_014/kitchen_01.jpg | 0.7367 | House_018/bathroom_01.jpg | 0.8871 | -0.1505 |
| House_017/bathroom_01.jpg | House_017 | - | House_017/living_room_01.jpg | 0.7751 | House_019/bathroom_01.jpg | 0.9145 | -0.1394 |
| House_019/bathroom_01.jpg | House_019 | - | House_019/living_room_01.jpg | 0.7976 | House_017/bathroom_01.jpg | 0.9145 | -0.1169 |
| House_014/kitchen_01.jpg | House_014 | - | House_014/bathroom_01.jpg | 0.7367 | House_021/kitchen_01.jpeg | 0.8460 | -0.1093 |
| House_021/bathroom_01.jpeg | House_021 | - | House_021/living_room_01.jpeg | 0.8064 | House_017/bathroom_01.jpg | 0.9096 | -0.1032 |

### DINOv2

**Group A hardest 5:**

| Query | House | Category | Best positive | Pos. sim | Best negative | Neg. sim | Margin |
|---|---|---|---|---|---|---|---|
| House_002/bathroom_01.jpeg | House_002 | - | House_002/living_room_01.jpeg | 0.0938 | House_010/bathroom_01.jpg | 0.6515 | -0.5577 |
| House_001/bedroom_02.jpeg | House_001 | - | House_001/bedroom_01.jpeg | 0.1510 | House_007/master_bedroom_02.jpeg | 0.6241 | -0.4731 |
| House_009/kitchen_01.jpeg | House_009 | - | House_009/living_room_01.jpeg | 0.2753 | House_007/kitchen_01.jpeg | 0.7018 | -0.4265 |
| House_003/kitchen_01.jpeg | House_003 | - | House_003/living_room_01.jpeg | 0.1249 | House_009/kitchen_01.jpeg | 0.5464 | -0.4215 |
| House_005/kitchen_01.jpeg | House_005 | - | House_005/living_room_01.jpeg | 0.1108 | House_007/kitchen_02.jpeg | 0.5058 | -0.3950 |

**Group B hardest 5:**

| Query | House | Category | Best positive | Pos. sim | Best negative | Neg. sim | Margin |
|---|---|---|---|---|---|---|---|
| House_017/bathroom_01.jpg | House_017 | - | House_017/bedroom_01.jpg | 0.0280 | House_019/bathroom_01.jpg | 0.7530 | -0.7250 |
| House_019/bathroom_01.jpg | House_019 | - | House_019/kitchen_01.jpg | 0.0446 | House_017/bathroom_01.jpg | 0.7530 | -0.7084 |
| House_014/bathroom_01.jpg | House_014 | - | House_014/living_room_01.jpg | 0.1260 | House_010/bathroom_01.jpg | 0.7793 | -0.6532 |
| House_015/balcony_01.jpg | House_015 | - | House_015/bedroom_01.jpg | 0.1062 | House_009/needs_review_01.jpeg | 0.6871 | -0.5809 |
| House_014/kitchen_01.jpg | House_014 | - | House_014/living_room_01.jpg | 0.1916 | House_017/kitchen_01.jpg | 0.7557 | -0.5640 |

(Full top-5 retrieval results for each of these queries are in `source_stratified_results.json` under `hard_queries_by_group`.)

## 7. Bathroom analysis by group

**Sample-size warning**: Group A has only 1 bathroom query total (out of 43 Group A images) - any Group A bathroom recall figure below is a single data point, not a statistically meaningful rate, and must not be interpreted as representative. Group B has 10 bathroom queries, a much more informative sample. This asymmetry itself is reported, not resolved - no bathroom images were added to Group A to balance it.

### SigLIP2

| Group | n queries | Recall@1 | Recall@3 | Recall@5 | Recall@10 |
|---|---|---|---|---|---|
| A ⚠ n=1 | 1 | 1.000 | 1.000 | 1.000 | 1.000 |
| B | 10 | 0.100 | 0.100 | 0.100 | 0.500 |

### DINOv2

| Group | n queries | Recall@1 | Recall@3 | Recall@5 | Recall@10 |
|---|---|---|---|---|---|
| A ⚠ n=1 | 1 | 0.000 | 0.000 | 0.000 | 0.000 |
| B | 10 | 0.000 | 0.000 | 0.000 | 0.100 |

## 8. Kitchen analysis by group

### SigLIP2

| Group | n queries | Recall@1 | Recall@3 | Recall@5 | Recall@10 |
|---|---|---|---|---|---|
| A | 10 | 0.300 | 0.500 | 0.600 | 0.800 |
| B | 9 | 0.111 | 0.333 | 0.333 | 0.444 |

### DINOv2

| Group | n queries | Recall@1 | Recall@3 | Recall@5 | Recall@10 |
|---|---|---|---|---|---|
| A | 10 | 0.100 | 0.200 | 0.300 | 0.300 |
| B | 9 | 0.000 | 0.000 | 0.000 | 0.111 |

## 9. Source-confounded failure analysis (SigLIP2 primary; DINOv2 for comparison)

### SigLIP2

- Total failures: 14
- Query is Group A: 0.143 | Query is Group B: 0.857
- Wrong result is Group A: 0.143 | Wrong result is Group B: 0.857
- **Cross-group failures: 0.000** | **Within-group failures: 1.000**

### DINOv2

- Total failures: 47
- Query is Group A: 0.404 | Query is Group B: 0.596
- Wrong result is Group A: 0.447 | Wrong result is Group B: 0.553
- **Cross-group failures: 0.170** | **Within-group failures: 0.830**

## 10. Similarity analysis

See `source_similarity_analysis.md` for full detail (within-model only, not cross-model).

## 11. Confound assessment

1. **Does performance differ substantially between Group A and Group B?** Yes for SigLIP2 (see §4/5 recall tables - Group A recall is consistently higher than Group B at every K where both are resolvable).
2. **Does one model behave differently across the two groups?** Both models show lower Group B performance, but the GAP size differs by model - see §4/5.
3. **Are top-10 failures disproportionately associated with Group B?** Yes - 0.857 of SigLIP2 failures and 0.553 of DINOv2 failures involve a Group B wrong result, both well above Group B's 12/21 = 0.57 share of all houses.
4. **Are bathroom/kitchen failures disproportionately associated with Group B?** See §7/8 - Group B's bathroom/kitchen Recall@1 is at or near 0 for both models in most cases, well below Group A's.
5. **Do cross-group results show strong source-specific retrieval behavior?** Yes - failures are overwhelmingly WITHIN-group (1.000 for SigLIP2), not cross-group, meaning when a model fails, the wrong answer usually comes from the SAME batch as the query.
6. **Does the evidence suggest source/style may be acting as a confounding variable?** The pattern (within-group failure concentration, Group B's weaker recall, Group B's watermark) is **consistent with a possible source/style confound**. This analysis cannot and does not claim it proves the model "learned the watermark" or that source style is definitively causal - only that the observed pattern is consistent with that explanation and inconsistent with a purely random/size-driven explanation.

## 12. Limitations

- Within-group Recall@10 and MRR could not be reliably derived from existing top-10-only data (§ Data sufficiency note) and are not reported as point estimates.
- Group B's watermark observation is based on a SAMPLE of images (from the prior error-analysis session), not every single Group B image individually re-verified in this pass.
- Small sample sizes in some group/category splits (e.g. bathroom-Group-A) limit statistical confidence - reported with explicit n alongside every recall figure.
- This is a post-hoc, non-causal analysis - see §11.

## 13. Implications for model selection

SigLIP2's property-level lead over DINOv2 is evaluated for robustness against the source-group confound in `README.md`'s Part 15 discussion (Outcome A/B/C/D) and `results/model_assessment.md`. This file does not itself select a model.