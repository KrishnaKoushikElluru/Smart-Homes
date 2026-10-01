# SigLIP2 Top-10 Failure Analysis

Total SigLIP2 top-10 failures (valid queries only): 14

## Failure rate by category (SigLIP2)

| Category | Valid queries | Top-10 failures | Failure rate |
|---|---|---|---|
| balcony | 2 | 0 | 0.000 |
| bathroom | 11 | 5 | 0.455 |
| bedroom | 20 | 2 | 0.100 |
| common_bedroom | 2 | 0 | 0.000 |
| devotional_room | 1 | 0 | 0.000 |
| kitchen | 19 | 7 | 0.368 |
| living_room | 22 | 0 | 0.000 |
| master_bedroom | 2 | 0 | 0.000 |
| needs_review | 2 | 0 | 0.000 |
| sit_out | 2 | 0 | 0.000 |

## Failure rate by category (DINOv2, for comparison)

| Category | Valid queries | Top-10 failures | Failure rate |
|---|---|---|---|
| balcony | 2 | 2 | 1.000 |
| bathroom | 11 | 10 | 0.909 |
| bedroom | 20 | 10 | 0.500 |
| common_bedroom | 2 | 0 | 0.000 |
| devotional_room | 1 | 1 | 1.000 |
| kitchen | 19 | 15 | 0.789 |
| living_room | 22 | 8 | 0.364 |
| master_bedroom | 2 | 0 | 0.000 |
| needs_review | 2 | 0 | 0.000 |
| sit_out | 2 | 1 | 0.500 |

## Every SigLIP2 failure, full top-10

**Query:** `House_003/kitchen_01.jpeg` (house House_003, category kitchen)

| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |
|---|---|---|---|---|---|
| 1 | House_004 | kitchen | 0.9166 | NO | YES |
| 2 | House_009 | kitchen | 0.9052 | NO | YES |
| 3 | House_006 | kitchen | 0.8964 | NO | YES |
| 4 | House_001 | kitchen | 0.8886 | NO | YES |
| 5 | House_008 | kitchen | 0.8831 | NO | YES |
| 6 | House_007 | kitchen | 0.8828 | NO | YES |
| 7 | House_001 | bedroom | 0.8632 | NO | NO |
| 8 | House_005 | kitchen | 0.8445 | NO | YES |
| 9 | House_006 | bedroom | 0.8441 | NO | NO |
| 10 | House_006 | living_room | 0.8441 | NO | NO |

**Query:** `House_005/kitchen_01.jpeg` (house House_005, category kitchen)

| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |
|---|---|---|---|---|---|
| 1 | House_008 | kitchen | 0.8614 | NO | YES |
| 2 | House_001 | bedroom | 0.8486 | NO | NO |
| 3 | House_007 | kitchen | 0.8479 | NO | YES |
| 4 | House_009 | kitchen | 0.8474 | NO | YES |
| 5 | House_007 | kitchen | 0.8471 | NO | YES |
| 6 | House_003 | kitchen | 0.8445 | NO | YES |
| 7 | House_021 | kitchen | 0.8257 | NO | YES |
| 8 | House_001 | kitchen | 0.8206 | NO | YES |
| 9 | House_010 | kitchen | 0.8186 | NO | YES |
| 10 | House_019 | kitchen | 0.8115 | NO | YES |

**Query:** `House_010/bathroom_01.jpg` (house House_010, category bathroom)

| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |
|---|---|---|---|---|---|
| 1 | House_014 | bathroom | 0.8513 | NO | YES |
| 2 | House_012 | bathroom | 0.8472 | NO | YES |
| 3 | House_021 | bathroom | 0.8362 | NO | YES |
| 4 | House_019 | bathroom | 0.8197 | NO | YES |
| 5 | House_013 | bathroom | 0.8181 | NO | YES |
| 6 | House_015 | bathroom | 0.8153 | NO | YES |
| 7 | House_017 | bathroom | 0.8010 | NO | YES |
| 8 | House_002 | bathroom | 0.7911 | NO | YES |
| 9 | House_018 | bathroom | 0.7865 | NO | YES |
| 10 | House_020 | bathroom | 0.7740 | NO | YES |

**Query:** `House_010/kitchen_01.jpeg` (house House_010, category kitchen)

| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |
|---|---|---|---|---|---|
| 1 | House_019 | kitchen | 0.9097 | NO | YES |
| 2 | House_021 | kitchen | 0.9042 | NO | YES |
| 3 | House_017 | kitchen | 0.8669 | NO | YES |
| 4 | House_020 | kitchen | 0.8645 | NO | YES |
| 5 | House_008 | kitchen | 0.8620 | NO | YES |
| 6 | House_001 | kitchen | 0.8599 | NO | YES |
| 7 | House_007 | kitchen | 0.8383 | NO | YES |
| 8 | House_007 | kitchen | 0.8340 | NO | YES |
| 9 | House_012 | kitchen | 0.8296 | NO | YES |
| 10 | House_014 | kitchen | 0.8284 | NO | YES |

**Query:** `House_012/kitchen_01.jpg` (house House_012, category kitchen)

| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |
|---|---|---|---|---|---|
| 1 | House_019 | kitchen | 0.8620 | NO | YES |
| 2 | House_001 | kitchen | 0.8346 | NO | YES |
| 3 | House_021 | kitchen | 0.8335 | NO | YES |
| 4 | House_010 | kitchen | 0.8296 | NO | YES |
| 5 | House_020 | kitchen | 0.8225 | NO | YES |
| 6 | House_007 | kitchen | 0.8211 | NO | YES |
| 7 | House_017 | kitchen | 0.8209 | NO | YES |
| 8 | House_001 | bedroom | 0.8061 | NO | NO |
| 9 | House_007 | kitchen | 0.8049 | NO | YES |
| 10 | House_008 | kitchen | 0.8023 | NO | YES |

**Query:** `House_014/bathroom_01.jpg` (house House_014, category bathroom)

| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |
|---|---|---|---|---|---|
| 1 | House_018 | bathroom | 0.8871 | NO | YES |
| 2 | House_019 | bathroom | 0.8699 | NO | YES |
| 3 | House_017 | bathroom | 0.8624 | NO | YES |
| 4 | House_021 | bathroom | 0.8592 | NO | YES |
| 5 | House_010 | bathroom | 0.8513 | NO | YES |
| 6 | House_015 | bathroom | 0.8381 | NO | YES |
| 7 | House_013 | bathroom | 0.8334 | NO | YES |
| 8 | House_020 | bathroom | 0.8283 | NO | YES |
| 9 | House_012 | bathroom | 0.8282 | NO | YES |
| 10 | House_021 | kitchen | 0.7793 | NO | NO |

**Query:** `House_014/bedroom_01.jpg` (house House_014, category bedroom)

| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |
|---|---|---|---|---|---|
| 1 | House_019 | bedroom | 0.8325 | NO | YES |
| 2 | House_020 | living_room | 0.7898 | NO | NO |
| 3 | House_019 | living_room | 0.7862 | NO | NO |
| 4 | House_017 | bedroom | 0.7821 | NO | YES |
| 5 | House_016 | living_room | 0.7814 | NO | NO |
| 6 | House_021 | kitchen | 0.7644 | NO | NO |
| 7 | House_020 | kitchen | 0.7619 | NO | NO |
| 8 | House_020 | bedroom | 0.7612 | NO | YES |
| 9 | House_021 | bedroom | 0.7604 | NO | YES |
| 10 | House_009 | bedroom | 0.7548 | NO | YES |

**Query:** `House_014/kitchen_01.jpg` (house House_014, category kitchen)

| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |
|---|---|---|---|---|---|
| 1 | House_021 | kitchen | 0.8460 | NO | YES |
| 2 | House_019 | kitchen | 0.8325 | NO | YES |
| 3 | House_010 | kitchen | 0.8284 | NO | YES |
| 4 | House_008 | kitchen | 0.8147 | NO | YES |
| 5 | House_018 | kitchen | 0.8099 | NO | YES |
| 6 | House_017 | kitchen | 0.8085 | NO | YES |
| 7 | House_020 | kitchen | 0.7952 | NO | YES |
| 8 | House_005 | kitchen | 0.7883 | NO | YES |
| 9 | House_001 | kitchen | 0.7784 | NO | YES |
| 10 | House_007 | kitchen | 0.7750 | NO | YES |

**Query:** `House_017/bathroom_01.jpg` (house House_017, category bathroom)

| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |
|---|---|---|---|---|---|
| 1 | House_019 | bathroom | 0.9145 | NO | YES |
| 2 | House_021 | bathroom | 0.9096 | NO | YES |
| 3 | House_018 | bathroom | 0.8685 | NO | YES |
| 4 | House_020 | bathroom | 0.8640 | NO | YES |
| 5 | House_012 | bathroom | 0.8632 | NO | YES |
| 6 | House_014 | bathroom | 0.8624 | NO | YES |
| 7 | House_015 | bathroom | 0.8200 | NO | YES |
| 8 | House_010 | bathroom | 0.8010 | NO | YES |
| 9 | House_021 | living_room | 0.7914 | NO | NO |
| 10 | House_013 | bathroom | 0.7911 | NO | YES |

**Query:** `House_018/bathroom_01.jpg` (house House_018, category bathroom)

| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |
|---|---|---|---|---|---|
| 1 | House_014 | bathroom | 0.8871 | NO | YES |
| 2 | House_019 | bathroom | 0.8850 | NO | YES |
| 3 | House_017 | bathroom | 0.8685 | NO | YES |
| 4 | House_020 | bathroom | 0.8422 | NO | YES |
| 5 | House_015 | bathroom | 0.8362 | NO | YES |
| 6 | House_021 | bathroom | 0.8279 | NO | YES |
| 7 | House_012 | bathroom | 0.8245 | NO | YES |
| 8 | House_021 | kitchen | 0.8167 | NO | NO |
| 9 | House_013 | bathroom | 0.7947 | NO | YES |
| 10 | House_007 | master_bedroom | 0.7873 | NO | NO |

**Query:** `House_018/bedroom_01.jpg` (house House_018, category bedroom)

| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |
|---|---|---|---|---|---|
| 1 | House_020 | bedroom | 0.8649 | NO | YES |
| 2 | House_007 | master_bedroom | 0.8562 | NO | NO |
| 3 | House_007 | master_bedroom | 0.8559 | NO | NO |
| 4 | House_019 | bedroom | 0.8546 | NO | YES |
| 5 | House_001 | bedroom | 0.8470 | NO | YES |
| 6 | House_013 | bedroom | 0.8466 | NO | YES |
| 7 | House_019 | living_room | 0.8447 | NO | NO |
| 8 | House_015 | bedroom | 0.8345 | NO | YES |
| 9 | House_005 | bedroom | 0.8330 | NO | YES |
| 10 | House_011 | bedroom | 0.8317 | NO | YES |

**Query:** `House_018/kitchen_01.jpg` (house House_018, category kitchen)

| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |
|---|---|---|---|---|---|
| 1 | House_021 | kitchen | 0.8325 | NO | YES |
| 2 | House_019 | kitchen | 0.8259 | NO | YES |
| 3 | House_010 | kitchen | 0.8207 | NO | YES |
| 4 | House_008 | kitchen | 0.8206 | NO | YES |
| 5 | House_009 | kitchen | 0.8178 | NO | YES |
| 6 | House_014 | kitchen | 0.8099 | NO | YES |
| 7 | House_017 | kitchen | 0.7988 | NO | YES |
| 8 | House_012 | kitchen | 0.7956 | NO | YES |
| 9 | House_020 | kitchen | 0.7894 | NO | YES |
| 10 | House_001 | kitchen | 0.7760 | NO | YES |

**Query:** `House_019/bathroom_01.jpg` (house House_019, category bathroom)

| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |
|---|---|---|---|---|---|
| 1 | House_017 | bathroom | 0.9145 | NO | YES |
| 2 | House_018 | bathroom | 0.8850 | NO | YES |
| 3 | House_012 | bathroom | 0.8808 | NO | YES |
| 4 | House_014 | bathroom | 0.8699 | NO | YES |
| 5 | House_021 | bathroom | 0.8674 | NO | YES |
| 6 | House_020 | bathroom | 0.8655 | NO | YES |
| 7 | House_015 | bathroom | 0.8443 | NO | YES |
| 8 | House_010 | bathroom | 0.8197 | NO | YES |
| 9 | House_021 | living_room | 0.8146 | NO | NO |
| 10 | House_013 | bathroom | 0.8020 | NO | YES |

**Query:** `House_019/kitchen_01.jpg` (house House_019, category kitchen)

| Rank | Retrieved house | Retrieved category | Similarity | Same house? | Same category? |
|---|---|---|---|---|---|
| 1 | House_010 | kitchen | 0.9097 | NO | YES |
| 2 | House_021 | kitchen | 0.9093 | NO | YES |
| 3 | House_020 | kitchen | 0.8960 | NO | YES |
| 4 | House_017 | kitchen | 0.8906 | NO | YES |
| 5 | House_012 | kitchen | 0.8620 | NO | YES |
| 6 | House_001 | kitchen | 0.8590 | NO | YES |
| 7 | House_008 | kitchen | 0.8459 | NO | YES |
| 8 | House_007 | kitchen | 0.8420 | NO | YES |
| 9 | House_007 | kitchen | 0.8382 | NO | YES |
| 10 | House_014 | kitchen | 0.8325 | NO | YES |
