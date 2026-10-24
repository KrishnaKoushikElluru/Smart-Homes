# Phase 6 Pilot — Image Similarity Benchmark Summary

**Pilot dataset: 21 houses, 84 images.** This is a development/pilot benchmark, not the final SmartHomes image-similarity evaluation — see `docs/PHASE_6_IMAGE_SIMILARITY_BENCHMARK.md` and this folder's `README.md` for the full writeup.

## Dataset

- Houses with images: 21
- Total images: 84
- Empty/placeholder house directories: 0
- Unreadable files excluded: 0

| House | Images |
|---|---|
| House_001 | 4 |
| House_002 | 4 |
| House_003 | 3 |
| House_004 | 5 |
| House_005 | 4 |
| House_006 | 4 |
| House_007 | 11 |
| House_008 | 4 |
| House_009 | 4 |
| House_010 | 3 |
| House_011 | 1 |
| House_012 | 4 |
| House_013 | 4 |
| House_014 | 4 |
| House_015 | 3 |
| House_016 | 2 |
| House_017 | 4 |
| House_018 | 4 |
| House_019 | 4 |
| House_020 | 4 |
| House_021 | 4 |

| Category | Images |
|---|---|
| balcony | 2 |
| bathroom | 11 |
| bedroom | 21 |
| common_bedroom | 2 |
| devotional_room | 1 |
| kitchen | 19 |
| living_room | 22 |
| master_bedroom | 2 |
| needs_review | 2 |
| sit_out | 2 |

### Dataset issues/observations

- **[warning]** byte-identical image content reused across filenames (same photo, different names): ['House_006/bedroom_01.jpeg', 'House_006/living_room_01.jpeg']

## Comparison (pilot observation — 8 houses / 39 images, not a production claim)

| Metric | SigLIP2 | DINOv2 |
|---|---|---|
| Images processed | 84 | 84 |
| Houses | 21 | 21 |
| Embedding dimension | 768 | 768 |
| Avg embedding latency/image (s) | 0.263 | 0.337 |
| Recall@1 (property) | 0.434 | 0.072 |
| Recall@3 (property) | 0.590 | 0.217 |
| Recall@5 (property) | 0.663 | 0.337 |
| Recall@10 (property) | 0.831 | 0.434 |
| MRR (property) | 0.550 | 0.204 |
| Mean positive similarity | 0.810 | 0.219 |
| Mean top-negative similarity | 0.868 | 0.591 |
| Device | cpu | cpu |
| Model load time (s) | 1.31 | 1.45 |

**Pilot observation only** — with 8 houses / 39 images, any difference above is not a statistically strong basis for a production model choice. See the full report for caveats.

## Representative qualitative examples

### SigLIP2

**Query:** `House_001/bedroom_02.jpeg` (house House_001, category bedroom)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_001/bedroom_01.jpeg | House_001 | bedroom | 0.8465 | YES |
| 2 | House_005/bedroom_01.jpeg | House_005 | bedroom | 0.8366 | no |
| 3 | House_004/bedroom_01.jpeg | House_004 | bedroom | 0.8275 | no |
| 4 | House_007/master_bedroom_02.jpeg | House_007 | master_bedroom | 0.8255 | no |
| 5 | House_007/common_bedroom_01.jpeg | House_007 | common_bedroom | 0.8243 | no |
| 6 | House_018/bedroom_01.jpg | House_018 | bedroom | 0.8178 | no |
| 7 | House_007/master_bedroom_01.jpeg | House_007 | master_bedroom | 0.8148 | no |
| 8 | House_005/living_room_01.jpeg | House_005 | living_room | 0.8129 | no |
| 9 | House_003/living_room_01.jpeg | House_003 | living_room | 0.8037 | no |
| 10 | House_005/sit_out_01.jpeg | House_005 | sit_out | 0.7976 | no |

**Query:** `House_002/bathroom_01.jpeg` (house House_002, category bathroom)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_002/kitchen_01.jpeg | House_002 | kitchen | 0.8240 | YES |
| 2 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.7911 | no |
| 3 | House_002/bedroom_01.jpeg | House_002 | bedroom | 0.7858 | YES |
| 4 | House_002/living_room_01.jpeg | House_002 | living_room | 0.7711 | YES |
| 5 | House_004/bedroom_02.jpeg | House_004 | bedroom | 0.7490 | no |
| 6 | House_009/kitchen_01.jpeg | House_009 | kitchen | 0.7412 | no |
| 7 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.7397 | no |
| 8 | House_004/bedroom_01.jpeg | House_004 | bedroom | 0.7370 | no |
| 9 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.7341 | no |
| 10 | House_003/bedroom_01.jpeg | House_003 | bedroom | 0.7330 | no |

**Query:** `House_001/bedroom_01.jpeg` (house House_001, category bedroom)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_004/bedroom_01.jpeg | House_004 | bedroom | 0.8884 | no |
| 2 | House_007/master_bedroom_01.jpeg | House_007 | master_bedroom | 0.8854 | no |
| 3 | House_007/master_bedroom_02.jpeg | House_007 | master_bedroom | 0.8743 | no |
| 4 | House_005/bedroom_01.jpeg | House_005 | bedroom | 0.8738 | no |
| 5 | House_001/kitchen_01.jpeg | House_001 | kitchen | 0.8688 | YES |
| 6 | House_007/common_bedroom_01.jpeg | House_007 | common_bedroom | 0.8638 | no |
| 7 | House_003/kitchen_01.jpeg | House_003 | kitchen | 0.8632 | no |
| 8 | House_009/kitchen_01.jpeg | House_009 | kitchen | 0.8624 | no |
| 9 | House_007/kitchen_01.jpeg | House_007 | kitchen | 0.8610 | no |
| 10 | House_003/living_room_01.jpeg | House_003 | living_room | 0.8606 | no |

**Query:** `House_001/kitchen_01.jpeg` (house House_001, category kitchen)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_007/kitchen_01.jpeg | House_007 | kitchen | 0.8976 | no |
| 2 | House_003/kitchen_01.jpeg | House_003 | kitchen | 0.8886 | no |
| 3 | House_008/kitchen_01.jpeg | House_008 | kitchen | 0.8830 | no |
| 4 | House_004/kitchen_01.jpeg | House_004 | kitchen | 0.8730 | no |
| 5 | House_001/bedroom_01.jpeg | House_001 | bedroom | 0.8688 | YES |
| 6 | House_010/kitchen_01.jpeg | House_010 | kitchen | 0.8599 | no |
| 7 | House_019/kitchen_01.jpg | House_019 | kitchen | 0.8590 | no |
| 8 | House_007/kitchen_02.jpeg | House_007 | kitchen | 0.8569 | no |
| 9 | House_009/kitchen_01.jpeg | House_009 | kitchen | 0.8548 | no |
| 10 | House_006/kitchen_01.jpeg | House_006 | kitchen | 0.8439 | no |

**Query:** `House_003/kitchen_01.jpeg` (house House_003, category kitchen)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_004/kitchen_01.jpeg | House_004 | kitchen | 0.9166 | no |
| 2 | House_009/kitchen_01.jpeg | House_009 | kitchen | 0.9052 | no |
| 3 | House_006/kitchen_01.jpeg | House_006 | kitchen | 0.8964 | no |
| 4 | House_001/kitchen_01.jpeg | House_001 | kitchen | 0.8886 | no |
| 5 | House_008/kitchen_01.jpeg | House_008 | kitchen | 0.8831 | no |
| 6 | House_007/kitchen_01.jpeg | House_007 | kitchen | 0.8828 | no |
| 7 | House_001/bedroom_01.jpeg | House_001 | bedroom | 0.8632 | no |
| 8 | House_005/kitchen_01.jpeg | House_005 | kitchen | 0.8445 | no |
| 9 | House_006/bedroom_01.jpeg | House_006 | bedroom | 0.8441 | no |
| 10 | House_006/living_room_01.jpeg | House_006 | living_room | 0.8441 | no |

**Query:** `House_005/kitchen_01.jpeg` (house House_005, category kitchen)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_008/kitchen_01.jpeg | House_008 | kitchen | 0.8614 | no |
| 2 | House_001/bedroom_01.jpeg | House_001 | bedroom | 0.8486 | no |
| 3 | House_007/kitchen_02.jpeg | House_007 | kitchen | 0.8479 | no |
| 4 | House_009/kitchen_01.jpeg | House_009 | kitchen | 0.8474 | no |
| 5 | House_007/kitchen_01.jpeg | House_007 | kitchen | 0.8471 | no |
| 6 | House_003/kitchen_01.jpeg | House_003 | kitchen | 0.8445 | no |
| 7 | House_021/kitchen_01.jpeg | House_021 | kitchen | 0.8257 | no |
| 8 | House_001/kitchen_01.jpeg | House_001 | kitchen | 0.8206 | no |
| 9 | House_010/kitchen_01.jpeg | House_010 | kitchen | 0.8186 | no |
| 10 | House_019/kitchen_01.jpg | House_019 | kitchen | 0.8115 | no |

**Query:** `House_001/living_room_01.jpeg` (house House_001, category living_room)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_005/living_room_01.jpeg | House_005 | living_room | 0.8373 | no |
| 2 | House_007/living_room_01.jpeg | House_007 | living_room | 0.8345 | no |
| 3 | House_005/sit_out_01.jpeg | House_005 | sit_out | 0.8299 | no |
| 4 | House_004/living_room_02.jpeg | House_004 | living_room | 0.8236 | no |
| 5 | House_009/kitchen_01.jpeg | House_009 | kitchen | 0.8230 | no |
| 6 | House_001/bedroom_01.jpeg | House_001 | bedroom | 0.8199 | YES |
| 7 | House_003/kitchen_01.jpeg | House_003 | kitchen | 0.8185 | no |
| 8 | House_003/living_room_01.jpeg | House_003 | living_room | 0.8171 | no |
| 9 | House_007/living_room_03.jpeg | House_007 | living_room | 0.8131 | no |
| 10 | House_008/living_room_01.jpeg | House_008 | living_room | 0.8125 | no |

**Query:** `House_002/bedroom_01.jpeg` (house House_002, category bedroom)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_002/living_room_01.jpeg | House_002 | living_room | 0.8927 | YES |
| 2 | House_002/kitchen_01.jpeg | House_002 | kitchen | 0.8516 | YES |
| 3 | House_009/living_room_01.jpeg | House_009 | living_room | 0.8422 | no |
| 4 | House_003/bedroom_01.jpeg | House_003 | bedroom | 0.8399 | no |
| 5 | House_004/bedroom_02.jpeg | House_004 | bedroom | 0.8303 | no |
| 6 | House_004/bedroom_01.jpeg | House_004 | bedroom | 0.8056 | no |
| 7 | House_008/bedroom_01.jpeg | House_008 | bedroom | 0.7972 | no |
| 8 | House_004/living_room_02.jpeg | House_004 | living_room | 0.7949 | no |
| 9 | House_002/bathroom_01.jpeg | House_002 | bathroom | 0.7858 | YES |
| 10 | House_009/kitchen_01.jpeg | House_009 | kitchen | 0.7815 | no |

### DINOv2

**Query:** `House_006/bedroom_01.jpeg` (house House_006, category bedroom)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_006/living_room_01.jpeg | House_006 | living_room | 1.0000 | YES |
| 2 | House_002/bedroom_01.jpeg | House_002 | bedroom | 0.4891 | no |
| 3 | House_004/living_room_02.jpeg | House_004 | living_room | 0.4752 | no |
| 4 | House_003/bedroom_01.jpeg | House_003 | bedroom | 0.4669 | no |
| 5 | House_009/living_room_01.jpeg | House_009 | living_room | 0.4661 | no |
| 6 | House_001/living_room_01.jpeg | House_001 | living_room | 0.4347 | no |
| 7 | House_007/common_bedroom_01.jpeg | House_007 | common_bedroom | 0.4042 | no |
| 8 | House_004/bedroom_01.jpeg | House_004 | bedroom | 0.3938 | no |
| 9 | House_005/living_room_01.jpeg | House_005 | living_room | 0.3870 | no |
| 10 | House_007/sit_out_01.jpeg | House_007 | sit_out | 0.3829 | no |

**Query:** `House_006/living_room_01.jpeg` (house House_006, category living_room)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_006/bedroom_01.jpeg | House_006 | bedroom | 1.0000 | YES |
| 2 | House_002/bedroom_01.jpeg | House_002 | bedroom | 0.4891 | no |
| 3 | House_004/living_room_02.jpeg | House_004 | living_room | 0.4752 | no |
| 4 | House_003/bedroom_01.jpeg | House_003 | bedroom | 0.4669 | no |
| 5 | House_009/living_room_01.jpeg | House_009 | living_room | 0.4661 | no |
| 6 | House_001/living_room_01.jpeg | House_001 | living_room | 0.4347 | no |
| 7 | House_007/common_bedroom_01.jpeg | House_007 | common_bedroom | 0.4042 | no |
| 8 | House_004/bedroom_01.jpeg | House_004 | bedroom | 0.3938 | no |
| 9 | House_005/living_room_01.jpeg | House_005 | living_room | 0.3870 | no |
| 10 | House_007/sit_out_01.jpeg | House_007 | sit_out | 0.3829 | no |

**Query:** `House_002/bedroom_01.jpeg` (house House_002, category bedroom)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_006/bedroom_01.jpeg | House_006 | bedroom | 0.4891 | no |
| 2 | House_006/living_room_01.jpeg | House_006 | living_room | 0.4891 | no |
| 3 | House_009/living_room_01.jpeg | House_009 | living_room | 0.4758 | no |
| 4 | House_004/living_room_02.jpeg | House_004 | living_room | 0.3851 | no |
| 5 | House_002/living_room_01.jpeg | House_002 | living_room | 0.3824 | YES |
| 6 | House_003/bedroom_01.jpeg | House_003 | bedroom | 0.3670 | no |
| 7 | House_007/living_room_02.jpeg | House_007 | living_room | 0.3596 | no |
| 8 | House_004/bedroom_01.jpeg | House_004 | bedroom | 0.3567 | no |
| 9 | House_009/bedroom_01.jpeg | House_009 | bedroom | 0.3278 | no |
| 10 | House_007/sit_out_01.jpeg | House_007 | sit_out | 0.3276 | no |

**Query:** `House_002/living_room_01.jpeg` (house House_002, category living_room)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_009/bedroom_01.jpeg | House_009 | bedroom | 0.5204 | no |
| 2 | House_021/living_room_01.jpeg | House_021 | living_room | 0.4150 | no |
| 3 | House_005/sit_out_01.jpeg | House_005 | sit_out | 0.4045 | no |
| 4 | House_002/bedroom_01.jpeg | House_002 | bedroom | 0.3824 | YES |
| 5 | House_003/bedroom_01.jpeg | House_003 | bedroom | 0.3788 | no |
| 6 | House_016/bedroom_01.jpeg | House_016 | bedroom | 0.3743 | no |
| 7 | House_007/living_room_02.jpeg | House_007 | living_room | 0.3557 | no |
| 8 | House_019/bedroom_01.jpg | House_019 | bedroom | 0.3493 | no |
| 9 | House_007/sit_out_01.jpeg | House_007 | sit_out | 0.3459 | no |
| 10 | House_021/bedroom_01.jpeg | House_021 | bedroom | 0.3439 | no |

**Query:** `House_001/bedroom_01.jpeg` (house House_001, category bedroom)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_020/living_room_01.jpeg | House_020 | living_room | 0.5214 | no |
| 2 | House_021/kitchen_01.jpeg | House_021 | kitchen | 0.4775 | no |
| 3 | House_007/kitchen_02.jpeg | House_007 | kitchen | 0.4429 | no |
| 4 | House_010/kitchen_01.jpeg | House_010 | kitchen | 0.4407 | no |
| 5 | House_018/kitchen_01.jpg | House_018 | kitchen | 0.4395 | no |
| 6 | House_007/kitchen_01.jpeg | House_007 | kitchen | 0.4262 | no |
| 7 | House_020/kitchen_01.jpeg | House_020 | kitchen | 0.4148 | no |
| 8 | House_012/kitchen_01.jpg | House_012 | kitchen | 0.4052 | no |
| 9 | House_009/kitchen_01.jpeg | House_009 | kitchen | 0.3620 | no |
| 10 | House_008/living_room_01.jpeg | House_008 | living_room | 0.3559 | no |

**Query:** `House_001/bedroom_02.jpeg` (house House_001, category bedroom)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_007/master_bedroom_02.jpeg | House_007 | master_bedroom | 0.6241 | no |
| 2 | House_013/bedroom_01.jpg | House_013 | bedroom | 0.4921 | no |
| 3 | House_004/bedroom_02.jpeg | House_004 | bedroom | 0.4414 | no |
| 4 | House_003/bedroom_01.jpeg | House_003 | bedroom | 0.4017 | no |
| 5 | House_007/common_bedroom_01.jpeg | House_007 | common_bedroom | 0.3391 | no |
| 6 | House_012/bedroom_01.jpg | House_012 | bedroom | 0.3193 | no |
| 7 | House_004/bedroom_01.jpeg | House_004 | bedroom | 0.3074 | no |
| 8 | House_008/bedroom_01.jpeg | House_008 | bedroom | 0.3034 | no |
| 9 | House_015/bedroom_01.jpg | House_015 | bedroom | 0.3002 | no |
| 10 | House_005/bedroom_01.jpeg | House_005 | bedroom | 0.2805 | no |

**Query:** `House_001/kitchen_01.jpeg` (house House_001, category kitchen)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_008/kitchen_01.jpeg | House_008 | kitchen | 0.6119 | no |
| 2 | House_007/kitchen_01.jpeg | House_007 | kitchen | 0.5781 | no |
| 3 | House_012/kitchen_01.jpg | House_012 | kitchen | 0.5289 | no |
| 4 | House_009/kitchen_01.jpeg | House_009 | kitchen | 0.5010 | no |
| 5 | House_007/kitchen_02.jpeg | House_007 | kitchen | 0.4673 | no |
| 6 | House_003/kitchen_01.jpeg | House_003 | kitchen | 0.4420 | no |
| 7 | House_021/kitchen_01.jpeg | House_021 | kitchen | 0.4207 | no |
| 8 | House_019/kitchen_01.jpg | House_019 | kitchen | 0.4186 | no |
| 9 | House_020/kitchen_01.jpeg | House_020 | kitchen | 0.4176 | no |
| 10 | House_005/kitchen_01.jpeg | House_005 | kitchen | 0.4053 | no |

**Query:** `House_001/living_room_01.jpeg` (house House_001, category living_room)

| Rank | Image | House | Category | Similarity | Correct Property? |
|---|---|---|---|---|---|
| 1 | House_004/living_room_02.jpeg | House_004 | living_room | 0.4718 | no |
| 2 | House_006/bedroom_01.jpeg | House_006 | bedroom | 0.4347 | no |
| 3 | House_006/living_room_01.jpeg | House_006 | living_room | 0.4347 | no |
| 4 | House_008/living_room_01.jpeg | House_008 | living_room | 0.4231 | no |
| 5 | House_003/living_room_01.jpeg | House_003 | living_room | 0.3993 | no |
| 6 | House_003/bedroom_01.jpeg | House_003 | bedroom | 0.3920 | no |
| 7 | House_007/living_room_01.jpeg | House_007 | living_room | 0.3888 | no |
| 8 | House_004/living_room_01.jpeg | House_004 | living_room | 0.3841 | no |
| 9 | House_005/living_room_01.jpeg | House_005 | living_room | 0.3801 | no |
| 10 | House_007/living_room_02.jpeg | House_007 | living_room | 0.3800 | no |
