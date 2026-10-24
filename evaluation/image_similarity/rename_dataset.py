"""
Phase 6 dataset standardization - house folder + filename normalization
for properties/House_<N> and properties/HOUSE<N> into a single
consistent House_<NNN>/<category>_<NN>.<ext> convention.

ISOLATED, one-shot utility - not imported by app.py/routes/services,
not part of the normal benchmark run. Run explicitly:

    python evaluation/image_similarity/rename_dataset.py            # dry run, prints report only
    python evaluation/image_similarity/rename_dataset.py --execute  # performs the renames

SAFETY MODEL:
  - Renaming is a pure filesystem move (os.rename) - it never reads,
    re-encodes, or rewrites image bytes, so content cannot change as a
    side effect of this script (verified anyway, via SHA-256 before/
    after, because "trust the OS" is not the same as "verify").
  - Two-pass execution: ALL files are renamed first (still inside
    their ORIGINAL house directory), THEN house directories are
    renamed. This avoids ever needing to rename a file at the same
    moment as its parent directory changes identity.
  - Every rename target is checked for pre-existing collisions before
    any file is touched - if the full manifest is not collision-free,
    nothing is renamed and the collision is reported instead.
  - No image is ever deleted. No image is ever overwritten (a
    destination that already exists aborts the whole run instead).

HOUSE FOLDER NAMING COLLISION (read before touching HOUSE_MAPPING):
inspection found TWO naming styles present, e.g. both "House_1" and
"HOUSE1" exist as separate directories. Byte-for-byte SHA-256 hashing
(see dataset.scan_pilot_dataset()/this module's inventory) confirmed
they are NOT the same property re-uploaded under a different name -
every image in "HOUSE1".."HOUSE12" has a SHA-256 hash that does not
match ANY image anywhere in "House_1".."House_9" - they are genuinely
21 distinct properties, not 9. Naively mapping by the embedded number
(House_1 -> House_001, HOUSE1 -> House_001) would silently collide two
different real properties onto the same standardized folder - NOT
done here. Instead: the original "House_<N>" batch (the earlier pilot,
9 houses) keeps House_001..House_009 in its existing numeric order,
and the newer "HOUSE<N>" batch continues House_010 onward in ITS
numeric order - a deterministic, collision-free, and historically-
continuous numbering (the original pilot's houses keep their relative
identity), not an arbitrary reshuffle.

CATEGORY MAPPING (read before touching CATEGORY_MAPPING):
built from the exact set of room-name tokens actually found on disk
(see build_rename_manifest()'s inventory step) - not invented. Two
filenames are genuinely ambiguous compound room names
("Parking or sit_out.jpeg" in House_6, "sit_out or balcony.jpeg" in
House_9) and are NOT force-mapped to either category: both keep the
placeholder category "needs_review" (excluded from category-level
evaluation, included as-is in property-level evaluation, since their
HOUSE identity is not in question, only their precise room type).
"""

import argparse
import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from evaluation.image_similarity.dataset import (
    PILOT_DATASET_ROOT,
    sha256_of_file,
    AMBIGUOUS_CATEGORY_TOKEN,
)

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")

# ============================================================
# HOUSE FOLDER MAPPING
# ============================================================

_OLD_STYLE_RE = re.compile(r"^House_(\d+)$")       # e.g. "House_1"
_NEW_STYLE_RE = re.compile(r"^HOUSE(\d+)$")        # e.g. "HOUSE1"


def build_house_mapping(house_dirs):
    """Deterministic, collision-free house-folder mapping - see this
    module's docstring for why old-style and new-style houses are
    numbered in two separate contiguous ranges rather than by their
    embedded number directly."""

    old_style = []
    new_style = []
    unrecognized = []

    for name in house_dirs:
        m_old = _OLD_STYLE_RE.match(name)
        m_new = _NEW_STYLE_RE.match(name)
        if m_old:
            old_style.append((int(m_old.group(1)), name))
        elif m_new:
            new_style.append((int(m_new.group(1)), name))
        else:
            unrecognized.append(name)

    old_style.sort()
    new_style.sort()

    mapping = {}
    next_number = 1
    for _original_number, name in old_style:
        mapping[name] = f"House_{next_number:03d}"
        next_number += 1
    for _original_number, name in new_style:
        mapping[name] = f"House_{next_number:03d}"
        next_number += 1

    return mapping, unrecognized


# ============================================================
# CATEGORY MAPPING
# ============================================================

_TRAILING_NUMBER_RE = re.compile(r"_(\d+)$")

# raw token (lowercased, spaces/underscores collapsed to "_", trailing
# _<digits> already stripped) -> standardized target category. Every
# entry here was found on disk during inspection (see this module's
# docstring) - nothing in this table is speculative.
CATEGORY_MAPPING = {
    "bed_room": "bedroom",
    "bedroom": "bedroom",
    "living_room": "living_room",
    "living": "living_room",
    "kitchen_room": "kitchen",
    "kitchen": "kitchen",
    "bath_room": "bathroom",
    "bathroom": "bathroom",
    "sit_out": "sit_out",
    "balcony": "balcony",
    "common_bed_room": "common_bedroom",
    "master_bedroom": "master_bedroom",
    "devotional_room": "devotional_room",
}

# Raw tokens that are genuinely ambiguous compound room names - found
# verbatim on disk, never force-mapped to one of their component
# categories. Both instances are handled explicitly below.
# (AMBIGUOUS_CATEGORY_TOKEN itself is defined once in dataset.py and
# imported above - single source of truth with benchmark.py's
# category-level exclusion logic.)

_AMBIGUOUS_RAW_TOKENS = {
    "parking_or_sit_out",   # House_6/"Parking or sit_out.jpeg"
    "sit_out_or_balcony",   # House_9/"sit_out or balcony.jpeg"
}


def _raw_token_and_suffix(filename):
    """"Living_Room_2.jpeg" -> ("living_room", 2); "Bed_Room.jpeg" ->
    ("bed_room", 0) - suffix 0 means "no explicit suffix", which the
    view-numbering rule (see build_rename_manifest()) treats as the
    FIRST view, consistent with Step 4's examples."""

    stem = os.path.splitext(filename)[0]
    m = _TRAILING_NUMBER_RE.search(stem)
    if m:
        suffix = int(m.group(1))
        stem = stem[: m.start()]
    else:
        suffix = 0

    stem = stem.strip().lower()
    stem = re.sub(r"[\s_]+", "_", stem)
    return stem, suffix


def map_category(raw_token):
    """Returns (standardized_category, is_ambiguous). Never guesses:
    an unrecognized raw token not already in CATEGORY_MAPPING or
    _AMBIGUOUS_RAW_TOKENS is treated the same as an ambiguous one
    (flagged, not silently invented) - this can only happen if a NEW,
    previously-unseen filename pattern is added to the dataset later."""

    if raw_token in CATEGORY_MAPPING:
        return CATEGORY_MAPPING[raw_token], False
    return AMBIGUOUS_CATEGORY_TOKEN, True


# ============================================================
# MANIFEST
# ============================================================

def build_rename_manifest(root=None):
    """Scans the CURRENT (pre-rename) properties/ tree and builds the
    complete rename manifest, without touching any file. Returns
    (manifest: list[dict], house_mapping: dict, warnings: list[str])."""

    root = root or PILOT_DATASET_ROOT
    warnings = []

    house_dirs = sorted(
        entry for entry in os.listdir(root)
        if os.path.isdir(os.path.join(root, entry))
    )

    house_mapping, unrecognized_houses = build_house_mapping(house_dirs)
    for name in unrecognized_houses:
        warnings.append(f"House directory name not recognized by either naming pattern, skipped: {name!r}")

    manifest = []

    for house_original in house_dirs:
        if house_original not in house_mapping:
            continue

        house_standardized = house_mapping[house_original]
        house_dir = os.path.join(root, house_original)
        filenames = sorted(
            f for f in os.listdir(house_dir)
            if os.path.isfile(os.path.join(house_dir, f))
        )

        # Group files by their FINAL mapped category, not by raw token -
        # two different raw spellings that map to the same category
        # (e.g. "bed_room" and "bedroom" both -> "bedroom") must share
        # ONE view-numbering sequence, or they could each independently
        # produce "bedroom_01" and collide. All of today's houses only
        # use one naming style internally, so this hasn't been
        # observed in practice, but grouping by the pre-mapping token
        # was fragile - fixed here rather than left as a latent bug.
        groups = {}
        ambiguous_raw_tokens_seen = {}
        for filename in filenames:
            raw_token, suffix = _raw_token_and_suffix(filename)
            category, is_ambiguous = map_category(raw_token)
            groups.setdefault(category, []).append((suffix, filename))
            if is_ambiguous:
                ambiguous_raw_tokens_seen.setdefault(category, []).append((raw_token, filename))

        for category, entries in groups.items():
            is_ambiguous = category == AMBIGUOUS_CATEGORY_TOKEN
            if is_ambiguous:
                for raw_token, filename in ambiguous_raw_tokens_seen[category]:
                    warnings.append(
                        f"{house_original}: ambiguous/unrecognized room token {raw_token!r} "
                        f"(from {filename!r}) - kept as category={AMBIGUOUS_CATEGORY_TOKEN!r}, "
                        "not force-mapped, excluded from category-level evaluation."
                    )

            # Deterministic view ordering: by existing numeric suffix
            # (no-suffix file first), tie-broken by filename.
            entries.sort(key=lambda pair: (pair[0], pair[1]))

            for view_index, (_suffix, filename) in enumerate(entries, start=1):
                original_path = os.path.join(house_dir, filename)
                extension = os.path.splitext(filename)[1].lower()  # preserved as-is, never forced to .jpg
                image_standardized = f"{category}_{view_index:02d}{extension}"

                manifest.append({
                    "house_original": house_original,
                    "house_standardized": house_standardized,
                    "image_original": filename,
                    "image_standardized": image_standardized,
                    "category": category,
                    "category_ambiguous": is_ambiguous,
                    "view_number": view_index,
                    "sha256_before": sha256_of_file(original_path),
                    "size_before": os.path.getsize(original_path),
                    "original_path": original_path,
                })

    return manifest, house_mapping, warnings


def find_collisions(manifest):
    """Every (house_standardized, image_standardized) target must be
    unique - returns a list of collision descriptions (empty if none).
    This MUST be empty before any rename is executed."""

    targets = {}
    collisions = []
    for record in manifest:
        key = (record["house_standardized"], record["image_standardized"])
        if key in targets:
            collisions.append(
                f"Target collision {key}: {targets[key]['house_original']}/{targets[key]['image_original']} "
                f"and {record['house_original']}/{record['image_original']} both map to it"
            )
        else:
            targets[key] = record
    return collisions


# ============================================================
# EXECUTION (only reached with --execute)
# ============================================================

def execute_rename(manifest, root=None):
    """Performs the actual two-pass rename (files, then directories),
    verifying SHA-256 + file count identically before/after. Returns a
    verification report dict. Raises RuntimeError (without partially
    completing) if a pre-flight collision or missing-source check
    fails - nothing is renamed unless the ENTIRE manifest is safe."""

    root = root or PILOT_DATASET_ROOT

    collisions = find_collisions(manifest)
    if collisions:
        raise RuntimeError("Refusing to rename: target collisions found:\n" + "\n".join(collisions))

    for record in manifest:
        if not os.path.isfile(record["original_path"]):
            raise RuntimeError(f"Refusing to rename: source file missing: {record['original_path']}")

    # ---- Pass 1: rename files, still inside their ORIGINAL house dir ----
    for record in manifest:
        house_dir = os.path.dirname(record["original_path"])
        new_path_same_dir = os.path.join(house_dir, record["image_standardized"])

        if os.path.exists(new_path_same_dir) and new_path_same_dir != record["original_path"]:
            raise RuntimeError(f"Refusing to overwrite existing file: {new_path_same_dir}")

        os.rename(record["original_path"], new_path_same_dir)
        record["_path_after_pass1"] = new_path_same_dir

    # ---- Pass 2: rename house directories ----
    house_dir_mapping = {}
    for record in manifest:
        house_dir_mapping[record["house_original"]] = record["house_standardized"]

    for house_original, house_standardized in house_dir_mapping.items():
        old_dir = os.path.join(root, house_original)
        new_dir = os.path.join(root, house_standardized)
        if os.path.exists(new_dir) and os.path.abspath(new_dir) != os.path.abspath(old_dir):
            raise RuntimeError(f"Refusing to overwrite existing directory: {new_dir}")
        if os.path.abspath(old_dir) != os.path.abspath(new_dir):
            os.rename(old_dir, new_dir)

    # ---- Verification ----
    verification = {"ok": True, "issues": []}

    final_files = 0
    for record in manifest:
        final_path = os.path.join(root, record["house_standardized"], record["image_standardized"])
        if not os.path.isfile(final_path):
            verification["ok"] = False
            verification["issues"].append(f"MISSING after rename: {final_path}")
            continue
        final_files += 1
        actual_hash = sha256_of_file(final_path)
        if actual_hash != record["sha256_before"]:
            verification["ok"] = False
            verification["issues"].append(
                f"SHA-256 MISMATCH after rename for {final_path}: "
                f"before={record['sha256_before']} after={actual_hash}"
            )
        actual_size = os.path.getsize(final_path)
        if actual_size != record["size_before"]:
            verification["ok"] = False
            verification["issues"].append(
                f"SIZE MISMATCH after rename for {final_path}: "
                f"before={record['size_before']} after={actual_size}"
            )

    verification["n_files_expected"] = len(manifest)
    verification["n_files_found"] = final_files
    if final_files != len(manifest):
        verification["ok"] = False
        verification["issues"].append(f"File count mismatch: expected {len(manifest)}, found {final_files}")

    return verification


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Actually perform the rename (default: dry run, report only).",
    )
    args = parser.parse_args()

    manifest, house_mapping, warnings = build_rename_manifest()
    collisions = find_collisions(manifest)

    print(f"Houses discovered: {len(house_mapping)}")
    print(f"Images in manifest: {len(manifest)}")
    print()
    print("House mapping:")
    for original, standardized in sorted(house_mapping.items(), key=lambda kv: kv[1]):
        print(f"  {original} -> {standardized}")
    print()

    if warnings:
        print(f"Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"  - {w}")
        print()

    if collisions:
        print(f"COLLISIONS ({len(collisions)}) - rename will NOT proceed:")
        for c in collisions:
            print(f"  - {c}")
        return

    os.makedirs(RESULTS_DIR, exist_ok=True)
    manifest_path = os.path.join(RESULTS_DIR, "dataset_rename_manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(
            [{k: v for k, v in r.items() if k not in ("original_path", "_path_after_pass1")} for r in manifest],
            f, indent=2,
        )
    print(f"Rename manifest written to {manifest_path}")

    if not args.execute:
        print("\nDRY RUN ONLY - pass --execute to actually rename files.")
        return

    print("\nExecuting rename...")
    verification = execute_rename(manifest)
    print(json.dumps(verification, indent=2))

    if not verification["ok"]:
        print("\nVERIFICATION FAILED - see issues above. STOP before benchmarking.")
        return

    print("\nVerification OK: all files present, all SHA-256 hashes and sizes match pre-rename values.")


if __name__ == "__main__":
    main()
