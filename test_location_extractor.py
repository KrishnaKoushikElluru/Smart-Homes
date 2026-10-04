"""
Unit tests for services/nlp/location_extractor.py.

Focused on the comma-boundary fix (NLP correctness pass, post-Phase-4):
a POI/area phrase must stop at a comma the same way it already stops at
a STOP_WORD, so a trailing clause with no stop word of its own ("i need
a gym nearby") is never swallowed into the place name. Generic fix -
these tests deliberately use several different POI names to prove it
isn't a special case for any one of them.

extract_location() is called here WITHOUT `original_text`, so `.query`
comes back title-cased (its documented fallback casing) rather than in
the original query's exact case - these tests compare case-insensitively
since casing itself is not what's under test here (see
test_nlp_parser.py's LocationExtractionTests for casing behavior via
the full parse() path, which passes original_text through).
"""

import unittest

from services.nlp.location_extractor import extract_location


class CommaBoundaryTests(unittest.TestCase):

    def test_vit_chennai_stops_at_comma(self):
        r = extract_location("near vit chennai, i need a gym nearby")
        self.assertEqual(r.type, "poi")
        self.assertEqual(r.query.lower(), "vit chennai")

    def test_vit_chennai_stops_at_comma_before_furnishing_clause(self):
        r = extract_location("near vit chennai, flat should be semi furnished")
        self.assertEqual(r.query.lower(), "vit chennai")

    def test_apollo_hospital_stops_at_comma(self):
        r = extract_location("near apollo hospital chennai, close to a school")
        self.assertEqual(r.query.lower(), "apollo hospital chennai")

    def test_generic_not_hardcoded_to_one_place_name(self):
        # Same construction, three different POI names - proves the fix
        # is generic punctuation handling, not a VIT-specific special case.
        for poi in ("vit chennai", "apollo hospital", "phoenix marketcity"):
            with self.subTest(poi=poi):
                r = extract_location(f"near {poi}, it should be semi furnished")
                self.assertEqual(r.query.lower(), poi)

    def test_bare_in_place_also_stops_at_comma(self):
        # The "in <place>" (area_or_city) branch shares _capture_phrase
        # with the POI branch - must get the same fix.
        r = extract_location("flat in chennai, semi furnished")
        self.assertEqual(r.type, "area_or_city")
        self.assertEqual(r.query.lower(), "chennai")

    def test_multiple_commas_stops_at_the_first_one(self):
        r = extract_location("near vit chennai, i need a gym, it should be semi furnished")
        self.assertEqual(r.query.lower(), "vit chennai")


class ExistingPoiPatternsStillWorkTests(unittest.TestCase):
    """No-comma queries must be completely unaffected by the fix -
    exact regression set from the task's own "should continue working"
    examples."""

    def test_near_vit_chennai(self):
        r = extract_location("near vit chennai")
        self.assertEqual(r.query.lower(), "vit chennai")

    def test_near_apollo_hospital_chennai(self):
        r = extract_location("near apollo hospital chennai")
        self.assertEqual(r.query.lower(), "apollo hospital chennai")

    def test_close_to_iit_madras(self):
        r = extract_location("close to iit madras")
        self.assertEqual(r.query.lower(), "iit madras")

    def test_around_phoenix_marketcity_chennai(self):
        r = extract_location("around phoenix marketcity chennai")
        self.assertEqual(r.query.lower(), "phoenix marketcity chennai")

    def test_location_does_not_swallow_trailing_price_clause(self):
        # Pre-existing STOP_WORD regression (not comma-related) - must
        # still pass unchanged.
        r = extract_location("near srm kattankulathur for boys under 6000")
        self.assertEqual(r.query.lower(), "srm kattankulathur")


class DetectedCityTests(unittest.TestCase):
    """LocationMention.city - purely additive metadata for a "poi"-type
    mention, reusing this module's existing _KNOWN_CITIES set (never a
    second parser). Must never change `query`/`raw_text` - see each
    test's assertion on those alongside `city`."""

    def test_city_as_trailing_word_no_comma(self):
        r = extract_location("near vit chennai")
        self.assertEqual(r.query.lower(), "vit chennai")  # unchanged
        self.assertEqual(r.city.lower(), "chennai")

    def test_city_with_in_preposition_between(self):
        r = extract_location("near phoenix mall in bangalore")
        self.assertEqual(r.query.lower(), "phoenix mall in bangalore")
        self.assertEqual(r.city.lower(), "bangalore")

    def test_city_after_comma_clause(self):
        # The comma already stops `query` at "marina mall" (see
        # CommaBoundaryTests above, unchanged) - the city is detected
        # from the clause AFTER that comma, which `query` itself never
        # includes.
        r = extract_location("near marina mall, chennai")
        self.assertEqual(r.query.lower(), "marina mall")
        self.assertEqual(r.city.lower(), "chennai")

    def test_no_city_present_returns_none(self):
        r = extract_location("near vit")
        self.assertIsNone(r.city)

    def test_unrelated_trailing_clause_is_not_mistaken_for_a_city(self):
        r = extract_location("near marina mall, i need a gym nearby")
        self.assertEqual(r.query.lower(), "marina mall")
        self.assertIsNone(r.city)

    def test_non_city_stop_word_clause_does_not_produce_a_city(self):
        r = extract_location("near srm kattankulathur for boys under 6000")
        self.assertIsNone(r.city)

    def test_whole_phrase_being_a_city_name_is_still_detected(self):
        # Degenerate but safe input: "near Hyderabad" alone - the POI
        # phrase IS the city. Harmless (see
        # services/search_orchestration.py's "already present" guard,
        # which prevents ever appending ", Hyderabad" to "Hyderabad").
        r = extract_location("near hyderabad")
        self.assertEqual(r.query.lower(), "hyderabad")
        self.assertEqual(r.city.lower(), "hyderabad")

    def test_pure_city_only_area_or_city_mention_gets_no_separate_city_field(self):
        # A bare city name with nothing else ("flat in chennai") has no
        # separate locality to split off - `query` already IS the city
        # text, so a separate `city` field would be redundant. This is
        # DIFFERENT from a "<locality> <city>" mention like "flat in
        # Velachery Chennai", which DOES populate `city` now - see
        # AreaOrCityLocalityCitySplitTests below for that behavior.
        r = extract_location("flat in chennai")
        self.assertEqual(r.type, "area_or_city")
        self.assertEqual(r.query.lower(), "chennai")
        self.assertIsNone(r.city)

    def test_city_preserves_original_casing_like_query_does(self):
        r = extract_location("near vit chennai", original_text="2 BHK near VIT Chennai")
        self.assertEqual(r.query, "VIT Chennai")
        self.assertEqual(r.city, "Chennai")

    def test_multiple_commas_city_still_detected_from_first_clause(self):
        r = extract_location("near marina mall, chennai, with a gym nearby")
        self.assertEqual(r.query.lower(), "marina mall")
        self.assertEqual(r.city.lower(), "chennai")


class AreaOrCityLocalityCitySplitTests(unittest.TestCase):
    """Regression suite for the "Velachery Chennai never matched"
    bug: an area_or_city phrase shaped like "<locality> <city>" (no
    comma) or "<locality>, <city>" (comma) is now split into a
    separate `query` (locality) and `city`, instead of the whole
    two-word phrase being treated as one opaque string that never
    matches a document storing city/locality separately. Generic -
    reuses the SAME _KNOWN_CITIES set as everything else in this
    module; these tests deliberately span multiple different cities,
    not just Chennai, to prove that."""

    # ---- Case 1: no comma (the originally-reported failure) ----

    def test_velachery_chennai_without_comma_splits_locality_and_city(self):
        r = extract_location("2 bhk semi furnished apartment for rent in velachery chennai")
        self.assertEqual(r.type, "area_or_city")
        self.assertEqual(r.query.lower(), "velachery")
        self.assertEqual(r.city.lower(), "chennai")

    # ---- Case 2: with comma (previously silently dropped the city) ----

    def test_velachery_chennai_with_comma_also_splits_locality_and_city(self):
        r = extract_location("2 bhk semi furnished apartment for rent in velachery, chennai")
        self.assertEqual(r.type, "area_or_city")
        self.assertEqual(r.query.lower(), "velachery")
        self.assertEqual(r.city.lower(), "chennai")

    # ---- Case 3: non-Chennai locality + city examples (generality) ----

    def test_whitefield_bangalore_splits_correctly(self):
        r = extract_location("apartment in whitefield bangalore")
        self.assertEqual(r.query.lower(), "whitefield")
        self.assertEqual(r.city.lower(), "bangalore")

    def test_indiranagar_bengaluru_splits_correctly(self):
        r = extract_location("flat in indiranagar bengaluru")
        self.assertEqual(r.query.lower(), "indiranagar")
        self.assertEqual(r.city.lower(), "bengaluru")

    def test_multi_word_locality_hsr_layout_bangalore_splits_correctly(self):
        # The locality itself can be more than one word - only the
        # trailing city is split off, not assumed to be "the last
        # token" of the locality.
        r = extract_location("house in hsr layout bangalore")
        self.assertEqual(r.query.lower(), "hsr layout")
        self.assertEqual(r.city.lower(), "bangalore")

    def test_multi_word_locality_t_nagar_chennai_splits_correctly(self):
        r = extract_location("2 bhk in t nagar chennai")
        self.assertEqual(r.query.lower(), "t nagar")
        self.assertEqual(r.city.lower(), "chennai")

    # ---- Case 4: city-only query - existing behavior preserved ----

    def test_city_only_query_is_unaffected(self):
        r = extract_location("flat in chennai")
        self.assertEqual(r.type, "area_or_city")
        self.assertEqual(r.query.lower(), "chennai")
        self.assertIsNone(r.city)

    def test_locality_only_query_with_no_known_city_is_unaffected(self):
        r = extract_location("flat in anna nagar")
        self.assertEqual(r.type, "area_or_city")
        self.assertEqual(r.query.lower(), "anna nagar")
        self.assertIsNone(r.city)

    # ---- Case 5: existing POI + city query - must stay unaffected ----

    def test_poi_plus_city_query_is_unaffected_by_the_area_or_city_fix(self):
        # The POI branch (type="poi") has its OWN pre-existing
        # city-detection (_detect_trailing_city, used for the
        # city-qualified Ola retry) that must NEVER have `query`
        # stripped - that's a hard requirement for Phase 1 POI
        # resolution. This fix only touches the area_or_city branch.
        r = extract_location("near phoenix mall in bangalore")
        self.assertEqual(r.type, "poi")
        self.assertEqual(r.query.lower(), "phoenix mall in bangalore")
        self.assertEqual(r.city.lower(), "bangalore")

    def test_existing_poi_near_vit_chennai_is_unaffected(self):
        r = extract_location("near vit chennai")
        self.assertEqual(r.type, "poi")
        self.assertEqual(r.query.lower(), "vit chennai")
        self.assertEqual(r.city.lower(), "chennai")


if __name__ == "__main__":
    unittest.main()
