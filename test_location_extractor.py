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


if __name__ == "__main__":
    unittest.main()
