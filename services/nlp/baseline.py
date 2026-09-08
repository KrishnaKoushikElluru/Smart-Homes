"""
Baseline A: a deliberately simple keyword/rule-based parser, for
comparison against the full hybrid pipeline in parser.py (Step 11 of
the Phase 2 task - "do not claim superiority until measured").

Differences from the full pipeline, all intentional:
  - No Indian numbering-system multipliers: "25k"/"50 lakh"/"1.5 crore"
    are NOT converted; only a bare number is extracted (so it will get
    "25" instead of 25000, "50" instead of 5000000, etc.) - this is
    exactly the kind of mistake a naive keyword scanner makes.
  - No operator detection at all: every price/area found is returned as
    a plain "eq" value, whether or not the query said "under"/"above"/
    "between".
  - No location.type distinction - everything found is "unknown".
  - No word-number bedrooms ("two bhk" is not recognized, only "2 bhk").
  - No amenities, no furnishing, no unsupported-phrase detection.

This is a real, runnable second implementation - not a stub - so the
evaluation comparison in evaluation/nlp/evaluate_nlp.py is measuring
something genuine.
"""

from __future__ import annotations

import re

from services.nlp.schema import Slot, RangeConstraint, LocationMention, StructuredQuery


def parse_baseline(raw_query: str) -> StructuredQuery:
    text = (raw_query or "").lower().strip()

    if not text:
        return StructuredQuery(raw_query=raw_query or "", intent="unknown", warnings=["empty query"])

    listing_type = None
    if "rent" in text:
        listing_type = Slot(value="rent", confidence=0.6, source="baseline_substring")
    elif "sale" in text or "sell" in text or "buy" in text:
        listing_type = Slot(value="sell", confidence=0.6, source="baseline_substring")

    property_type = None
    for word, value in (("flat", "apartment"), ("apartment", "apartment"),
                         ("house", "independent_house"), ("villa", "villa"), ("plot", "plot")):
        if word in text:
            property_type = Slot(value=value, confidence=0.6, source="baseline_substring")
            break

    bedrooms = None
    m = re.search(r"(\d+)\s*bhk", text)
    if m:
        bedrooms = Slot(value=float(m.group(1)), confidence=0.6, source="baseline_regex")

    price = None
    m = re.search(r"(\d+)", text)
    if m and ("price" in text or "under" in text or "budget" in text or "rent" in text
              or "sale" in text or "crore" in text or "lakh" in text or "k" in text):
        price = RangeConstraint(operator="eq", value=float(m.group(1)), unit="inr", raw_text=m.group(0))

    location = None
    m = re.search(r"\b(?:near|in)\s+(.+)$", text)
    if m:
        location = LocationMention(type="unknown", query=m.group(1).strip().title(),
                                    raw_text=m.group(0), confidence=0.4)

    has_any = any([listing_type, property_type, bedrooms, price, location])
    intent = "property_search" if has_any else "unknown"

    return StructuredQuery(
        raw_query=raw_query,
        intent=intent,
        listing_type=listing_type,
        property_type=property_type,
        bedrooms=bedrooms,
        price=price,
        location=location,
        warnings=[] if has_any else ["no recognizable real-estate search terms found"],
    )
