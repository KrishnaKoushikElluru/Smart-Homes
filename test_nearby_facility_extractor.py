"""
Unit tests for services/nlp/nearby_facility_extractor.py (Stage 2,
Phase 4: nearby-FACILITY mention extraction - distinct from
services/nlp/entity_extractor.py's PROPERTY-amenity extraction).

Pure text processing, no network, no Mappls/OSM - matches the rest of
services/nlp/*'s test conventions (see test_nlp_parser.py).
"""

import unittest

from services.nlp.nearby_facility_extractor import (
    extract_nearby_facilities, extract_unsupported_nearby_mentions,
    NEARBY_FACILITY_CATEGORIES, _FACILITY_NOUNS,
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


class ShouldBeNearbyTests(unittest.TestCase):
    """"<facility> should be nearby" - a copula between the facility and
    "nearby" - is recognized the same as the bare "<facility> nearby"
    postfix form."""

    def test_gym_should_be_nearby(self):
        result = extract_nearby_facilities("gym should be nearby")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].category, "gym")
        self.assertIsNone(result[0].radius_m)

    def test_hospital_should_be_nearby(self):
        result = extract_nearby_facilities("hospital should be nearby")
        self.assertEqual(result[0].category, "hospital")

    def test_bus_stop_nearby_bare(self):
        result = extract_nearby_facilities("bus stop nearby")
        self.assertEqual(result[0].category, "bus_stop")


class WalkableDistanceTests(unittest.TestCase):
    """"walkable"/"walking distance" is QUALITATIVE - the facility
    requirement must be kept, but radius_m must stay None (never a
    fabricated number) - see this module's docstring."""

    def test_bus_stop_should_be_in_walkable_distance(self):
        result = extract_nearby_facilities("bus stop should be in walkable distance")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0].category, "bus_stop")
        self.assertIsNone(result[0].radius_m)
        self.assertIn("walkable distance", result[0].raw_text)

    def test_gym_walking_distance_synonym(self):
        result = extract_nearby_facilities("gym in walking distance")
        self.assertEqual(result[0].category, "gym")
        self.assertIsNone(result[0].radius_m)

    def test_walkable_distance_never_produces_a_radius(self):
        result = extract_nearby_facilities("hospital should be in walkable distance")
        for r in result:
            self.assertIsNone(r.radius_m)


class CoordinatedGroupTests(unittest.TestCase):
    """A coordinated list of facilities sharing one trailing "nearby" /
    "should be nearby" - generic list-of-known-nouns handling, not a
    hardcoded pairing of any two specific words (see this module's
    docstring)."""

    def test_gym_and_pool_should_be_nearby_extracts_gym(self):
        # "pool" is intentionally NOT a supported category (see
        # UnsupportedPoolTests below) - only "gym" should come back here.
        result = extract_nearby_facilities("gym and pool should be nearby")
        categories = {r.category for r in result}
        self.assertEqual(categories, {"gym"})

    def test_three_way_coordination(self):
        result = extract_nearby_facilities("gym, hospital and bank should be nearby")
        categories = {r.category for r in result}
        self.assertEqual(categories, {"gym", "hospital", "bank"})

    def test_coordination_does_not_duplicate_a_category_already_found_directly(self):
        # "near a gym" is already caught by the single-noun preposition
        # pattern; the coordinated-group pass must not add a second gym
        # entry for the same category.
        result = extract_nearby_facilities("near a gym and pool should be nearby")
        gym_entries = [r for r in result if r.category == "gym"]
        self.assertEqual(len(gym_entries), 1)

    def test_pool_first_in_list_still_lets_hospital_be_found(self):
        # Regression test for a real masking-order bug found while
        # building this fix: when the UNSUPPORTED noun appears FIRST in
        # the coordinated list ("pool and hospital..."), hospital's own
        # single-noun match ("hospital should be nearby") got masked
        # first, and the leftover "pool and" then leaked through to
        # entity_extractor's property-amenity lexicon because the
        # unsupported-mention masking (computed against the ORIGINAL
        # text) could no longer find its now-partially-masked span. The
        # fix masks all nearby-facility spans longest-first (see
        # services/nlp/parser.py) - this test simply checks the
        # extractor's own output stays correct regardless of masking.
        result = extract_nearby_facilities("pool and hospital should be nearby")
        categories = {r.category for r in result}
        self.assertEqual(categories, {"hospital"})


class UnsupportedPoolTests(unittest.TestCase):
    """swimming_pool is NOT in NEARBY_FACILITY_CATEGORIES (the real
    Phase 4 Mappls taxonomy has no verified "swimming pool" category) -
    a proximity-wrapped pool mention must be reported as an explicitly
    UNSUPPORTED nearby-facility mention, never as a
    NearbyFacilityRequirement and never silently left for
    entity_extractor.py to reinterpret as a property amenity."""

    def test_pool_nearby_is_not_a_nearby_facility_requirement(self):
        self.assertEqual(extract_nearby_facilities("pool nearby"), [])

    def test_pool_nearby_is_reported_as_unsupported(self):
        result = extract_unsupported_nearby_mentions("pool nearby")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["category"], "swimming_pool")

    def test_swimming_pool_should_be_nearby_is_unsupported(self):
        result = extract_unsupported_nearby_mentions("swimming pool should be nearby")
        categories = {r["category"] for r in result}
        self.assertEqual(categories, {"swimming_pool"})

    def test_bare_pool_with_no_proximity_wrapper_is_not_flagged(self):
        # "flat with a pool" is a property AMENITY, not a nearby-facility
        # mention at all - this module must stay silent so
        # entity_extractor.py's existing amenity lexicon handles it,
        # exactly like the gym/park amenity-vs-nearby distinction.
        self.assertEqual(extract_unsupported_nearby_mentions("flat with a pool"), [])
        self.assertEqual(extract_nearby_facilities("flat with a pool"), [])

    def test_swimming_pool_not_in_supported_taxonomy(self):
        self.assertNotIn("swimming_pool", NEARBY_FACILITY_CATEGORIES)


if __name__ == "__main__":
    unittest.main()
