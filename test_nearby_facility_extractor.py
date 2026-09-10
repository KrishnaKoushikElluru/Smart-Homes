"""
Unit tests for services/nlp/nearby_facility_extractor.py (Stage 2,
Phase 4: nearby-FACILITY mention extraction - distinct from
services/nlp/entity_extractor.py's PROPERTY-amenity extraction).

Pure text processing, no network, no Mappls/OSM - matches the rest of
services/nlp/*'s test conventions (see test_nlp_parser.py).
"""

import unittest

from services.nlp.nearby_facility_extractor import (
    extract_nearby_facilities, NEARBY_FACILITY_CATEGORIES, _FACILITY_NOUNS,
)
from services.nlp.schema import NEARBY_FACILITY_CATEGORIES as SCHEMA_CATEGORIES


class TaxonomyConsistencyTests(unittest.TestCase):
    """This module's category vocabulary is a deliberate, documented
    duplicate of services/nearby_facility_service.FACILITY_CATEGORIES'
    keys (never imported - see this module's own docstring for why).
    These tests are the actual cross-check that the duplication hasn't
    drifted."""

    def test_local_category_set_matches_schema_declaration(self):
        self.assertEqual(NEARBY_FACILITY_CATEGORIES, SCHEMA_CATEGORIES)

    def test_every_facility_noun_maps_to_a_declared_category(self):
        for _, category in _FACILITY_NOUNS:
            self.assertIn(category, NEARBY_FACILITY_CATEGORIES)

    def test_matches_nearby_facility_service_categories(self):
        # A live cross-check against the actual Phase 4 taxonomy this
        # module is deliberately NOT importing from - if the two ever
        # drift apart, this test (not a silent inconsistency) is the
        # thing that should catch it.
        from services.nearby_facility_service import FACILITY_CATEGORIES
        self.assertEqual(NEARBY_FACILITY_CATEGORIES, set(FACILITY_CATEGORIES.keys()))


class BareFacilityWordTests(unittest.TestCase):
    """A facility noun with NO proximity wrapper must never be claimed
    here - it's a property amenity (entity_extractor.py's job), not a
    nearby-facility mention."""

    def test_bare_gym_produces_no_requirement(self):
        self.assertEqual(extract_nearby_facilities("flat with a gym"), [])

    def test_bare_hospital_produces_no_requirement(self):
        self.assertEqual(extract_nearby_facilities("hospital included"), [])

    def test_bare_park_produces_no_requirement(self):
        self.assertEqual(extract_nearby_facilities("flat with a park"), [])


class ProximityWrapperTests(unittest.TestCase):

    def test_near_a_gym(self):
        result = extract_nearby_facilities("flat near a gym")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].category, "gym")
        self.assertIsNone(result[0].radius_m)
        self.assertIn(result[0].raw_text, "flat near a gym")

    def test_gym_nearby_postfix(self):
        result = extract_nearby_facilities("flat with a gym nearby")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].category, "gym")
        self.assertIsNone(result[0].radius_m)

    def test_close_to_a_hospital(self):
        result = extract_nearby_facilities("flat close to a hospital")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].category, "hospital")

    def test_around_a_school(self):
        result = extract_nearby_facilities("house around a school")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].category, "school")

    def test_next_to_a_supermarket(self):
        result = extract_nearby_facilities("flat next to a supermarket")
        self.assertEqual(result[0].category, "supermarket")

    def test_beside_a_park(self):
        # Proximity-wrapped "park" IS a nearby facility, unlike bare "park".
        result = extract_nearby_facilities("villa beside a park")
        self.assertEqual(result[0].category, "park")


class RadiusExtractionTests(unittest.TestCase):

    def test_this_phase_own_worked_example(self):
        # "2 BHK near hospital within 1 km" -> hospital, 1 km
        result = extract_nearby_facilities("2 bhk near hospital within 1 km")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].category, "hospital")
        self.assertEqual(result[0].radius_m, 1000.0)

    def test_within_n_km_of_a_facility(self):
        result = extract_nearby_facilities("flat within 1 km of a school")
        self.assertEqual(result[0].category, "school")
        self.assertEqual(result[0].radius_m, 1000.0)

    def test_bare_facility_within_n_km_no_leading_prep(self):
        result = extract_nearby_facilities("flat gym within 500 m")
        self.assertEqual(result[0].category, "gym")
        self.assertEqual(result[0].radius_m, 500.0)

    def test_meters_unit_variants(self):
        for unit in ("m", "meters", "metres"):
            with self.subTest(unit=unit):
                result = extract_nearby_facilities(f"gym within 500 {unit}")
                self.assertEqual(result[0].radius_m, 500.0)

    def test_km_unit_variants(self):
        for unit in ("km", "kilometers", "kilometres"):
            with self.subTest(unit=unit):
                result = extract_nearby_facilities(f"gym within 2 {unit}")
                self.assertEqual(result[0].radius_m, 2000.0)

    def test_decimal_km(self):
        result = extract_nearby_facilities("hospital within 1.5 km")
        self.assertEqual(result[0].radius_m, 1500.0)


class MultipleFacilitiesTests(unittest.TestCase):

    def test_two_different_categories_both_extracted(self):
        result = extract_nearby_facilities("flat near a gym and close to a hospital")
        categories = {r.category for r in result}
        self.assertEqual(categories, {"gym", "hospital"})

    def test_at_most_one_requirement_per_category(self):
        result = extract_nearby_facilities("near a gym, also near a gym")
        gym_entries = [r for r in result if r.category == "gym"]
        self.assertEqual(len(gym_entries), 1)


class CategoryVocabularyTests(unittest.TestCase):

    def test_metro_station_phrasing(self):
        result = extract_nearby_facilities("flat near a metro station")
        self.assertEqual(result[0].category, "metro_station")

    def test_railway_station_phrasing(self):
        result = extract_nearby_facilities("flat near a railway station")
        self.assertEqual(result[0].category, "railway_station")

    def test_bus_stop_phrasing(self):
        result = extract_nearby_facilities("flat near a bus stop")
        self.assertEqual(result[0].category, "bus_stop")

    def test_shopping_mall_phrasing(self):
        result = extract_nearby_facilities("flat near a shopping mall")
        self.assertEqual(result[0].category, "shopping_mall")

    def test_petrol_pump_phrasing(self):
        result = extract_nearby_facilities("flat near a petrol pump")
        self.assertEqual(result[0].category, "petrol_station")

    def test_police_station_phrasing(self):
        result = extract_nearby_facilities("flat near a police station")
        self.assertEqual(result[0].category, "police_station")


class NoMatchTests(unittest.TestCase):

    def test_empty_text(self):
        self.assertEqual(extract_nearby_facilities(""), [])

    def test_no_facility_words_at_all(self):
        self.assertEqual(extract_nearby_facilities("2 bhk flat for rent under 25000"), [])

    def test_near_a_poi_name_is_not_a_facility_match(self):
        # "VIT Chennai" isn't in the facility vocabulary at all - this
        # extractor correctly produces nothing, leaving "near VIT
        # Chennai" entirely for location_extractor.py (unmodified) to
        # handle as a POI mention.
        self.assertEqual(extract_nearby_facilities("flat near vit chennai"), [])


if __name__ == "__main__":
    unittest.main()
