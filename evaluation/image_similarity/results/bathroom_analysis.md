# Bathroom Retrieval Analysis

## Why bathrooms are hard (Goal 4 - empirical, evidence-based)

Direct visual inspection of `House_014/bathroom_01.jpg`, `House_017/bathroom_01.jpg`,
`House_018/bathroom_01.jpg`, `House_019/bathroom_01.jpg`, `House_010/bathroom_01.jpg`,
and `House_002/bathroom_01.jpeg` (original batch, for contrast).

**OBSERVED**:
- All five `House_01x`-`House_02x` bathroom photos share a near-identical camera
  framing convention: shot from the doorway looking straight in, wall-mounted toilet
  roughly centered, wall-hung shower fixture visible, neutral-to-warm large-format
  wall tiles floor-to-near-ceiling, bright even lighting, no clutter/personal items
  visible.
- All five carry a visible "magicbricks" watermark (see `failure_taxonomy.md`'s
  manual-inspection section).
- By contrast, `House_002/bathroom_01.jpeg` (original batch) is a narrow, cluttered,
  clearly lived-in space - dark wood-look flooring, a patterned shower curtain,
  visible personal items (toilet brush, toiletries, laundry basket) - and carries no
  watermark.

**INTERPRETATION**: The `House_01x`-`House_02x` bathroom photos are visually
homogeneous with each other in a way the original batch's bathroom photo is not -
consistent with real-estate LISTING photography (staged/empty rooms, consistent
professional framing and lighting) rather than personal photography (lived-in,
individually distinct clutter/decor). This plausibly explains why an embedding
model finds these bathrooms more interchangeable with each other than with their
own house's other rooms: the STYLE similarity may be at least as strong a signal in
the image as the specific property's own visual identity. This is an observation
about the dataset's photographic source, not a claim about either model's
understanding of "bathroom" as a concept.

## SigLIP2

- Bathroom queries: 11
- Valid bathroom queries: 11
- Excluded (zero-positive/singleton house): 0
- Correct property found somewhere in top-10: 6
- Top-1 is another house's bathroom (outranks own house entirely at rank 1): 9

| Recall@1 | Recall@3 | Recall@5 | Recall@10 |
|---|---|---|---|
| 0.182 | 0.182 | 0.182 | 0.545 |

### Per-query top-10

**Query:** `House_002/bathroom_01.jpeg` (house House_002) - first correct-property rank: 1

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_002/kitchen_01.jpeg | House_002 | kitchen | 0.8240 | YES | NO |
| 2 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.7911 | NO | YES |
| 3 | House_002/bedroom_01.jpeg | House_002 | bedroom | 0.7858 | YES | NO |
| 4 | House_002/living_room_01.jpeg | House_002 | living_room | 0.7711 | YES | NO |
| 5 | House_004/bedroom_02.jpeg | House_004 | bedroom | 0.7490 | NO | NO |
| 6 | House_009/kitchen_01.jpeg | House_009 | kitchen | 0.7412 | NO | NO |
| 7 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.7397 | NO | YES |
| 8 | House_004/bedroom_01.jpeg | House_004 | bedroom | 0.7370 | NO | NO |
| 9 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.7341 | NO | YES |
| 10 | House_003/bedroom_01.jpeg | House_003 | bedroom | 0.7330 | NO | NO |

**Query:** `House_010/bathroom_01.jpg` (house House_010) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.8513 | NO | YES |
| 2 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.8472 | NO | YES |
| 3 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.8362 | NO | YES |
| 4 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.8197 | NO | YES |
| 5 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.8181 | NO | YES |
| 6 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.8153 | NO | YES |
| 7 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.8010 | NO | YES |
| 8 | House_002/bathroom_01.jpeg | House_002 | bathroom | 0.7911 | NO | YES |
| 9 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.7865 | NO | YES |
| 10 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.7740 | NO | YES |

**Query:** `House_012/bathroom_01.jpg` (house House_012) - first correct-property rank: 10

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.8808 | NO | YES |
| 2 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.8632 | NO | YES |
| 3 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.8494 | NO | YES |
| 4 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.8472 | NO | YES |
| 5 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.8282 | NO | YES |
| 6 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.8245 | NO | YES |
| 7 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.8226 | NO | YES |
| 8 | House_001/kitchen_01.jpeg | House_001 | kitchen | 0.7979 | NO | NO |
| 9 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.7973 | NO | YES |
| 10 | House_012/living_room_01.jpg | House_012 | living_room | 0.7859 | YES | NO |

**Query:** `House_013/bathroom_01.jpg` (house House_013) - first correct-property rank: 8

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.8523 | NO | YES |
| 2 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.8334 | NO | YES |
| 3 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.8181 | NO | YES |
| 4 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.8020 | NO | YES |
| 5 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.8000 | NO | YES |
| 6 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.7947 | NO | YES |
| 7 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.7911 | NO | YES |
| 8 | House_013/bedroom_01.jpg | House_013 | bedroom | 0.7894 | YES | NO |
| 9 | House_013/kitchen_01.jpg | House_013 | kitchen | 0.7800 | YES | NO |
| 10 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.7761 | NO | YES |

**Query:** `House_014/bathroom_01.jpg` (house House_014) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.8871 | NO | YES |
| 2 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.8699 | NO | YES |
| 3 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.8624 | NO | YES |
| 4 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.8592 | NO | YES |
| 5 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.8513 | NO | YES |
| 6 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.8381 | NO | YES |
| 7 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.8334 | NO | YES |
| 8 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.8283 | NO | YES |
| 9 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.8282 | NO | YES |
| 10 | House_021/kitchen_01.jpeg | House_021 | kitchen | 0.7793 | NO | NO |

**Query:** `House_015/bathroom_01.jpg` (house House_015) - first correct-property rank: 8

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.8494 | NO | YES |
| 2 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.8443 | NO | YES |
| 3 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.8381 | NO | YES |
| 4 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.8362 | NO | YES |
| 5 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.8200 | NO | YES |
| 6 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.8153 | NO | YES |
| 7 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.8002 | NO | YES |
| 8 | House_015/bedroom_01.jpg | House_015 | bedroom | 0.7954 | YES | NO |
| 9 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.7932 | NO | YES |
| 10 | House_012/living_room_01.jpg | House_012 | living_room | 0.7783 | NO | NO |

**Query:** `House_017/bathroom_01.jpg` (house House_017) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.9145 | NO | YES |
| 2 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.9096 | NO | YES |
| 3 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.8685 | NO | YES |
| 4 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.8640 | NO | YES |
| 5 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.8632 | NO | YES |
| 6 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.8624 | NO | YES |
| 7 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.8200 | NO | YES |
| 8 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.8010 | NO | YES |
| 9 | House_021/living_room_01.jpeg | House_021 | living_room | 0.7914 | NO | NO |
| 10 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.7911 | NO | YES |

**Query:** `House_018/bathroom_01.jpg` (house House_018) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.8871 | NO | YES |
| 2 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.8850 | NO | YES |
| 3 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.8685 | NO | YES |
| 4 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.8422 | NO | YES |
| 5 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.8362 | NO | YES |
| 6 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.8279 | NO | YES |
| 7 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.8245 | NO | YES |
| 8 | House_021/kitchen_01.jpeg | House_021 | kitchen | 0.8167 | NO | NO |
| 9 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.7947 | NO | YES |
| 10 | House_007/master_bedroom_01.jpeg | House_007 | master_bedroom | 0.7873 | NO | NO |

**Query:** `House_019/bathroom_01.jpg` (house House_019) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.9145 | NO | YES |
| 2 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.8850 | NO | YES |
| 3 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.8808 | NO | YES |
| 4 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.8699 | NO | YES |
| 5 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.8674 | NO | YES |
| 6 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.8655 | NO | YES |
| 7 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.8443 | NO | YES |
| 8 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.8197 | NO | YES |
| 9 | House_021/living_room_01.jpeg | House_021 | living_room | 0.8146 | NO | NO |
| 10 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.8020 | NO | YES |

**Query:** `House_020/bathroom_01.jpeg` (house House_020) - first correct-property rank: 1

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_020/kitchen_01.jpeg | House_020 | kitchen | 0.8666 | YES | NO |
| 2 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.8655 | NO | YES |
| 3 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.8640 | NO | YES |
| 4 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.8580 | NO | YES |
| 5 | House_020/living_room_01.jpeg | House_020 | living_room | 0.8552 | YES | NO |
| 6 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.8422 | NO | YES |
| 7 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.8283 | NO | YES |
| 8 | House_010/kitchen_01.jpeg | House_010 | kitchen | 0.8157 | NO | NO |
| 9 | House_021/living_room_01.jpeg | House_021 | living_room | 0.8130 | NO | NO |
| 10 | House_020/bedroom_01.jpeg | House_020 | bedroom | 0.8095 | YES | NO |

**Query:** `House_021/bathroom_01.jpeg` (house House_021) - first correct-property rank: 9

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.9096 | NO | YES |
| 2 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.8674 | NO | YES |
| 3 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.8592 | NO | YES |
| 4 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.8580 | NO | YES |
| 5 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.8523 | NO | YES |
| 6 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.8362 | NO | YES |
| 7 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.8279 | NO | YES |
| 8 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.8226 | NO | YES |
| 9 | House_021/living_room_01.jpeg | House_021 | living_room | 0.8064 | YES | NO |
| 10 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.7932 | NO | YES |

## DINOv2

- Bathroom queries: 11
- Valid bathroom queries: 11
- Excluded (zero-positive/singleton house): 0
- Correct property found somewhere in top-10: 1
- Top-1 is another house's bathroom (outranks own house entirely at rank 1): 11

| Recall@1 | Recall@3 | Recall@5 | Recall@10 |
|---|---|---|---|
| 0.000 | 0.000 | 0.000 | 0.091 |

### Per-query top-10

**Query:** `House_002/bathroom_01.jpeg` (house House_002) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.6515 | NO | YES |
| 2 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.6244 | NO | YES |
| 3 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.6216 | NO | YES |
| 4 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.5915 | NO | YES |
| 5 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.5462 | NO | YES |
| 6 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.5448 | NO | YES |
| 7 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.5367 | NO | YES |
| 8 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.4545 | NO | YES |
| 9 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.4312 | NO | YES |
| 10 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.3941 | NO | YES |

**Query:** `House_010/bathroom_01.jpg` (house House_010) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.7793 | NO | YES |
| 2 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.7188 | NO | YES |
| 3 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.6805 | NO | YES |
| 4 | House_002/bathroom_01.jpeg | House_002 | bathroom | 0.6515 | NO | YES |
| 5 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.6467 | NO | YES |
| 6 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.6335 | NO | YES |
| 7 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.5143 | NO | YES |
| 8 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.4918 | NO | YES |
| 9 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.4892 | NO | YES |
| 10 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.4613 | NO | YES |

**Query:** `House_012/bathroom_01.jpg` (house House_012) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.6761 | NO | YES |
| 2 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.6154 | NO | YES |
| 3 | House_002/bathroom_01.jpeg | House_002 | bathroom | 0.5462 | NO | YES |
| 4 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.5143 | NO | YES |
| 5 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.5036 | NO | YES |
| 6 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.4863 | NO | YES |
| 7 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.4700 | NO | YES |
| 8 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.4142 | NO | YES |
| 9 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.3894 | NO | YES |
| 10 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.2780 | NO | YES |

**Query:** `House_013/bathroom_01.jpg` (house House_013) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.6711 | NO | YES |
| 2 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.6182 | NO | YES |
| 3 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.5266 | NO | YES |
| 4 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.4750 | NO | YES |
| 5 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.4613 | NO | YES |
| 6 | House_002/bathroom_01.jpeg | House_002 | bathroom | 0.4312 | NO | YES |
| 7 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.4265 | NO | YES |
| 8 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.4140 | NO | YES |
| 9 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.3966 | NO | YES |
| 10 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.3894 | NO | YES |

**Query:** `House_014/bathroom_01.jpg` (house House_014) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.7793 | NO | YES |
| 2 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.6041 | NO | YES |
| 3 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.5917 | NO | YES |
| 4 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.5813 | NO | YES |
| 5 | House_002/bathroom_01.jpeg | House_002 | bathroom | 0.5367 | NO | YES |
| 6 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.5313 | NO | YES |
| 7 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.4598 | NO | YES |
| 8 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.4298 | NO | YES |
| 9 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.4142 | NO | YES |
| 10 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.3966 | NO | YES |

**Query:** `House_015/bathroom_01.jpg` (house House_015) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.6880 | NO | YES |
| 2 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.6729 | NO | YES |
| 3 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.6673 | NO | YES |
| 4 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.6467 | NO | YES |
| 5 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.5673 | NO | YES |
| 6 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.5645 | NO | YES |
| 7 | House_002/bathroom_01.jpeg | House_002 | bathroom | 0.5448 | NO | YES |
| 8 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.5313 | NO | YES |
| 9 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.4700 | NO | YES |
| 10 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.4265 | NO | YES |

**Query:** `House_017/bathroom_01.jpg` (house House_017) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.7530 | NO | YES |
| 2 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.7188 | NO | YES |
| 3 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.6802 | NO | YES |
| 4 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.6761 | NO | YES |
| 5 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.6673 | NO | YES |
| 6 | House_002/bathroom_01.jpeg | House_002 | bathroom | 0.6216 | NO | YES |
| 7 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.5856 | NO | YES |
| 8 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.5813 | NO | YES |
| 9 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.4750 | NO | YES |
| 10 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.4428 | NO | YES |

**Query:** `House_018/bathroom_01.jpg` (house House_018) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.6711 | NO | YES |
| 2 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.6665 | NO | YES |
| 3 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.6308 | NO | YES |
| 4 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.5856 | NO | YES |
| 5 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.5673 | NO | YES |
| 6 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.5639 | NO | YES |
| 7 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.4892 | NO | YES |
| 8 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.4863 | NO | YES |
| 9 | House_002/bathroom_01.jpeg | House_002 | bathroom | 0.4545 | NO | YES |
| 10 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.4298 | NO | YES |

**Query:** `House_019/bathroom_01.jpg` (house House_019) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.7530 | NO | YES |
| 2 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.7298 | NO | YES |
| 3 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.6729 | NO | YES |
| 4 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.6665 | NO | YES |
| 5 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.6335 | NO | YES |
| 6 | House_002/bathroom_01.jpeg | House_002 | bathroom | 0.6244 | NO | YES |
| 7 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.6154 | NO | YES |
| 8 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.5917 | NO | YES |
| 9 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.5543 | NO | YES |
| 10 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.5266 | NO | YES |

**Query:** `House_020/bathroom_01.jpeg` (house House_020) - first correct-property rank: 9

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.6308 | NO | YES |
| 2 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.6182 | NO | YES |
| 3 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.5645 | NO | YES |
| 4 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.5543 | NO | YES |
| 5 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.4918 | NO | YES |
| 6 | House_021/bathroom_01.jpeg | House_021 | bathroom | 0.4836 | NO | YES |
| 7 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.4598 | NO | YES |
| 8 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.4428 | NO | YES |
| 9 | House_020/kitchen_01.jpeg | House_020 | kitchen | 0.4110 | YES | NO |
| 10 | House_002/bathroom_01.jpeg | House_002 | bathroom | 0.3941 | NO | YES |

**Query:** `House_021/bathroom_01.jpeg` (house House_021) - first correct-property rank: None

| Rank | Retrieved | House | Category | Similarity | Correct property? | Same category? |
|---|---|---|---|---|---|---|
| 1 | House_019/bathroom_01.jpg | House_019 | bathroom | 0.7298 | NO | YES |
| 2 | House_015/bathroom_01.jpg | House_015 | bathroom | 0.6880 | NO | YES |
| 3 | House_010/bathroom_01.jpg | House_010 | bathroom | 0.6805 | NO | YES |
| 4 | House_017/bathroom_01.jpg | House_017 | bathroom | 0.6802 | NO | YES |
| 5 | House_014/bathroom_01.jpg | House_014 | bathroom | 0.6041 | NO | YES |
| 6 | House_002/bathroom_01.jpeg | House_002 | bathroom | 0.5915 | NO | YES |
| 7 | House_018/bathroom_01.jpg | House_018 | bathroom | 0.5639 | NO | YES |
| 8 | House_012/bathroom_01.jpg | House_012 | bathroom | 0.5036 | NO | YES |
| 9 | House_020/bathroom_01.jpeg | House_020 | bathroom | 0.4836 | NO | YES |
| 10 | House_013/bathroom_01.jpg | House_013 | bathroom | 0.4140 | NO | YES |
