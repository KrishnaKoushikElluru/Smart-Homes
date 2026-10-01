# Source Similarity Analysis (Part 10)

Raw cosine values are NOT compared between SigLIP2 and DINOv2 as if calibrated - only within-model comparisons below are meaningful.

## SigLIP2

| Quantity | n | n missing (undeterminable from existing data) | Mean | Median | Min | Max |
|---|---|---|---|---|---|---|
| Best same-house similarity | 83 | 0 | 0.854 | 0.866 | 0.732 | 1.000 |
| Best same-group wrong-house similarity | 83 | 0 | 0.868 | 0.875 | 0.749 | 0.917 |
| Best cross-group similarity | 32 | 51 | 0.823 | 0.826 | 0.729 | 0.862 |

## DINOv2

| Quantity | n | n missing (undeterminable from existing data) | Mean | Median | Min | Max |
|---|---|---|---|---|---|---|
| Best same-house similarity | 83 | 0 | 0.339 | 0.311 | 0.028 | 1.000 |
| Best same-group wrong-house similarity | 82 | 1 | 0.575 | 0.573 | 0.257 | 0.779 |
| Best cross-group similarity | 70 | 13 | 0.477 | 0.468 | 0.280 | 0.696 |
