"""
Unit tests for evaluation/image_similarity/dataset.py's pilot-dataset
scanning logic (Phase 6 Step 1 pilot: properties/House_<N>/*.jpeg).

These tests use a TEMPORARY directory with small synthetic images
(created with Pillow, a dependency this project already has via
services/media_service.py) rather than depending on the real
properties/ folder's exact contents - so this file keeps passing even
if the real pilot dataset changes size later, and never touches or
depends on network access or torch/transformers.
"""

import hashlib
import os
import shutil
import tempfile
import unittest

from PIL import Image

from evaluation.image_similarity.dataset import (
    normalize_category_from_filename,
    scan_pilot_dataset,
    sha256_of_file,
    Manifest,
)


def _write_tiny_jpeg(path, color=(200, 100, 50)):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    Image.new("RGB", (8, 8), color=color).save(path, format="JPEG")


class NormalizeCategoryFromFilenameTests(unittest.TestCase):

    def test_simple_name_is_lowercased(self):
        self.assertEqual(normalize_category_from_filename("Living_Room.jpeg"), "living_room")

    def test_trailing_number_suffix_is_stripped(self):
        self.assertEqual(normalize_category_from_filename("Bed_Room_1.jpeg"), "bed_room")
        self.assertEqual(normalize_category_from_filename("Master_Bedroom_2.jpeg"), "master_bedroom")

    def test_different_capitalizations_of_the_same_room_merge(self):
        a = normalize_category_from_filename("common_bed_room_1.jpeg")
        b = normalize_category_from_filename("Common_bed_Room_2.jpeg")
        self.assertEqual(a, b)
        self.assertEqual(a, "common_bed_room")

    def test_spaces_become_underscores(self):
        self.assertEqual(normalize_category_from_filename("Parking or sit_out.jpeg"), "parking_or_sit_out")

    def test_distinct_room_names_are_not_merged(self):
        # "bed_room" and "master_bedroom" and "common_bed_room" must
        # stay THREE separate categories - merging them would be
        # inventing a mapping the filenames don't actually support.
        self.assertNotEqual(
            normalize_category_from_filename("Bed_Room.jpeg"),
            normalize_category_from_filename("Master_bedroom_1.jpeg"),
        )
        self.assertNotEqual(
            normalize_category_from_filename("Bed_Room.jpeg"),
            normalize_category_from_filename("common_bed_room_1.jpeg"),
        )


class Sha256OfFileTests(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_matches_hashlib_directly(self):
        path = os.path.join(self._tmpdir.name, "x.bin")
        with open(path, "wb") as f:
            f.write(b"some deterministic content")

        expected = hashlib.sha256(b"some deterministic content").hexdigest()

        self.assertEqual(sha256_of_file(path), expected)

    def test_identical_content_produces_identical_hash(self):
        path_a = os.path.join(self._tmpdir.name, "a.bin")
        path_b = os.path.join(self._tmpdir.name, "b.bin")
        with open(path_a, "wb") as f:
            f.write(b"identical bytes")
        with open(path_b, "wb") as f:
            f.write(b"identical bytes")

        self.assertEqual(sha256_of_file(path_a), sha256_of_file(path_b))

    def test_different_content_produces_different_hash(self):
        path_a = os.path.join(self._tmpdir.name, "a.bin")
        path_b = os.path.join(self._tmpdir.name, "b.bin")
        with open(path_a, "wb") as f:
            f.write(b"content one")
        with open(path_b, "wb") as f:
            f.write(b"content two")

        self.assertNotEqual(sha256_of_file(path_a), sha256_of_file(path_b))


class ScanPilotDatasetTests(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def test_groups_images_by_house_directory(self):
        _write_tiny_jpeg(os.path.join(self.root, "House_1", "Bed_Room.jpeg"))
        _write_tiny_jpeg(os.path.join(self.root, "House_1", "Living_Room.jpeg"))
        _write_tiny_jpeg(os.path.join(self.root, "House_2", "Kitchen_Room.jpeg"))

        manifest, summary, issues = scan_pilot_dataset(self.root)

        self.assertEqual(summary["n_images"], 3)
        self.assertEqual(summary["n_houses_with_images"], 2)
        self.assertEqual(summary["images_per_house"], {"House_1": 2, "House_2": 1})

        house_ids = {record["house_id"] for record in manifest}
        self.assertEqual(house_ids, {"House_1", "House_2"})

    def test_empty_house_directory_is_reported_not_an_error(self):
        _write_tiny_jpeg(os.path.join(self.root, "House_1", "Bed_Room.jpeg"))
        os.makedirs(os.path.join(self.root, "House_2"))  # empty, no images

        manifest, summary, issues = scan_pilot_dataset(self.root)

        self.assertEqual(summary["n_houses_total"], 2)
        self.assertEqual(summary["n_houses_with_images"], 1)
        self.assertEqual(summary["n_houses_empty"], 1)
        self.assertTrue(any("House_2" in issue.message and "empty" in issue.message for issue in issues))

    def test_no_cross_house_reassignment(self):
        _write_tiny_jpeg(os.path.join(self.root, "House_1", "Bed_Room.jpeg"))
        _write_tiny_jpeg(os.path.join(self.root, "House_2", "Bed_Room.jpeg"))  # same filename, different house

        manifest, summary, issues = scan_pilot_dataset(self.root)

        records_by_id = {record["id"]: record for record in manifest}
        self.assertEqual(records_by_id["House_1/Bed_Room.jpeg"]["house_id"], "House_1")
        self.assertEqual(records_by_id["House_2/Bed_Room.jpeg"]["house_id"], "House_2")

    def test_unreadable_image_is_reported_and_excluded_from_manifest_not_deleted(self):
        good_path = os.path.join(self.root, "House_1", "Bed_Room.jpeg")
        bad_path = os.path.join(self.root, "House_1", "Corrupt_Room.jpeg")
        _write_tiny_jpeg(good_path)
        os.makedirs(os.path.dirname(bad_path), exist_ok=True)
        with open(bad_path, "wb") as f:
            f.write(b"this is not a real jpeg file at all")

        manifest, summary, issues = scan_pilot_dataset(self.root)

        self.assertEqual(summary["n_unreadable"], 1)
        self.assertEqual(summary["n_images"], 1)  # only the good one is in the manifest
        # The file itself must still exist on disk - never deleted.
        self.assertTrue(os.path.isfile(bad_path))
        self.assertTrue(any("Corrupt_Room" in issue.message for issue in issues))

    def test_byte_identical_duplicate_content_is_flagged_but_both_kept(self):
        path_a = os.path.join(self.root, "House_1", "Bed_Room.jpeg")
        path_b = os.path.join(self.root, "House_1", "Living_Room.jpeg")
        _write_tiny_jpeg(path_a, color=(10, 20, 30))
        shutil.copyfile(path_a, path_b)  # byte-identical, different filename

        manifest, summary, issues = scan_pilot_dataset(self.root)

        # Both images are preserved - this benchmark must never
        # silently drop an existing image, even a detected duplicate.
        self.assertEqual(summary["n_images"], 2)
        self.assertTrue(any("byte-identical" in issue.message for issue in issues))
        self.assertEqual(len(summary["duplicate_groups"]), 1)
        self.assertEqual(
            sorted(summary["duplicate_groups"][0]["image_ids"]),
            ["House_1/Bed_Room.jpeg", "House_1/Living_Room.jpeg"],
        )
        # The duplicate group's hash is a real SHA-256 of the file content.
        self.assertEqual(summary["duplicate_groups"][0]["sha256"], sha256_of_file(path_a))

    def test_records_include_sha256_format_and_dimensions(self):
        path = os.path.join(self.root, "House_1", "Bed_Room.jpeg")
        _write_tiny_jpeg(path)

        manifest, summary, issues = scan_pilot_dataset(self.root)

        record = list(manifest)[0]
        self.assertEqual(record["sha256"], sha256_of_file(path))
        self.assertEqual(record["format"], "JPEG")
        self.assertEqual((record["width"], record["height"]), (8, 8))
        self.assertEqual(summary["formats"], {"JPEG": 1})

    def test_duplicate_path_is_not_counted_twice(self):
        _write_tiny_jpeg(os.path.join(self.root, "House_1", "Bed_Room.jpeg"))

        manifest, summary, issues = scan_pilot_dataset(self.root)
        manifest2, summary2, issues2 = scan_pilot_dataset(self.root)

        # Scanning the same directory twice must not accumulate state
        # or double-count anything within a single scan.
        self.assertEqual(summary["n_images"], 1)
        self.assertEqual(summary2["n_images"], 1)

    def test_category_extracted_from_filename_and_counted(self):
        _write_tiny_jpeg(os.path.join(self.root, "House_1", "Bed_Room.jpeg"))
        _write_tiny_jpeg(os.path.join(self.root, "House_1", "Bed_Room_1.jpeg"))
        _write_tiny_jpeg(os.path.join(self.root, "House_2", "Kitchen_Room.jpeg"))

        manifest, summary, issues = scan_pilot_dataset(self.root)

        self.assertEqual(summary["categories"], {"bed_room": 2, "kitchen_room": 1})

    def test_nonexistent_root_reports_a_warning_not_a_crash(self):
        manifest, summary, issues = scan_pilot_dataset(os.path.join(self.root, "does_not_exist"))

        self.assertEqual(len(manifest), 0)
        self.assertEqual(summary["n_images"], 0)
        self.assertTrue(any(issue.severity == "warning" for issue in issues))

    def test_manifest_records_have_required_keys_for_metrics(self):
        _write_tiny_jpeg(os.path.join(self.root, "House_1", "Bed_Room.jpeg"))

        manifest, summary, issues = scan_pilot_dataset(self.root)

        record = list(manifest)[0]
        for key in ("id", "path", "house_id", "category"):
            self.assertIn(key, record)

    def test_manifest_from_records_no_longer_requires_a_label_field(self):
        # Pilot manifests use house_id/category, not the older "label"
        # field the pipeline-smoke manifest used - Manifest must accept
        # both shapes.
        records = [{"id": "x", "path": "/tmp/x.jpg", "house_id": "House_1"}]
        manifest = Manifest.from_records(records)
        self.assertEqual(len(manifest), 1)


if __name__ == "__main__":
    unittest.main()
