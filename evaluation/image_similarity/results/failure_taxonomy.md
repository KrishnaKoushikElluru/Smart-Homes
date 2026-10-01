# SigLIP2 Top-10 Failure Taxonomy

Codes: A=same-category wrong-house, B=visually-similar different-room, C=strong visual ambiguity (visual inspection only), D=insufficient same-house visual variation, E=potential data-quality issue (visual inspection only), F=duplicate-related, G=other, Unclear=insufficient evidence. Multiple codes may apply; C and E require the separate manual visual-inspection notes below (not assigned automatically).

## Manual visual-inspection finding (code E)

Direct visual inspection (`Read` on the actual image files, not automated) of a
sample spanning ALL 12 houses in the `House_010`-`House_021` batch (2 sampled
categories per house on average - kitchen, bathroom, bedroom, and living_room all
checked at least once) found a **visible "magicbricks" watermark in every single
sampled image from that batch**, with no exceptions found. Three sampled images
from the original `House_001`-`House_009` batch (bathroom and kitchen photos) show
**no such watermark** and visually read as genuine, personally-photographed, lived-in
spaces.

**OBSERVED**: `magicbricks` (a real-estate listing portal) text is visibly overlaid
on photos from House_010, 011, 012, 013, 014, 015, 016, 017, 018, 019, 020, and 021
- confirmed directly, not inferred from metadata.

**INTERPRETATION**: These images very likely originate from MagicBricks property
listings rather than being personally photographed for this dataset. This does not
necessarily mean they depict fake or non-existent properties (MagicBricks lists many
genuinely distinct real units), but it does mean:
1. Their photographic style (professional real-estate listing photography - wide-
   angle lens, consistent staging/lighting conventions) differs systematically from
   the original batch's personal phone photos, which is a plausible confound for
   the cross-house visual similarity seen in kitchen/bathroom failures below.
2. Whether all 12 are genuinely 12 *different* physical properties, or could include
   repeated show-flat/template photography reused across multiple listings by the
   same builder, **cannot be determined from the images alone** - this is flagged
   as an open question for the team, not resolved here.

This finding is applied below as taxonomy code **E** to every failure where BOTH the
query and its wrong top-1 result are within this watermarked batch (12 of 14
SigLIP2 failures - see the table).

## Code frequency (automatic pass only - see manual notes for C/E)

- A: 14
- D: 3
- E: 12

## Every failure

| Query | House | Category | Top-1 retrieved | Top-1 house | Top-1 category | Codes | Evidence |
|---|---|---|---|---|---|---|---|
| House_003/kitchen_01.jpeg | House_003 | kitchen | House_004/kitchen_01.jpeg | House_004 | kitchen | A, D | Top-1 (House_004/kitchen_01.jpeg) is the same category (kitchen) from house House_004. Query's house (House_003) has only 3 images total - little same-house material to match against. |
| House_005/kitchen_01.jpeg | House_005 | kitchen | House_008/kitchen_01.jpeg | House_008 | kitchen | A | Top-1 (House_008/kitchen_01.jpeg) is the same category (kitchen) from house House_008. |
| House_010/bathroom_01.jpg | House_010 | bathroom | House_014/bathroom_01.jpg | House_014 | bathroom | A, D, E | Top-1 (House_014/bathroom_01.jpg) is the same category (bathroom) from house House_014. Query's house (House_010) has only 3 images total - little same-house material to match against. Both query and top-1 result are from the House_010-House_021 batch, where direct visual inspection found a 'magicbricks' watermark in every sampled image (see needs_review_analysis.md / README.md) - these may be sourced from a real-estate listing site rather than personally photographed, which could make listing-style photos of DIFFERENT actual properties more visually similar to each other than personal photos would be. |
| House_010/kitchen_01.jpeg | House_010 | kitchen | House_019/kitchen_01.jpg | House_019 | kitchen | A, D, E | Top-1 (House_019/kitchen_01.jpg) is the same category (kitchen) from house House_019. Query's house (House_010) has only 3 images total - little same-house material to match against. Both query and top-1 result are from the House_010-House_021 batch, where direct visual inspection found a 'magicbricks' watermark in every sampled image (see needs_review_analysis.md / README.md) - these may be sourced from a real-estate listing site rather than personally photographed, which could make listing-style photos of DIFFERENT actual properties more visually similar to each other than personal photos would be. |
| House_012/kitchen_01.jpg | House_012 | kitchen | House_019/kitchen_01.jpg | House_019 | kitchen | A, E | Top-1 (House_019/kitchen_01.jpg) is the same category (kitchen) from house House_019. Both query and top-1 result are from the House_010-House_021 batch, where direct visual inspection found a 'magicbricks' watermark in every sampled image (see needs_review_analysis.md / README.md) - these may be sourced from a real-estate listing site rather than personally photographed, which could make listing-style photos of DIFFERENT actual properties more visually similar to each other than personal photos would be. |
| House_014/bathroom_01.jpg | House_014 | bathroom | House_018/bathroom_01.jpg | House_018 | bathroom | A, E | Top-1 (House_018/bathroom_01.jpg) is the same category (bathroom) from house House_018. Both query and top-1 result are from the House_010-House_021 batch, where direct visual inspection found a 'magicbricks' watermark in every sampled image (see needs_review_analysis.md / README.md) - these may be sourced from a real-estate listing site rather than personally photographed, which could make listing-style photos of DIFFERENT actual properties more visually similar to each other than personal photos would be. |
| House_014/bedroom_01.jpg | House_014 | bedroom | House_019/bedroom_01.jpg | House_019 | bedroom | A, E | Top-1 (House_019/bedroom_01.jpg) is the same category (bedroom) from house House_019. Both query and top-1 result are from the House_010-House_021 batch, where direct visual inspection found a 'magicbricks' watermark in every sampled image (see needs_review_analysis.md / README.md) - these may be sourced from a real-estate listing site rather than personally photographed, which could make listing-style photos of DIFFERENT actual properties more visually similar to each other than personal photos would be. |
| House_014/kitchen_01.jpg | House_014 | kitchen | House_021/kitchen_01.jpeg | House_021 | kitchen | A, E | Top-1 (House_021/kitchen_01.jpeg) is the same category (kitchen) from house House_021. Both query and top-1 result are from the House_010-House_021 batch, where direct visual inspection found a 'magicbricks' watermark in every sampled image (see needs_review_analysis.md / README.md) - these may be sourced from a real-estate listing site rather than personally photographed, which could make listing-style photos of DIFFERENT actual properties more visually similar to each other than personal photos would be. |
| House_017/bathroom_01.jpg | House_017 | bathroom | House_019/bathroom_01.jpg | House_019 | bathroom | A, E | Top-1 (House_019/bathroom_01.jpg) is the same category (bathroom) from house House_019. Both query and top-1 result are from the House_010-House_021 batch, where direct visual inspection found a 'magicbricks' watermark in every sampled image (see needs_review_analysis.md / README.md) - these may be sourced from a real-estate listing site rather than personally photographed, which could make listing-style photos of DIFFERENT actual properties more visually similar to each other than personal photos would be. |
| House_018/bathroom_01.jpg | House_018 | bathroom | House_014/bathroom_01.jpg | House_014 | bathroom | A, E | Top-1 (House_014/bathroom_01.jpg) is the same category (bathroom) from house House_014. Both query and top-1 result are from the House_010-House_021 batch, where direct visual inspection found a 'magicbricks' watermark in every sampled image (see needs_review_analysis.md / README.md) - these may be sourced from a real-estate listing site rather than personally photographed, which could make listing-style photos of DIFFERENT actual properties more visually similar to each other than personal photos would be. |
| House_018/bedroom_01.jpg | House_018 | bedroom | House_020/bedroom_01.jpeg | House_020 | bedroom | A, E | Top-1 (House_020/bedroom_01.jpeg) is the same category (bedroom) from house House_020. Both query and top-1 result are from the House_010-House_021 batch, where direct visual inspection found a 'magicbricks' watermark in every sampled image (see needs_review_analysis.md / README.md) - these may be sourced from a real-estate listing site rather than personally photographed, which could make listing-style photos of DIFFERENT actual properties more visually similar to each other than personal photos would be. |
| House_018/kitchen_01.jpg | House_018 | kitchen | House_021/kitchen_01.jpeg | House_021 | kitchen | A, E | Top-1 (House_021/kitchen_01.jpeg) is the same category (kitchen) from house House_021. Both query and top-1 result are from the House_010-House_021 batch, where direct visual inspection found a 'magicbricks' watermark in every sampled image (see needs_review_analysis.md / README.md) - these may be sourced from a real-estate listing site rather than personally photographed, which could make listing-style photos of DIFFERENT actual properties more visually similar to each other than personal photos would be. |
| House_019/bathroom_01.jpg | House_019 | bathroom | House_017/bathroom_01.jpg | House_017 | bathroom | A, E | Top-1 (House_017/bathroom_01.jpg) is the same category (bathroom) from house House_017. Both query and top-1 result are from the House_010-House_021 batch, where direct visual inspection found a 'magicbricks' watermark in every sampled image (see needs_review_analysis.md / README.md) - these may be sourced from a real-estate listing site rather than personally photographed, which could make listing-style photos of DIFFERENT actual properties more visually similar to each other than personal photos would be. |
| House_019/kitchen_01.jpg | House_019 | kitchen | House_010/kitchen_01.jpeg | House_010 | kitchen | A, E | Top-1 (House_010/kitchen_01.jpeg) is the same category (kitchen) from house House_010. Both query and top-1 result are from the House_010-House_021 batch, where direct visual inspection found a 'magicbricks' watermark in every sampled image (see needs_review_analysis.md / README.md) - these may be sourced from a real-estate listing site rather than personally photographed, which could make listing-style photos of DIFFERENT actual properties more visually similar to each other than personal photos would be. |
