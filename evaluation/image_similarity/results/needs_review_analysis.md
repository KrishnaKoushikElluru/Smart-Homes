# Needs-Review Image Analysis (Goal 2)

Both images were deliberately kept as `needs_review` during dataset standardization
(compound/ambiguous original filenames) rather than guessed. Directly inspected here;
**neither file was renamed or altered as a result of this analysis** - this is a
human-review recommendation only.

---

## Image 1: `House_006/needs_review_01.jpeg`

- **Original filename**: `"Parking or sit_out.jpeg"`
- **Current category**: `needs_review`

**Visual interpretation**: A dark stone/slate-tiled covered floor area, shot from
above at the threshold. A pair of sandals sits on a small mat near an open grille/
security door on the left; stacked cardboard boxes and cooking-oil cartons lean
against a discolored teal wall on the right, next to a dark door leading further
inside. No vehicle is visible anywhere in frame. No outdoor sky, railing, or seating
is visible either.

**Proposed category**: **None with confidence** - this does not clearly match
either original candidate. It reads more like a covered entrance passage / foyer /
utility area (shoe-removal point + storage) than a vehicle parking spot (no vehicle,
space looks too narrow) or a typical sit-out (no seating, no outdoor view).

**Confidence: LOW**

**Reason**: Neither "parking" nor "sit_out" is visually well-supported. A vehicle
would be expected for "parking"; open sky/seating would be expected for "sit_out."
Neither is present. Inventing a third category (e.g. "entrance"/"foyer") not already
in this dataset's vocabulary was avoided per instructions.

**Recommendation: Keep `needs_review`.** A human who knows the property should
confirm what this space actually is.

---

## Image 2: `House_009/needs_review_01.jpeg`

- **Original filename**: `"sit_out or balcony.jpeg"`
- **Current category**: `needs_review`

**Visual interpretation**: A covered balcony shot from inside, through a glass
sliding door. Two chairs (one plastic, one wooden) sit on tiled flooring; a
checkered cloth is draped over one chair. A clothesline with a garment hangs across
the opening. Beyond a metal railing: a wide outdoor view of a lake/wetland and
mid-rise apartment buildings, consistent with a high-floor unit. A ceiling fan is
visible in the reflection.

**Proposed category**: **`balcony`** - has a railing, an expansive outdoor view, and
is structurally an enclosed balcony (not an open ground-level sit-out area).

**Confidence: MEDIUM**

**Reason**: The space is furnished with chairs the way a "sit_out" area typically
is in this dataset's own vocabulary (e.g. `House_005/sit_out_01.jpeg`,
`House_007/sit_out_01.jpeg`), so "sit_out" is also defensible - the two terms
genuinely overlap for a furnished balcony. "balcony" is proposed because the
railing + high-rise skyline view is the more visually dominant, structurally
distinguishing feature (this dataset's other `balcony`-labeled image,
`House_008/balcony_01.jpeg`, is also a railed elevated space), but this is not a
confident, unambiguous call.

**Recommendation**: If a human reviewer agrees this is a covered balcony (not a
ground-floor open sit-out), relabel to `balcony`. Given the genuine overlap, keeping
`needs_review` until confirmed is also reasonable - this analysis does not change
the dataset automatically either way.
