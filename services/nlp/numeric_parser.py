"""
Numeric constraint extraction: price and area.

Handles Indian numbering-system multipliers (k/thousand, L/lakh, Cr/crore)
and a small, explicit operator vocabulary (lte/gte/eq/approx/between).
Runs on TEXT ALREADY PASSED THROUGH normalization.normalize_query, so
"2bhk"/"25k" have already been split into "2 bhk" / "25 k" by the time
these regexes see them.

No operator keyword found near a bare number is NOT silently treated as
"under" (a real assumption bug we deliberately avoid) - it's returned as
operator="eq" with a lower confidence and a warning, so the caller can
see this was ambiguous rather than quietly guessing the user's intent.
"""

from __future__ import annotations

import re
from typing import Optional

from services.nlp.schema import RangeConstraint

MULTIPLIERS = {
    "k": 1_000, "thousand": 1_000,
    "l": 100_000, "lac": 100_000, "lacs": 100_000, "lakh": 100_000, "lakhs": 100_000,
    "cr": 10_000_000, "crore": 10_000_000, "crores": 10_000_000,
}

_NUMBER = r"(\d+(?:\.\d+)?)"
_UNIT_WORD = r"k|thousand|l|lac|lacs|lakh|lakhs|cr|crore|crores"
# The optional unit AND the whitespace before it are grouped together
# non-capturing, so when no unit word follows, nothing is consumed and
# no trailing whitespace leaks into the match (a real bug caught while
# smoke-testing: "under 25000 " was matching with a trailing space).
_NUM_WITH_UNIT = rf"{_NUMBER}(?:\s*({_UNIT_WORD})\b)?"

# Negative lookahead used ONLY by price matching (see _NUM_WITH_UNIT_PRICE
# below): a number immediately followed by an area unit or a distance
# unit is an area/radius, never a price, even when it happens to sit
# right after a word price matching also treats as an operator keyword.
# Two real collisions caught during evaluation: "above 1200 sqft" was
# ALSO matching as a price of 1200 (since "above" is a valid price
# operator word too), and "within 5 km of IIT Madras" was matching as
# a price of 5 (since "within" is a valid price LTE word, but here it's
# introducing a distance radius, not a budget).
_NOT_AREA_OR_DISTANCE = r"(?!\s*(?:sq\s?ft|sqft|square\s?feet|square\s?foot|km|kilometers?)\b)"
# \b immediately after the digit run is essential, not decorative: without
# it, Python's re backtracks into a SHORTER digit match ("120" instead of
# "1200") to satisfy the negative lookahead below, since "0 sqft" doesn't
# start with an area unit either - a real bug caught during evaluation
# where "above 1200 sqft" produced a phantom price of 120.0. The digit
# run must fully resolve (word boundary) before the lookahead is allowed
# to even be evaluated.
_NUM_WITH_UNIT_PRICE = rf"{_NUMBER}\b(?:\s*({_UNIT_WORD})\b)?{_NOT_AREA_OR_DISTANCE}"

_LTE_WORDS = r"(?:under|below|less than|up ?to|within|no more than|max(?:imum)?|budget of)"
_GTE_WORDS = r"(?:above|over|more than|starting from|min(?:imum)?|from|atleast|at least)"
_APPROX_WORDS = r"(?:around|approx(?:imately)?|about|close to|near(?:ly)?)"
_BETWEEN_WORDS = r"(?:between)"
_RANGE_JOIN = r"(?:to|and|-)"


def _parse_number_with_unit(number_str: str, unit_str: Optional[str]) -> float:
    value = float(number_str)
    if unit_str:
        value *= MULTIPLIERS[unit_str]
    return value


def _find_between(text: str) -> Optional[tuple]:
    """"between 20k and 30k" / "20k to 30k" / "20k - 30k" (price only -
    see _NUM_WITH_UNIT_PRICE)"""
    pattern = rf"(?:{_BETWEEN_WORDS}\s+)?{_NUM_WITH_UNIT_PRICE}\s*{_RANGE_JOIN}\s*{_NUM_WITH_UNIT_PRICE}"
    m = re.search(pattern, text)
    if not m:
        return None
    n1, u1, n2, u2 = m.group(1), m.group(2), m.group(3), m.group(4)
    # If only one side carries a unit ("20 to 30k"), apply it to both -
    # this is standard spoken/written shorthand.
    if u2 and not u1:
        u1 = u2
    if u1 and not u2:
        u2 = u1
    v1 = _parse_number_with_unit(n1, u1)
    v2 = _parse_number_with_unit(n2, u2)
    lo, hi = min(v1, v2), max(v1, v2)
    return lo, hi, m.group(0)


def _find_operator_bound(text: str, words: str, operator: str) -> Optional[tuple]:
    pattern = rf"{words}\s+{_NUM_WITH_UNIT_PRICE}"
    m = re.search(pattern, text)
    if not m:
        return None
    value = _parse_number_with_unit(m.group(1), m.group(2))
    return value, operator, m.group(0)


def _find_bare_number_near(text: str, context_words: list) -> Optional[tuple]:
    """Fallback: a number that appears near a context word (e.g. "budget
    25000", "price 45k") but with no explicit operator keyword. Returned
    with operator="eq" and the caller marks it lower-confidence."""
    for word in context_words:
        pattern = rf"{word}\s*(?:of|is|:)?\s*{_NUM_WITH_UNIT_PRICE}"
        m = re.search(pattern, text)
        if m:
            value = _parse_number_with_unit(m.group(1), m.group(2))
            return value, "eq", m.group(0)
    return None


def extract_price(text: str) -> Optional[RangeConstraint]:
    """Looks for a price constraint anywhere in `text`. Distinguishes
    price from area by requiring the number NOT be immediately followed
    by an area unit (sqft/sq ft/square feet) - callers should run
    extract_area first if both might be present, or rely on this
    function's own area-unit exclusion (see _PRICE_NUMBER regex note)."""

    between = _find_between(text)
    if between:
        lo, hi, raw = between
        return RangeConstraint(operator="between", value_min=lo, value_max=hi, unit="inr", raw_text=raw)

    for words, op in ((_LTE_WORDS, "lte"), (_GTE_WORDS, "gte"), (_APPROX_WORDS, "approx")):
        found = _find_operator_bound(text, words, op)
        if found:
            value, operator, raw = found
            return RangeConstraint(operator=operator, value=value, unit="inr", raw_text=raw)

    # Fallback: explicit price/budget/rent/cost word + bare number, no
    # operator - genuinely ambiguous, flagged via a lower confidence by
    # the caller (parser.py), not silently assumed to mean "under".
    # NOTE: deliberately excludes generic words like "for" - "for 1200
    # sqft" would otherwise be misread as a price of 1200 before the
    # area extractor gets a chance to see it.
    fallback = _find_bare_number_near(text, ["price", "budget", "rent", "cost", "rs"])
    if fallback:
        value, operator, raw = fallback
        return RangeConstraint(operator=operator, value=value, unit="inr", raw_text=raw)

    return None


_AREA_UNIT_WORDS = r"(?:sq\s?ft|sqft|square\s?feet|square\s?foot)"


def extract_area(text: str) -> Optional[RangeConstraint]:
    """Same operator vocabulary as price, but requires an explicit area
    unit word nearby so "under 1200" (ambiguous) is never mistaken for
    an area constraint without the query actually saying sqft."""

    area_num = rf"(\d+(?:\.\d+)?)\s*{_AREA_UNIT_WORDS}"

    # between X and Y sqft
    m = re.search(rf"{_BETWEEN_WORDS}\s+(\d+(?:\.\d+)?)\s*{_RANGE_JOIN}\s*(\d+(?:\.\d+)?)\s*{_AREA_UNIT_WORDS}", text)
    if m:
        lo, hi = float(m.group(1)), float(m.group(2))
        lo, hi = min(lo, hi), max(lo, hi)
        return RangeConstraint(operator="between", value_min=lo, value_max=hi, unit="sqft", raw_text=m.group(0))

    for words, op in ((_LTE_WORDS, "lte"), (_GTE_WORDS, "gte"), (_APPROX_WORDS, "approx")):
        m = re.search(rf"{words}\s+{area_num}", text)
        if m:
            return RangeConstraint(operator=op, value=float(m.group(1)), unit="sqft", raw_text=m.group(0))

    # Bare "1200 sqft" with no operator word.
    m = re.search(area_num, text)
    if m:
        return RangeConstraint(operator="eq", value=float(m.group(1)), unit="sqft", raw_text=m.group(0))

    return None
