# Pilot Duplicate Sensitivity & Margin Analysis

## Part A — Duplicate verification

**1 byte-identical duplicate group(s) detected** (independently re-verified via SHA-256, not just trusting the dataset scan's stored hash).

- Group: `House_006/bedroom_01.jpeg`, `House_006/living_room_01.jpeg`
  - `House_006/bedroom_01.jpeg` — 139818 bytes — SHA-256 `0ca7881210665e452322001a15bcf02ebdd6aedf9a4525a82676e1ea0fd805b5`
  - `House_006/living_room_01.jpeg` — 139818 bytes — SHA-256 `0ca7881210665e452322001a15bcf02ebdd6aedf9a4525a82676e1ea0fd805b5`
  - **Identical (SHA-256 match): True**

## Part A — Duplicate sensitivity (Recall@K, MRR)

| metric | SigLIP2 All | SigLIP2 Excl. Duplicate | SigLIP2 Abs. Diff | DINOv2 All | DINOv2 Excl. Duplicate | DINOv2 Abs. Diff |
|---|---|---|---|---|---|---|
| Recall@1 | 0.4337 | 0.4198 | 0.0140 | 0.0723 | 0.0494 | 0.0229 |
| Recall@3 | 0.5904 | 0.5679 | 0.0225 | 0.2169 | 0.2099 | 0.0070 |
| Recall@5 | 0.6627 | 0.6420 | 0.0207 | 0.3373 | 0.3210 | 0.0164 |
| Recall@10 | 0.8313 | 0.8148 | 0.0165 | 0.4337 | 0.4074 | 0.0263 |
| MRR | 0.5500 | 0.5328 | 0.0172 | 0.2039 | 0.1860 | 0.0179 |

## Part B — Margin analysis

For every query: `best_positive_similarity` (closest same-house image), `best_negative_similarity` (closest different-house image), `margin = best_positive - best_negative`. Not comparable in absolute terms across models (different embedding-space calibration) — only within-model ranking/separation behavior is meaningful.

| Metric | SigLIP2 | DINOv2 |
|---|---|---|
| Number of queries | 84 | 84 |
| Valid queries (>=1 positive & >=1 negative) | 83 | 83 |
| Total positive candidates | 318 | 318 |
| Total negative candidates | 6571 | 6571 |
| Mean best-positive similarity | 0.8539 | 0.3390 |
| Mean best-negative similarity | 0.8685 | 0.5910 |
| Mean margin | -0.0146 | -0.2520 |
| Median margin | -0.0155 | -0.2275 |
| % margin > 0 | 0.4337 | 0.0723 |
| % margin >= 0.05 | 0.1325 | 0.0723 |
| % margin >= 0.10 | 0.0120 | 0.0482 |

## Part C — Hard / strong queries by margin

### SigLIP2

**5 strongest (highest margin):**

| Query | House | Best Positive | Pos. Sim | Best Negative | Neg. Sim | Margin | Duplicate-related? |
|---|---|---|---|---|---|---|---|
| House_002/living_room_01.jpeg | House_002 | House_002/bedroom_01.jpeg | 0.8927 | House_009/living_room_01.jpeg | 0.7788 | 0.1140 | no |
| House_006/living_room_01.jpeg | House_006 | House_006/bedroom_01.jpeg | 1.0000 | House_004/living_room_02.jpeg | 0.9050 | 0.0950 | YES |
| House_006/bedroom_01.jpeg | House_006 | House_006/living_room_01.jpeg | 1.0000 | House_004/living_room_02.jpeg | 0.9050 | 0.0950 | YES |
| House_007/common_bedroom_02.jpeg | House_007 | House_007/master_bedroom_01.jpeg | 0.9392 | House_001/bedroom_01.jpeg | 0.8515 | 0.0876 | no |
| House_007/common_bedroom_01.jpeg | House_007 | House_007/master_bedroom_02.jpeg | 0.9510 | House_008/living_room_01.jpeg | 0.8648 | 0.0863 | no |

**5 hardest (lowest margin):**

| Query | House | Best Positive | Pos. Sim | Best Negative | Neg. Sim | Margin | Duplicate-related? |
|---|---|---|---|---|---|---|---|
| House_014/bathroom_01.jpg | House_014 | House_014/kitchen_01.jpg | 0.7367 | House_018/bathroom_01.jpg | 0.8871 | -0.1505 | no |
| House_017/bathroom_01.jpg | House_017 | House_017/living_room_01.jpg | 0.7751 | House_019/bathroom_01.jpg | 0.9145 | -0.1394 | no |
| House_019/bathroom_01.jpg | House_019 | House_019/living_room_01.jpg | 0.7976 | House_017/bathroom_01.jpg | 0.9145 | -0.1169 | no |
| House_014/kitchen_01.jpg | House_014 | House_014/bathroom_01.jpg | 0.7367 | House_021/kitchen_01.jpeg | 0.8460 | -0.1093 | no |
| House_021/bathroom_01.jpeg | House_021 | House_021/living_room_01.jpeg | 0.8064 | House_017/bathroom_01.jpg | 0.9096 | -0.1032 | no |

### DINOv2

**5 strongest (highest margin):**

| Query | House | Best Positive | Pos. Sim | Best Negative | Neg. Sim | Margin | Duplicate-related? |
|---|---|---|---|---|---|---|---|
| House_006/living_room_01.jpeg | House_006 | House_006/bedroom_01.jpeg | 1.0000 | House_002/bedroom_01.jpeg | 0.4891 | 0.5109 | YES |
| House_006/bedroom_01.jpeg | House_006 | House_006/living_room_01.jpeg | 1.0000 | House_002/bedroom_01.jpeg | 0.4891 | 0.5109 | YES |
| House_007/master_bedroom_01.jpeg | House_007 | House_007/common_bedroom_02.jpeg | 0.6978 | House_016/living_room_01.jpeg | 0.5276 | 0.1702 | no |
| House_007/common_bedroom_02.jpeg | House_007 | House_007/master_bedroom_01.jpeg | 0.6978 | House_008/bedroom_01.jpeg | 0.5716 | 0.1262 | no |
| House_007/kitchen_02.jpeg | House_007 | House_007/kitchen_01.jpeg | 0.5718 | House_005/kitchen_01.jpeg | 0.5058 | 0.0659 | no |

**5 hardest (lowest margin):**

| Query | House | Best Positive | Pos. Sim | Best Negative | Neg. Sim | Margin | Duplicate-related? |
|---|---|---|---|---|---|---|---|
| House_017/bathroom_01.jpg | House_017 | House_017/bedroom_01.jpg | 0.0280 | House_019/bathroom_01.jpg | 0.7530 | -0.7250 | no |
| House_019/bathroom_01.jpg | House_019 | House_019/kitchen_01.jpg | 0.0446 | House_017/bathroom_01.jpg | 0.7530 | -0.7084 | no |
| House_014/bathroom_01.jpg | House_014 | House_014/living_room_01.jpg | 0.1260 | House_010/bathroom_01.jpg | 0.7793 | -0.6532 | no |
| House_015/balcony_01.jpg | House_015 | House_015/bedroom_01.jpg | 0.1062 | House_009/needs_review_01.jpeg | 0.6871 | -0.5809 | no |
| House_014/kitchen_01.jpg | House_014 | House_014/living_room_01.jpg | 0.1916 | House_017/kitchen_01.jpg | 0.7557 | -0.5640 | no |
