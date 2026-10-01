"""
Unit tests for evaluation/image_similarity/rename_dataset.py's pure
mapping/collision logic (house-folder mapping, category mapping, view-
number assignment, target-collision detection).

These tests use synthetic data only - no real dataset on disk is
required, and no image files are read or renamed (build_house_mapping,
map_category, _raw_token_and_suffix, find_collisions are all pure
functions). execute_rename() itself (the actual filesystem mutation)
IS covered, but only against a throwaway temporary directory this test
creates and destroys - never against the real properties/ tree.
"""

import os
import shutil
import tempfile
import unittest

from evaluation.image_similarity.rename_dataset import (
    build_house_mapping,
    map_category,
    _raw_token_and_suffix,
    build_rename_manifest,
    find_collisions,
    execute_rename,
    CATEGORY_MAPPING,
    AMBIGUOUS_CATEGORY_TOKEN,
)


class BuildHouseMappingTests(unittest.TestCase):

    def test_old_style_numbered_in_order(self):
        mapping, unrecognized = build_house_mapping(["House_3", "House_1", "House_2"])

        self.assertEqual(mapping["House_1"], "House_001")
        self.assertEqual(mapping["House_2"], "House_002")
        self.assertEqual(mapping["House_3"], "House_003")
        self.assertEqual(unrecognized, [])

    def test_new_style_continues_after_old_style_never_collides(self):
        mapping, unrecognized = build_house_mapping(["House_1", "House_2", "HOUSE1", "HOUSE2"])

        # Old-style houses keep the low numbers...
        self.assertEqual(mapping["House_1"], "House_001")
        self.assertEqual(mapping["House_2"], "House_002")
        # ...new-style houses continue afterward, never reusing a number
        # even though HOUSE1/HOUSE2 embed the same digits as House_1/House_2.
        self.assertEqual(mapping["HOUSE1"], "House_003")
        self.assertEqual(mapping["HOUSE2"], "House_004")
        self.assertEqual(len(set(mapping.values())), 4)  # all targets unique

    def test_new_style_numbered_by_its_own_embedded_number_order(self):
        mapping, unrecognized = build_house_mapping(["HOUSE10", "HOUSE2", "HOUSE1"])

        self.assertEqual(mapping["HOUSE1"], "House_001")
        self.assertEqual(mapping["HOUSE2"], "House_002")
        self.assertEqual(mapping["HOUSE10"], "House_003")

    def test_unrecognized_folder_name_is_reported_not_mapped(self):
        mapping, unrecognized = build_house_mapping(["House_1", "SomeOtherFolder"])

        self.assertNotIn("SomeOtherFolder", mapping)
        self.assertIn("SomeOtherFolder", unrecognized)

    def test_all_targets_are_unique_for_a_large_mixed_set(self):
        names = [f"House_{i}" for i in range(1, 10)] + [f"HOUSE{i}" for i in range(1, 13)]
        mapping, unrecognized = build_house_mapping(names)

        self.assertEqual(len(mapping), 21)
        self.assertEqual(len(set(mapping.values())), 21)


class RawTokenAndSuffixTests(unittest.TestCase):

    def test_no_suffix_is_suffix_zero(self):
        self.assertEqual(_raw_token_and_suffix("Bed_Room.jpeg"), ("bed_room", 0))

    def test_numeric_suffix_is_parsed(self):
        self.assertEqual(_raw_token_and_suffix("Bed_Room_1.jpeg"), ("bed_room", 1))
        self.assertEqual(_raw_token_and_suffix("Living_Room_2.jpeg"), ("living_room", 2))

    def test_capitalization_and_spacing_do_not_affect_the_token(self):
        a, _ = _raw_token_and_suffix("common_bed_room_1.jpeg")
        b, _ = _raw_token_and_suffix("Common_bed_Room_2.jpeg")
        self.assertEqual(a, b)

    def test_new_style_simple_names(self):
        self.assertEqual(_raw_token_and_suffix("bathroom.jpg"), ("bathroom", 0))
        self.assertEqual(_raw_token_and_suffix("living.jpeg"), ("living", 0))

    def test_compound_name_with_spaces(self):
        token, suffix = _raw_token_and_suffix("Parking or sit_out.jpeg")
        self.assertEqual(token, "parking_or_sit_out")
        self.assertEqual(suffix, 0)


class MapCategoryTests(unittest.TestCase):

    def test_known_tokens_map_unambiguously(self):
        self.assertEqual(map_category("bed_room"), ("bedroom", False))
        self.assertEqual(map_category("bedroom"), ("bedroom", False))
        self.assertEqual(map_category("living_room"), ("living_room", False))
        self.assertEqual(map_category("living"), ("living_room", False))
        self.assertEqual(map_category("kitchen_room"), ("kitchen", False))
        self.assertEqual(map_category("bath_room"), ("bathroom", False))
        self.assertEqual(map_category("master_bedroom"), ("master_bedroom", False))
        self.assertEqual(map_category("common_bed_room"), ("common_bedroom", False))
        self.assertEqual(map_category("devotional_room"), ("devotional_room", False))

    def test_distinct_bedroom_variants_are_not_merged(self):
        # bedroom / master_bedroom / common_bedroom must map to THREE
        # different target categories, never collapsed into one.
        targets = {
            map_category("bed_room")[0],
            map_category("master_bedroom")[0],
            map_category("common_bed_room")[0],
        }
        self.assertEqual(len(targets), 3)

    def test_unknown_or_compound_token_is_flagged_ambiguous_not_guessed(self):
        category, is_ambiguous = map_category("parking_or_sit_out")
        self.assertEqual(category, AMBIGUOUS_CATEGORY_TOKEN)
        self.assertTrue(is_ambiguous)

    def test_never_returns_ambiguous_for_a_known_token(self):
        for token in CATEGORY_MAPPING:
            _category, is_ambiguous = map_category(token)
            self.assertFalse(is_ambiguous)


class BuildRenameManifestTests(unittest.TestCase):

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, house, filename, content=b"fake image bytes"):
        d = os.path.join(self.root, house)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, filename)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_view_numbers_assigned_in_suffix_order_starting_at_01(self):
        self._write("House_1", "Living_Room.jpeg", b"a")
        self._write("House_1", "Living_Room_1.jpeg", b"b")
        self._write("House_1", "Living_Room_2.jpeg", b"c")

        manifest, house_mapping, warnings = build_rename_manifest(self.root)

        by_original = {r["image_original"]: r for r in manifest}
        self.assertEqual(by_original["Living_Room.jpeg"]["image_standardized"], "living_room_01.jpeg")
        self.assertEqual(by_original["Living_Room_1.jpeg"]["image_standardized"], "living_room_02.jpeg")
        self.assertEqual(by_original["Living_Room_2.jpeg"]["image_standardized"], "living_room_03.jpeg")

    def test_missing_base_file_still_normalizes_to_start_at_01(self):
        # Only _1 and _2 exist (no bare "Master_Bedroom.jpeg") - the
        # rule is "normalize to start at 01", not "preserve original numbers".
        self._write("House_7", "Master_bedroom_1.jpeg", b"a")
        self._write("House_7", "Master_Bedroom_2.jpeg", b"b")

        manifest, house_mapping, warnings = build_rename_manifest(self.root)

        by_original = {r["image_original"]: r for r in manifest}
        self.assertEqual(by_original["Master_bedroom_1.jpeg"]["image_standardized"], "master_bedroom_01.jpeg")
        self.assertEqual(by_original["Master_Bedroom_2.jpeg"]["image_standardized"], "master_bedroom_02.jpeg")

    def test_extension_is_preserved_not_forced_to_jpg(self):
        self._write("HOUSE1", "bathroom.jpg", b"a")
        self._write("HOUSE1", "kitchen.jpeg", b"b")

        manifest, house_mapping, warnings = build_rename_manifest(self.root)

        by_original = {r["image_original"]: r for r in manifest}
        self.assertTrue(by_original["bathroom.jpg"]["image_standardized"].endswith(".jpg"))
        self.assertTrue(by_original["kitchen.jpeg"]["image_standardized"].endswith(".jpeg"))

    def test_ambiguous_category_is_flagged_and_produces_a_warning(self):
        self._write("House_6", "Parking or sit_out.jpeg", b"a")

        manifest, house_mapping, warnings = build_rename_manifest(self.root)

        record = manifest[0]
        self.assertEqual(record["category"], AMBIGUOUS_CATEGORY_TOKEN)
        self.assertTrue(record["category_ambiguous"])
        self.assertTrue(any("ambiguous" in w.lower() for w in warnings))

    def test_sha256_and_size_recorded_before_any_rename(self):
        import hashlib
        content = b"deterministic content"
        path = self._write("House_1", "Bed_Room.jpeg", content)

        manifest, house_mapping, warnings = build_rename_manifest(self.root)

        record = manifest[0]
        self.assertEqual(record["sha256_before"], hashlib.sha256(content).hexdigest())
        self.assertEqual(record["size_before"], len(content))

    def test_no_collisions_for_a_clean_synthetic_dataset(self):
        self._write("House_1", "Bed_Room.jpeg")
        self._write("House_2", "Bed_Room.jpeg")  # same original filename, different house

        manifest, house_mapping, warnings = build_rename_manifest(self.root)

        self.assertEqual(find_collisions(manifest), [])


class ExecuteRenameTests(unittest.TestCase):
    """Exercises the actual filesystem rename against a throwaway
    temp directory only - never the real properties/ tree."""

    def setUp(self):
        self._tmpdir = tempfile.TemporaryDirectory()
        self.root = self._tmpdir.name

    def tearDown(self):
        self._tmpdir.cleanup()

    def _write(self, house, filename, content):
        d = os.path.join(self.root, house)
        os.makedirs(d, exist_ok=True)
        path = os.path.join(d, filename)
        with open(path, "wb") as f:
            f.write(content)
        return path

    def test_rename_preserves_bytes_and_verifies_clean(self):
        import hashlib
        content_a = b"living room photo bytes"
        content_b = b"bedroom photo bytes"
        self._write("House_1", "Living_Room.jpeg", content_a)
        self._write("House_1", "Bed_Room.jpeg", content_b)

        manifest, house_mapping, warnings = build_rename_manifest(self.root)
        verification = execute_rename(manifest, root=self.root)

        self.assertTrue(verification["ok"])
        self.assertEqual(verification["issues"], [])

        new_living_path = os.path.join(self.root, "House_001", "living_room_01.jpeg")
        new_bed_path = os.path.join(self.root, "House_001", "bedroom_01.jpeg")
        self.assertTrue(os.path.isfile(new_living_path))
        self.assertTrue(os.path.isfile(new_bed_path))

        with open(new_living_path, "rb") as f:
            self.assertEqual(f.read(), content_a)
        with open(new_bed_path, "rb") as f:
            self.assertEqual(f.read(), content_b)

        # Original directory/files are gone (moved, not copied).
        self.assertFalse(os.path.isdir(os.path.join(self.root, "House_1")))

    def test_refuses_to_overwrite_an_existing_destination(self):
        self._write("House_1", "Bed_Room.jpeg", b"a")
        # Pre-create a colliding destination file/dir to force the abort path.
        os.makedirs(os.path.join(self.root, "House_1"), exist_ok=True)
        conflicting_path = os.path.join(self.root, "House_1", "bedroom_01.jpeg")
        with open(conflicting_path, "wb") as f:
            f.write(b"pre-existing content, must not be overwritten")

        manifest, house_mapping, warnings = build_rename_manifest(self.root)

        with self.assertRaises(RuntimeError):
            execute_rename(manifest, root=self.root)

        # The pre-existing file's content must be untouched.
        with open(conflicting_path, "rb") as f:
            self.assertEqual(f.read(), b"pre-existing content, must not be overwritten")


if __name__ == "__main__":
    unittest.main()
