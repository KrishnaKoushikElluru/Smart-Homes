# Per-House Analysis (SigLIP2 primary, DINOv2 for comparison)

Sorted by: (1) highest SigLIP2 top-10 failure count, (2) lowest SigLIP2 Recall@1, (3) House ID. Houses with 0 valid queries (House_011 only) are listed separately at the end - not ranked, since they contribute no property-level queries at all.

| House | Images | Model | Valid Q | R@1 | R@3 | R@5 | R@10 | Avg rank (when found) | Top-10 failures |
|---|---|---|---|---|---|---|---|---|---|
| House_014 | 4 | SigLIP2 | 4 | 0.000 | 0.000 | 0.000 | 0.250 | 6 | 3 |
| House_014 | 4 | DINOv2 | 4 | 0.000 | 0.000 | 0.250 | 0.250 | 4 | 3 |
| House_018 | 4 | SigLIP2 | 4 | 0.000 | 0.250 | 0.250 | 0.250 | 2 | 3 |
| House_018 | 4 | DINOv2 | 4 | 0.000 | 0.000 | 0.000 | 0.000 | n/a | 4 |
| House_010 | 3 | SigLIP2 | 3 | 0.000 | 0.000 | 0.000 | 0.333 | 9 | 2 |
| House_010 | 3 | DINOv2 | 3 | 0.000 | 0.000 | 0.000 | 0.000 | n/a | 3 |
| House_019 | 4 | SigLIP2 | 4 | 0.500 | 0.500 | 0.500 | 0.500 | 1 | 2 |
| House_019 | 4 | DINOv2 | 4 | 0.000 | 0.000 | 0.250 | 0.500 | 6 | 2 |
| House_003 | 3 | SigLIP2 | 3 | 0.000 | 0.333 | 0.333 | 0.667 | 5.500 | 1 |
| House_003 | 3 | DINOv2 | 3 | 0.000 | 0.000 | 0.000 | 0.000 | n/a | 3 |
| House_017 | 4 | SigLIP2 | 4 | 0.250 | 0.750 | 0.750 | 0.750 | 2 | 1 |
| House_017 | 4 | DINOv2 | 4 | 0.000 | 0.000 | 0.250 | 0.500 | 5 | 2 |
| House_012 | 4 | SigLIP2 | 4 | 0.500 | 0.500 | 0.500 | 0.750 | 4 | 1 |
| House_012 | 4 | DINOv2 | 4 | 0.000 | 0.000 | 0.000 | 0.000 | n/a | 4 |
| House_005 | 4 | SigLIP2 | 4 | 0.750 | 0.750 | 0.750 | 0.750 | 1 | 1 |
| House_005 | 4 | DINOv2 | 4 | 0.000 | 0.500 | 0.500 | 0.750 | 3.333 | 1 |
| House_015 | 3 | SigLIP2 | 3 | 0.000 | 0.000 | 0.333 | 1.000 | 6.333 | 0 |
| House_015 | 3 | DINOv2 | 3 | 0.000 | 0.000 | 0.000 | 0.000 | n/a | 3 |
| House_021 | 4 | SigLIP2 | 4 | 0.000 | 0.250 | 0.250 | 1.000 | 6.750 | 0 |
| House_021 | 4 | DINOv2 | 4 | 0.250 | 0.500 | 0.500 | 0.500 | 1.500 | 2 |
| House_001 | 4 | SigLIP2 | 4 | 0.250 | 0.250 | 0.750 | 1.000 | 4.250 | 0 |
| House_001 | 4 | DINOv2 | 4 | 0.000 | 0.000 | 0.000 | 0.000 | n/a | 4 |
| House_008 | 4 | SigLIP2 | 4 | 0.250 | 0.250 | 0.500 | 1.000 | 4.500 | 0 |
| House_008 | 4 | DINOv2 | 4 | 0.000 | 0.000 | 0.000 | 0.000 | n/a | 4 |
| House_004 | 5 | SigLIP2 | 5 | 0.400 | 0.800 | 1.000 | 1.000 | 2.200 | 0 |
| House_004 | 5 | DINOv2 | 5 | 0.000 | 0.800 | 1.000 | 1.000 | 2.800 | 0 |
| House_006 | 4 | SigLIP2 | 4 | 0.500 | 0.750 | 0.750 | 1.000 | 2.750 | 0 |
| House_006 | 4 | DINOv2 | 4 | 0.500 | 0.500 | 0.500 | 0.750 | 3 | 1 |
| House_013 | 4 | SigLIP2 | 4 | 0.500 | 0.750 | 0.750 | 1.000 | 3.250 | 0 |
| House_013 | 4 | DINOv2 | 4 | 0.000 | 0.000 | 0.000 | 0.000 | n/a | 4 |
| House_020 | 4 | SigLIP2 | 4 | 0.500 | 1.000 | 1.000 | 1.000 | 1.500 | 0 |
| House_020 | 4 | DINOv2 | 4 | 0.000 | 0.250 | 0.250 | 0.750 | 6.667 | 1 |
| House_009 | 4 | SigLIP2 | 4 | 0.750 | 1.000 | 1.000 | 1.000 | 1.500 | 0 |
| House_009 | 4 | DINOv2 | 4 | 0.000 | 0.250 | 0.500 | 0.750 | 6 | 1 |
| House_007 | 11 | SigLIP2 | 11 | 0.818 | 0.909 | 1.000 | 1.000 | 1.545 | 0 |
| House_007 | 11 | DINOv2 | 11 | 0.273 | 0.455 | 0.636 | 0.727 | 3.375 | 3 |
| House_002 | 4 | SigLIP2 | 4 | 1.000 | 1.000 | 1.000 | 1.000 | 1 | 0 |
| House_002 | 4 | DINOv2 | 4 | 0.000 | 0.000 | 0.500 | 0.500 | 4.500 | 2 |
| House_016 | 2 | SigLIP2 | 2 | 1.000 | 1.000 | 1.000 | 1.000 | 1 | 0 |
| House_016 | 2 | DINOv2 | 2 | 0.000 | 0.500 | 1.000 | 1.000 | 3 | 0 |

## Houses with zero valid queries

- House_011: 1 image(s) - no same-house positive candidate exists.
