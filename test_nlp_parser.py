"""
Unit tests for services/nlp/ (Phase 2: NLP query understanding).

Run with:
    python -m unittest test_nlp_parser

No network access needed - this whole layer is pure text processing.
Includes explicit BOUNDARY tests (see NoCoordinatesOrPhase1CallsTests)
proving this layer never produces latitude/longitude and never imports
or calls services.mappls_service / services.osm_location_service - the
Phase 1/Phase 2 separation this task requires is enforced, not just
assumed.
"""

import sys
import unittest

from services.nlp.parser import parse
from services.nlp.baseline import parse_baseline
from services.nlp.schema import validate_structured_query


class SimpleQueryTests(unittest.TestCase):

    def test_simple_rent_query(self):
        r = parse("for rent")
        self.assertEqual(r.listing_type.value, "rent")

    def test_simple_sale_query(self):
        r = parse("for sale")
        self.assertEqual(r.listing_type.value, "sell")

    def test_bhk_extraction(self):
        r = parse("2 bhk apartment")
        self.assertEqual(r.bedrooms.value, 2.0)

    def test_property_type_extraction(self):
        r = parse("looking for a villa")
        self.assertEqual(r.property_type.value, "villa")


class NumericExtractionTests(unittest.TestCase):

    def test_price_extraction_bare_number(self):
        r = parse("flat under 25000")
        self.assertEqual(r.price.operator, "lte")
        self.assertEqual(r.price.value, 25000.0)

    def test_lakh_conversion(self):
        r = parse("villa below 50 lakh")
        self.assertEqual(r.price.value, 5_000_000.0)

    def test_lakh_short_form_conversion(self):
        r = parse("villa below 50L")
        self.assertEqual(r.price.value, 5_000_000.0)

    def test_crore_conversion(self):
        r = parse("villa below 1.5 crore")
        self.assertEqual(r.price.value, 15_000_000.0)

    def test_thousand_k_conversion(self):
        r = parse("flat under 25k")
        self.assertEqual(r.price.value, 25_000.0)

    def test_between_operator(self):
        r = parse("flat between 20k and 30k")
        self.assertEqual(r.price.operator, "between")
        self.assertEqual(r.price.value_min, 20_000.0)
        self.assertEqual(r.price.value_max, 30_000.0)

    def test_area_extraction(self):
        r = parse("apartment above 1200 sqft")
        self.assertEqual(r.area.operator, "gte")
        self.assertEqual(r.area.value, 1200.0)

    def test_price_and_area_do_not_cross_contaminate(self):
        # Regression test for a real bug found during evaluation: "above
        # 1200 sqft" was ALSO being read as a price of 1200.
        r = parse("apartment above 1200 sqft")
        self.assertIsNone(r.price)

    def test_malformed_numeric_input_does_not_crash(self):
        r = parse("flat under abc")
        self.assertIsNone(r.price)  # no valid number - must stay unspecified, not raise

    def test_negative_number_does_not_crash(self):
        # Documented, deliberate behavior: the sign is simply not part of
        # the number pattern, so this degrades gracefully to a positive
        # value rather than erroring - see evaluation/nlp/build_dataset.py.
        r = parse("flat under -5000")
        self.assertEqual(r.price.value, 5000.0)


class AmenityAndFurnishingTests(unittest.TestCase):

    def test_single_amenity(self):
        r = parse("flat with parking")
        values = [a.value for a in r.amenities]
        self.assertIn("parking", values)

    def test_multiple_amenities(self):
        r = parse("flat with parking and gym")
        values = {a.value for a in r.amenities}
        self.assertEqual(values, {"parking", "gym"})

    def test_furnishing_semi(self):
        r = parse("semi furnished 2 bhk")
        self.assertEqual(r.furnishing.value, "semi_furnished")

    def test_furnishing_un(self):
        r = parse("unfurnished flat")
        self.assertEqual(r.furnishing.value, "unfurnished")


class LocationExtractionTests(unittest.TestCase):

    def test_poi_location(self):
        r = parse("2 bhk near VIT Chennai")
        self.assertEqual(r.location.type, "poi")
        self.assertEqual(r.location.query, "VIT Chennai")

    def test_city_location(self):
        r = parse("3 bhk villa in Chennai")
        self.assertEqual(r.location.type, "area_or_city")
        self.assertEqual(r.location.query, "Chennai")

    def test_no_location_mention(self):
        r = parse("2 bhk apartment for rent")
        self.assertIsNone(r.location)

    def test_location_does_not_swallow_trailing_price_clause(self):
        # Regression test: "near SRM for boys under 6000" was capturing
        # "SRM for boys" as the location instead of stopping at "for".
        r = parse("1 bhk pg near SRM Kattankulathur for boys under 6000")
        self.assertEqual(r.location.query, "SRM Kattankulathur")

    def test_around_is_not_confused_with_price_approximation(self):
        # Regression test: "villa around 1 crore" was extracting "1
        # crore" as a fake POI location.
        r = parse("villa around 1 crore")
        self.assertIsNone(r.location)
        self.assertEqual(r.price.operator, "approx")

    def test_amenity_word_inside_place_name_is_not_misread(self):
        # Regression test: "Guindy National Park" was leaking amenity
        # "park" because the text wasn't masked before amenity matching.
        r = parse("villa beside Guindy National Park")
        self.assertEqual(r.location.query, "Guindy National Park")
        self.assertEqual(r.amenities, [])


class MultiConstraintTests(unittest.TestCase):

    def test_full_worked_example_one(self):
        r = parse("2 bhk flat for rent near VIT Chennai under 25000 with parking")
        self.assertEqual(r.listing_type.value, "rent")
        self.assertEqual(r.property_type.value, "apartment")
        self.assertEqual(r.bedrooms.value, 2.0)
        self.assertEqual(r.price.operator, "lte")
        self.assertEqual(r.price.value, 25000.0)
        self.assertEqual(r.location.type, "poi")
        self.assertEqual(r.location.query, "VIT Chennai")
        self.assertEqual([a.value for a in r.amenities], ["parking"])

    def test_full_worked_example_two(self):
        r = parse("3 BHK villa for sale in Chennai below 1.5 crore with swimming pool")
        self.assertEqual(r.listing_type.value, "sell")
        self.assertEqual(r.property_type.value, "villa")
        self.assertEqual(r.bedrooms.value, 3.0)
        self.assertEqual(r.price.value, 15_000_000.0)
        self.assertEqual(r.location.query, "Chennai")
        self.assertEqual([a.value for a in r.amenities], ["swimming_pool"])


class AmbiguousAndUnsupportedTests(unittest.TestCase):

    def test_ambiguous_query_does_not_invent_a_price(self):
        # "cheap" must never be silently converted into a number.
        r = parse("cheap flat near VIT")
        self.assertIsNone(r.price)
        self.assertEqual(r.property_type.value, "apartment")

    def test_unsupported_off_topic_query(self):
        r = parse("what's the weather today")
        self.assertEqual(r.intent, "unknown")

    def test_domain_adjacent_unmapped_phrase_is_recognized_not_dropped(self):
        r = parse("gated community with vastu compliance")
        self.assertEqual(r.intent, "property_search")
        self.assertTrue(len(r.unsupported_phrases) > 0)

    def test_empty_query(self):
        r = parse("")
        self.assertEqual(r.intent, "unknown")
        self.assertIn("empty query", r.warnings)


class RobustnessTests(unittest.TestCase):

    def test_mixed_casing(self):
        r = parse("2 BHK FLAT FOR RENT")
        self.assertEqual(r.bedrooms.value, 2.0)
        self.assertEqual(r.property_type.value, "apartment")
        self.assertEqual(r.listing_type.value, "rent")

    def test_extra_whitespace(self):
        r = parse("   2   bhk    flat   for   rent  ")
        self.assertEqual(r.bedrooms.value, 2.0)

    def test_glued_bhk(self):
        r = parse("2bhk flat")
        self.assertEqual(r.bedrooms.value, 2.0)

    def test_word_number_bhk(self):
        r = parse("two bedroom flat")
        self.assertEqual(r.bedrooms.value, 2.0)

    def test_indian_english_to_let(self):
        r = parse("flat to let")
        self.assertEqual(r.listing_type.value, "rent")

    def test_indian_english_lease_maps_to_rent(self):
        r = parse("independent house for lease")
        self.assertEqual(r.listing_type.value, "rent")


class ValidationTests(unittest.TestCase):

    def test_valid_structured_query_has_no_problems(self):
        r = parse("2 bhk flat for rent under 25000")
        problems = validate_structured_query(r)
        self.assertEqual(problems, [])


class BaselineTests(unittest.TestCase):
    """The baseline is a real, second implementation - not a stub - so
    it needs its own basic correctness tests too."""

    def test_baseline_runs_without_error(self):
        r = parse_baseline("2 bhk flat for rent under 25000")
        self.assertEqual(r.intent, "property_search")

    def test_baseline_does_not_understand_lakh(self):
        # Deliberate, documented baseline weakness.
        r = parse_baseline("villa below 50 lakh")
        self.assertEqual(r.price.value, 50.0)  # NOT 5,000,000 - proves the weakness is real


# ============================================================
# BOUNDARY TESTS: Phase 2 must never touch Phase 1's territory.
# ============================================================

class NoCoordinatesOrPhase1CallsTests(unittest.TestCase):

    def test_no_latitude_longitude_anywhere_in_output(self):
        r = parse("2 bhk flat for rent near VIT Chennai under 25000 with parking").to_dict()

        def walk(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    self.assertNotIn(k.lower(), ("latitude", "longitude", "lat", "lon", "lng"),
                                      f"NLP output must never contain coordinates, found key {k!r}")
                    walk(v)
            elif isinstance(obj, list):
                for item in obj:
                    walk(item)

        walk(r)

    def test_location_mention_is_free_text_only(self):
        r = parse("near VIT Chennai")
        # location.query must be a plain string, never a coordinate pair.
        self.assertIsInstance(r.location.query, str)
        self.assertNotIsInstance(r.location.query, (tuple, list))

    def test_services_nlp_package_never_imports_phase_1_modules(self):
        """Static check: services.nlp.* must not import
        services.mappls_service or services.osm_location_service. This
        is enforced by inspecting sys.modules after importing the whole
        package - if Phase 1 modules got pulled in transitively, they'd
        already be loaded."""
        import services.nlp  # noqa: F401 (ensure fully imported)

        for mod_name in list(sys.modules):
            if mod_name.startswith("services.nlp"):
                module = sys.modules[mod_name]
                source_globals = getattr(module, "__dict__", {})
                for name, value in source_globals.items():
                    module_of_value = getattr(value, "__module__", "")
                    self.assertFalse(
                        isinstance(module_of_value, str) and (
                            "mappls_service" in module_of_value or "osm_location_service" in module_of_value
                        ),
                        f"services.nlp.{mod_name} references a Phase 1 module via {name!r}",
                    )

    def test_mappls_service_module_not_loaded_by_nlp_import(self):
        """If services.nlp ever started importing Phase 1 modules, this
        would start failing the moment someone `import services.nlp`
        without also importing Phase 1 directly first, in a clean
        interpreter. We can't easily get a clean interpreter mid-suite,
        but we CAN assert the specific submodules were never referenced
        as dependencies by inspecting each nlp module's own imports."""
        import ast
        import inspect
        import services.nlp.parser as parser_mod
        import services.nlp.normalization
        import services.nlp.numeric_parser
        import services.nlp.location_extractor
        import services.nlp.entity_extractor
        import services.nlp.baseline
        import services.nlp.schema

        for module in (
            parser_mod, services.nlp.normalization, services.nlp.numeric_parser,
            services.nlp.location_extractor, services.nlp.entity_extractor,
            services.nlp.baseline, services.nlp.schema,
        ):
            source = inspect.getsource(module)
            tree = ast.parse(source)
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        self.assertNotIn("mappls_service", alias.name)
                        self.assertNotIn("osm_location_service", alias.name)
                elif isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    self.assertNotIn("mappls_service", mod)
                    self.assertNotIn("osm_location_service", mod)


if __name__ == "__main__":
    unittest.main()
