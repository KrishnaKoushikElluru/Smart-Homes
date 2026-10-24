"""
Deterministic text normalization for real-estate search queries.

Scope is intentionally narrow: whitespace/casing cleanup, currency
symbol handling, and a small set of GENERIC, domain-wide token
normalizations ("2bhk" -> "2 bhk", "sqft" spelling variants) that would
be correct for literally any query, not brand/POI-specific rewrites.

This is NOT where POI names get touched. "VIT" stays "VIT" - see
location_extractor.py's module docstring for why resolving that is
explicitly out of scope for this whole layer, not just this function.
"""

from __future__ import annotations

import re
import unicodedata


def normalize_query(text: str) -> str:
    """Lowercase, Unicode-normalize, collapse whitespace, and split
    glued number+unit tokens ("2bhk" -> "2 bhk", "25k" -> "25 k",
    "1200sqft" -> "1200 sqft") so downstream regexes have a consistent
    "number SPACE word" shape to match against. Does not touch location
    or property-name text beyond casing."""

    if not text:
        return ""

    text = unicodedata.normalize("NFKC", text)
    text = text.lower()

    # ₹ / Rs. / INR prefix immediately before a number -> just drop the
    # symbol, keep the number (the numeric parser handles the rest).
    # MUST require a following digit and a word boundary before "rs"/
    # "inr" - a real bug caught during evaluation: an unanchored `rs`
    # matched the substring inside "university" ("unive-RS-ity"),
    # silently corrupting it to "univeity" before location extraction
    # ever ran.
    text = re.sub(r"(?:₹\s*|\brs\.?\s*(?=\d)|\binr\s*(?=\d))", "", text)

    # Comma-grouped numbers: "25,000" -> "25000" (only inside digit runs,
    # so it never touches e.g. "2, 3 bhk" list-style text).
    text = re.sub(r"(?<=\d),(?=\d)", "", text)

    # Split a number glued directly to letters: "2bhk" -> "2 bhk",
    # "1200sqft" -> "1200 sqft", "25k" -> "25 k".
    text = re.sub(r"(\d)([a-z])", r"\1 \2", text)
    # And the reverse glue direction: "bhk2" (rare, but seen) -> "bhk 2".
    text = re.sub(r"([a-z])(\d)", r"\1 \2", text)

    # Normalize hyphens used as separators to spaces ("2-bedroom" ->
    # "2 bedroom", "semi-furnished" stays meaningful either way since the
    # lexicon matches both forms explicitly).
    text = text.replace("-", " ")

    text = re.sub(r"\s+", " ", text).strip()

    return text
