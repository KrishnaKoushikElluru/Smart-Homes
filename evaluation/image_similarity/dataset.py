"""
Phase 6 image-similarity benchmark - dataset manifest.

CRITICAL FINDING (read this before using anything below): inspection
of the live MongoDB `properties` collection and static/images/
properties/ found only 8 image FILES across 4 property documents, and
byte-for-byte hashing showed those 8 files are only 5 DISTINCT images
(3 are exact re-uploads of images already used elsewhere):

    static/images/properties/WIN_20241125_13_57_15_Pro.jpg  - dorm-room photo (person + bunk beds)
    static/images/properties/WIN_20241125_13_57_16_Pro.jpg  - same dorm room, different frame
      (== 2b98d81297a547e69270a2697520525b.jpg, byte-identical, re-uploaded
       under property 6a98583d... labeled category="exterior")
    static/images/properties/WIN_20231207_22_49_20_Pro.jpg  - selfie of two people indoors
      (== c40b2b54fc9d46ffbb72a58d6bc287a3.jpg, byte-identical, re-uploaded
       under property 6a98583d... labeled category="bedroom")
    static/images/properties/WIN_20240919_13_26_25_Pro.jpg  - selfie of three people lying down
      (== fbfcaf0ecb844fa6bc60a327f4ac8561.jpg, byte-identical, re-uploaded
       under property 6a98583d... labeled category="living_room")
    static/images/properties/8918826087604660bd2ccfae7bca5230.jpg - a
      downloaded devotional/wallpaper illustration (Radha-Krishna),
      labeled category="other"

NONE of these depict an actual house/apartment room or exterior - they
are personal test photos and one stock wallpaper, uploaded while
exercising the property-listing upload form during earlier development
(most likely this project's own manual QA of the upload feature, not
real seller-submitted listings). The "bedroom"/"living_room"/
"exterior" category labels stored alongside them are placeholder
values clicked through while testing the form - they do NOT describe
the actual visual content, and treating them as ground truth would be
fabricating labels, which the task instructions explicitly forbid.

Per the task's own instruction ("If there are insufficient existing
property images, report that limitation instead of inventing a
dataset"), this module does NOT construct a real-estate visual-
similarity evaluation set from these files. What it DOES provide:

  - `PROPERTY_IMAGE_INVENTORY`: an honest, literal description of what
    each file actually shows (for transparency/audit), explicitly
    flagged `is_genuine_real_estate_photo=False` on every entry.
  - `build_pipeline_smoke_manifest()`: a manifest built from the 5
    distinct files, labeled by their TRUE content (not by invented
    real-estate categories) - used ONLY to sanity-check that the
    embedding pipeline behaves sensibly (e.g. the two photos of the
    SAME physical dorm room should embed more similarly to each other
    than to an unrelated selfie or the wallpaper). This is a pipeline/
    methodology validation, not a real-estate retrieval-accuracy
    benchmark - see docs/PHASE_6_IMAGE_SIMILARITY_BENCHMARK.md.
  - `load_manifest(path)` / `Manifest.from_records(...)`: the generic,
    reusable manifest format any FUTURE genuine, manually-labeled real-
    estate image set should use, so the rest of this benchmark module
    (models.py, benchmark.py) needs no changes once real data exists.
"""

import json
import os

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
PROPERTY_IMAGES_DIR = os.path.join(REPO_ROOT, "static", "images", "properties")


# Literal, honest description of what each file on disk actually shows -
# established by direct visual inspection, not by trusting the stored
# (placeholder) category metadata. See the module docstring above.
PROPERTY_IMAGE_INVENTORY = [
    {
        "path": os.path.join(PROPERTY_IMAGES_DIR, "WIN_20241125_13_57_15_Pro.jpg"),
        "true_content": "dorm_room_photo",
        "description": "Hostel/dorm-style room: bunk beds, hanging clothes, a person standing holding a phone.",
        "stored_category_label": None,
        "is_genuine_real_estate_photo": False,
    },
    {
        "path": os.path.join(PROPERTY_IMAGES_DIR, "WIN_20241125_13_57_16_Pro.jpg"),
        "true_content": "dorm_room_photo",
        "description": "Same dorm room as WIN_..._15, a different frame of the same scene.",
        "stored_category_label": None,
        "is_genuine_real_estate_photo": False,
    },
    {
        "path": os.path.join(PROPERTY_IMAGES_DIR, "2b98d81297a547e69270a2697520525b.jpg"),
        "true_content": "dorm_room_photo",
        "description": "Byte-identical duplicate of WIN_20241125_13_57_16_Pro.jpg, re-uploaded and stored with category label \"exterior\" (label does not match content).",
        "stored_category_label": "exterior",
        "is_genuine_real_estate_photo": False,
    },
    {
        "path": os.path.join(PROPERTY_IMAGES_DIR, "WIN_20231207_22_49_20_Pro.jpg"),
        "true_content": "personal_selfie_photo",
        "description": "Close-up selfie of two people indoors, cupboard and a wall shelf in the background.",
        "stored_category_label": None,
        "is_genuine_real_estate_photo": False,
    },
    {
        "path": os.path.join(PROPERTY_IMAGES_DIR, "c40b2b54fc9d46ffbb72a58d6bc287a3.jpg"),
        "true_content": "personal_selfie_photo",
        "description": "Byte-identical duplicate of WIN_20231207_22_49_20_Pro.jpg, re-uploaded and stored with category label \"bedroom\" (label does not match content).",
        "stored_category_label": "bedroom",
        "is_genuine_real_estate_photo": False,
    },
    {
        "path": os.path.join(PROPERTY_IMAGES_DIR, "WIN_20240919_13_26_25_Pro.jpg"),
        "true_content": "personal_selfie_photo",
        "description": "Blurry selfie of three people lying down, luggage in the background.",
        "stored_category_label": None,
        "is_genuine_real_estate_photo": False,
    },
    {
        "path": os.path.join(PROPERTY_IMAGES_DIR, "fbfcaf0ecb844fa6bc60a327f4ac8561.jpg"),
        "true_content": "personal_selfie_photo",
        "description": "Byte-identical duplicate of WIN_20240919_13_26_25_Pro.jpg, re-uploaded and stored with category label \"living_room\" (label does not match content).",
        "stored_category_label": "living_room",
        "is_genuine_real_estate_photo": False,
    },
    {
        "path": os.path.join(PROPERTY_IMAGES_DIR, "8918826087604660bd2ccfae7bca5230.jpg"),
        "true_content": "devotional_wallpaper",
        "description": "Downloaded digital-art wallpaper (Radha-Krishna illustration), not a photo at all.",
        "stored_category_label": "other",
        "is_genuine_real_estate_photo": False,
    },
]


class Manifest:
    """A list of image records - the format models.py/benchmark.py
    consume. Every record needs "id" and "path"; beyond that, whatever
    grouping field(s) a given manifest evaluates against are up to the
    caller (e.g. "label" for the older pipeline-smoke manifest below,
    or "house_id"/"category" for the pilot dataset's property-level and
    category-level evaluation - see scan_pilot_dataset())."""

    def __init__(self, records):
        self.records = records

    @classmethod
    def from_records(cls, records):
        for record in records:
            for required_key in ("id", "path"):
                if required_key not in record:
                    raise ValueError(f"manifest record missing required key {required_key!r}: {record!r}")
        return cls(records)

    def __len__(self):
        return len(self.records)

    def __iter__(self):
        return iter(self.records)


def load_manifest(path):
    """Loads a manifest JSON file: a list of objects with at least
    "id", "path", "label" (and optionally "property_id"). This is the
    format any future genuine, manually-labeled real-estate dataset
    should be provided in - see the module docstring."""

    with open(path, "r", encoding="utf-8") as f:
        records = json.load(f)

    return Manifest.from_records(records)


# ============================================================
# PILOT DATASET (Phase 6 Step 1 pilot) - properties/House_<N>/*.jpeg
#
# A genuine, real-property image set the user collected specifically
# for this benchmark: 8 houses, 39 images total, at the time this code
# was written (verified below by scan_pilot_dataset(), never assumed).
# This is a SEPARATE dataset from PROPERTY_IMAGE_INVENTORY above (the
# static/images/properties/ test-upload artifacts) - that finding and
# this one do not overwrite each other; both are preserved.
#
# Category labels here come from the image FILENAME itself (e.g.
# "Bed_Room.jpeg", "Kitchen_Room_1.jpeg"), which is legitimate real
# metadata: the user named each file after the room it depicts while
# collecting the dataset, unlike static/images/properties/'s stored
# "category" field (which was clicked-through placeholder data - see
# above). Filenames are normalized (case folded, trailing "_<digits>"
# stripped - e.g. "Bed_Room_1" and "Bed_Room" both become "bed_room",
# since a trailing number consistently marks "another photo of the
# same room" throughout this dataset) but NEVER remapped onto a
# different vocabulary (e.g. "sit_out" is kept as "sit_out", not
# guessed to mean "balcony" or "exterior") - see
# docs/PHASE_6_IMAGE_SIMILARITY_BENCHMARK.md for the full category
# list this produced and why near-synonyms (e.g. "bed_room" vs
# "master_bedroom" vs "common_bed_room") were deliberately NOT merged.
# ============================================================

import hashlib
import re

PILOT_DATASET_ROOT = os.path.join(REPO_ROOT, "properties")

# Category value assigned to images whose room type could not be
# confidently determined from filename metadata (e.g. a genuinely
# compound/ambiguous original filename like "Parking or sit_out.jpeg" -
# see rename_dataset.py's CATEGORY_MAPPING for where this is assigned).
# Single source of truth: rename_dataset.py imports this rather than
# redefining it, and callers (benchmark.py) exclude records with this
# category from category-level evaluation, since "needs_review" is a
# placeholder, not a real room type - grouping by it would be
# meaningless (or worse, a false positive if two unrelated ambiguous
# images from different houses happened to share it).
AMBIGUOUS_CATEGORY_TOKEN = "needs_review"

_TRAILING_NUMBER_RE = re.compile(r"_\d+$")


def sha256_of_file(path):
    """Cryptographic (SHA-256) content hash of a file, read in one
    shot (these are small JPEGs, not large enough to need chunked
    reading). Used for duplicate-content detection in
    scan_pilot_dataset() and for the explicit Part A duplicate
    verification in benchmark.py's duplicate-sensitivity analysis -
    SHA-256 rather than MD5 specifically because the task asked for a
    cryptographic hash for that verification step."""

    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def normalize_category_from_filename(filename):
    """Pure function, no disk access: "Bed_Room_1.jpeg" -> "bed_room",
    "Parking or sit_out.jpeg" -> "parking_or_sit_out". Deterministic
    and side-effect-free so it's directly unit-testable without a real
    dataset on disk."""

    stem = os.path.splitext(filename)[0]
    stem = _TRAILING_NUMBER_RE.sub("", stem)
    stem = stem.strip().lower()
    stem = re.sub(r"[\s_]+", "_", stem)
    return stem


class PilotDatasetIssue:
    """One human-readable problem/observation surfaced while scanning
    the pilot dataset - collected and reported, never used to silently
    skip or "fix" an image (see scan_pilot_dataset())."""

    def __init__(self, severity, message):
        self.severity = severity  # "info" | "warning"
        self.message = message

    def __repr__(self):
        return f"[{self.severity}] {self.message}"


def scan_pilot_dataset(root=None):
    """Scans properties/House_<N>/*.jpeg into a Manifest, validating
    every image and preserving every readable one - never deletes,
    reassigns, or excludes an image based on its content. Returns
    (Manifest, summary: dict, issues: list[PilotDatasetIssue]).

    Validates, per image: the file exists and is readable, PIL can
    open AND verify it as a real image, and its house_id (parent
    directory name) is present. A house directory with zero image
    files (e.g. a placeholder for a house not photographed yet) is
    reported, not treated as an error. An unreadable/corrupt file is
    reported and excluded from the MANIFEST (it has no valid
    embedding-able content) but never deleted from disk, and the
    caller's dataset summary still counts it under "unreadable" so
    nothing silently vanishes from the report.

    Duplicate handling: images are de-duplicated by PATH only (so
    re-scanning never double-counts the same file) - byte-identical
    CONTENT duplicates across different filenames (which do occur in
    this dataset, e.g. within a single house) are preserved as
    separate manifest entries and only flagged as an issue, since per
    this task's instructions no existing image may be silently
    dropped.
    """

    root = root or PILOT_DATASET_ROOT
    issues = []
    records = []
    seen_paths = set()
    content_hashes = {}  # sha256 -> [record_id, ...]
    house_image_counts = {}
    category_counts = {}
    format_counts = {}
    n_unreadable = 0

    if not os.path.isdir(root):
        issues.append(PilotDatasetIssue("warning", f"pilot dataset root does not exist: {root}"))
        return Manifest.from_records([]), {
            "root": root,
            "n_houses_with_images": 0,
            "n_houses_total": 0,
            "n_houses_empty": 0,
            "n_images": 0,
            "images_per_house": {},
            "categories": {},
            "formats": {},
            "n_unreadable": 0,
            "duplicate_groups": [],
        }, issues

    house_dirs = sorted(
        entry for entry in os.listdir(root)
        if os.path.isdir(os.path.join(root, entry))
    )

    n_empty_houses = 0

    for house_id in house_dirs:
        house_dir = os.path.join(root, house_id)
        filenames = sorted(
            f for f in os.listdir(house_dir)
            if os.path.isfile(os.path.join(house_dir, f))
        )

        if not filenames:
            n_empty_houses += 1
            issues.append(PilotDatasetIssue("info", f"{house_id}: no image files (empty/placeholder house directory)"))
            continue

        house_count = 0

        for filename in filenames:
            path = os.path.join(house_dir, filename)

            if path in seen_paths:
                issues.append(PilotDatasetIssue("warning", f"duplicate path scanned twice, counted once: {path}"))
                continue
            seen_paths.add(path)

            try:
                with open(path, "rb") as f:
                    data = f.read()
            except OSError as exc:
                n_unreadable += 1
                issues.append(PilotDatasetIssue("warning", f"{path}: could not read file ({exc})"))
                continue

            try:
                from PIL import Image, UnidentifiedImageError
                from io import BytesIO
                image = Image.open(BytesIO(data))
                image.verify()
                # verify() invalidates the Image object for further use
                # (per Pillow's own docs) - re-open to read format/size.
                image = Image.open(BytesIO(data))
                image_format = image.format
                image_size = image.size
            except Exception as exc:  # noqa: BLE001 - report, never crash the scan
                n_unreadable += 1
                issues.append(PilotDatasetIssue("warning", f"{path}: not a valid/readable image ({exc})"))
                continue

            file_hash = hashlib.sha256(data).hexdigest()
            image_id = f"{house_id}/{filename}"
            content_hashes.setdefault(file_hash, []).append(image_id)
            format_counts[image_format] = format_counts.get(image_format, 0) + 1

            category = normalize_category_from_filename(filename)
            category_counts[category] = category_counts.get(category, 0) + 1

            records.append({
                "id": image_id,
                "path": path,
                "house_id": house_id,
                "category": category,
                "filename": filename,
                "sha256": file_hash,
                "format": image_format,
                "width": image_size[0],
                "height": image_size[1],
            })
            house_count += 1

        house_image_counts[house_id] = house_count

    duplicate_groups = []
    for file_hash, image_ids in content_hashes.items():
        if len(image_ids) > 1:
            duplicate_groups.append({"sha256": file_hash, "image_ids": image_ids})
            issues.append(PilotDatasetIssue(
                "warning",
                f"byte-identical image content reused across filenames (same photo, different names): {image_ids}",
            ))

    houses_with_images = {h: c for h, c in house_image_counts.items() if c > 0}

    summary = {
        "root": root,
        "n_houses_total": len(house_dirs),
        "n_houses_with_images": len(houses_with_images),
        "n_houses_empty": n_empty_houses,
        "n_images": len(records),
        "images_per_house": houses_with_images,
        "categories": dict(sorted(category_counts.items())),
        "formats": dict(sorted(format_counts.items())),
        "n_unreadable": n_unreadable,
        "duplicate_groups": duplicate_groups,
    }

    return Manifest.from_records(records), summary, issues


def build_pilot_manifest(root=None):
    """Convenience wrapper: scan_pilot_dataset() but returning only
    the Manifest, for callers (benchmark.py) that just need images to
    embed. Prefer scan_pilot_dataset() directly when the summary/issues
    matter too (e.g. printing the dataset report)."""

    manifest, _summary, _issues = scan_pilot_dataset(root)
    return manifest


def build_pipeline_smoke_manifest():
    """A manifest built ONLY from the 5 distinct files described in
    PROPERTY_IMAGE_INVENTORY, labeled by their TRUE content (dorm-room
    photo / personal selfie / wallpaper) - NOT invented real-estate
    categories. Byte-identical duplicates are excluded (deduplicated by
    file hash) so a "duplicate of the same upload" is never mistaken
    for "the model found a genuine near-duplicate".

    This exists to sanity-check the embedding pipeline mechanically
    (do the two distinct photos of the SAME physical dorm room end up
    closer to each other than to unrelated content?) - it is NOT a
    real-estate visual-similarity evaluation set and must never be
    reported as one. See docs/PHASE_6_IMAGE_SIMILARITY_BENCHMARK.md.
    """

    import hashlib

    seen_hashes = {}
    records = []

    for entry in PROPERTY_IMAGE_INVENTORY:
        path = entry["path"]

        if not os.path.isfile(path):
            continue

        with open(path, "rb") as f:
            file_hash = hashlib.md5(f.read()).hexdigest()

        if file_hash in seen_hashes:
            continue

        seen_hashes[file_hash] = path

        records.append({
            "id": os.path.basename(path),
            "path": path,
            "label": entry["true_content"],
            "property_id": None,
            "description": entry["description"],
        })

    return Manifest.from_records(records)
