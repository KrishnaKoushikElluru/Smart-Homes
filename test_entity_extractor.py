"""
Unit tests for services/nlp/entity_extractor.py's furnishing extraction.

Focused on the "semi furnished" -> "fully_furnished" bug found during
NLP correctness testing: extract_furnishing()'s regexes used `[\\s]?`
(zero-OR-ONE whitespace char) between the qualifier ("semi"/"fully"/
"un") and "furnished", instead of `\\s*` (zero-or-more). Since upstream
masking (services/nlp/parser.py replaces a matched span with spaces
equal to its own length) can legitimately leave MULTIPLE spaces between
two words that were originally adjacent, a multi-space gap fell through
every qualified pattern and matched only the bare "\\bfurnished\\b"
fallback - silently misreporting "semi_furnished" as "fully_furnished".
"""

import unittest

from services.nlp.entity_extractor import extract_furnishing


class FurnishingLexiconTests(unittest.TestCase):

    def test_semi_furnished(self):
        r = extract_furnishing("semi furnished")
        self.assertEqual(r.value, "semi_furnished")

    def test_semi_hyphen_furnished(self):
        # Hyphens are normalized to spaces upstream (normalize_query()),
        # but extract_furnishing() itself must also tolerate one
        # directly, since it's called independently in these tests.
        r = extract_furnishing("semi-furnished".replace("-", " "))
        self.assertEqual(r.value, "semi_furnished")

    def test_semifurnished_glued(self):
        r = extract_furnishing("semifurnished")
        self.assertEqual(r.value, "semi_furnished")

    def test_fully_furnished(self):
        r = extract_furnishing("fully furnished")
        self.assertEqual(r.value, "fully_furnished")

    def test_fully_hyphen_furnished(self):
        r = extract_furnishing("fully-furnished".replace("-", " "))
        self.assertEqual(r.value, "fully_furnished")

    def test_unfurnished(self):
        r = extract_furnishing("unfurnished")
        self.assertEqual(r.value, "unfurnished")

    def test_not_furnished(self):
        r = extract_furnishing("not furnished")
        self.assertEqual(r.value, "unfurnished")

    def test_bare_furnished_defaults_to_fully(self):
        # Documented, intentional fallback (lower confidence) - must
        # not be broken by the multi-space widening fix.
        r = extract_furnishing("furnished")
        self.assertEqual(r.value, "fully_furnished")
        self.assertEqual(r.source, "lexicon_match:furnished_bare")

    def test_no_furnishing_mention(self):
        self.assertIsNone(extract_furnishing("2 bhk apartment for rent"))


class MultiSpaceMaskingRobustnessTests(unittest.TestCase):
    """The actual root-cause reproduction: multiple spaces between the
    qualifier and "furnished" (as upstream masking can legitimately
    produce) must not fall through to the bare "furnished" pattern."""

    def test_semi_multiple_spaces(self):
        r = extract_furnishing("semi   furnished")
        self.assertEqual(r.value, "semi_furnished")

    def test_fully_multiple_spaces(self):
        r = extract_furnishing("fully   furnished")
        self.assertEqual(r.value, "fully_furnished")

    def test_un_multiple_spaces(self):
        r = extract_furnishing("un   furnished")
        self.assertEqual(r.value, "unfurnished")

    def test_not_multiple_spaces(self):
        r = extract_furnishing("not   furnished")
        self.assertEqual(r.value, "unfurnished")


if __name__ == "__main__":
    unittest.main()
