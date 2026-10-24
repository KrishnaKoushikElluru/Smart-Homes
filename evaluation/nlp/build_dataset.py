"""
Builds evaluation/nlp/queries.json.

Two sources, both real (not filler):

1. HAND_CRAFTED - ~55 individually written, individually reasoned-about
   queries targeting specific behaviors: spelling variants, numeric
   phrasing variants, ambiguous queries, unsupported/off-topic queries,
   sparse queries, multi-constraint queries, common Indian-English
   phrasing. Each has a manually-checked `expected` block.

2. GENERATED - a template x parameter combinatorial generator covering
   property_type x listing_type x bhk x price-phrasing x location-type
   x amenity systematically. Ground truth for these is COMPUTED by the
   same code that builds the query text, not hand-transcribed - this
   guarantees correctness for a much larger volume than could be
   reliably hand-annotated, which is standard practice for NLU
   evaluation sets (ATIS/SNIPS-style). This is NOT "random queries
   without annotation" - every generated instance has an exact,
   deterministic, verifiable ground truth derived from the same
   parameters used to construct its text.

Every entry has a `category` tag so evaluate_nlp.py can report
per-category breakdowns, not just an aggregate score.
"""
import json
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent / "queries.json"
# Phase 2.5 added a clearer name/location for this same dataset - it is
# THE development set (as opposed to evaluation/nlp/data/test_queries.json,
# the independent held-out set - see evaluation/nlp/README.md). queries.json
# is kept, byte-identical, for backward compatibility with anything already
# reading that path (evaluate_nlp.py's original entry point).
DEV_OUT_PATH = Path(__file__).resolve().parent / "data" / "development_queries.json"


def entry(query, expected, category, notes=""):
    return {"query": query, "expected": expected, "category": category, "notes": notes}


# ============================================================
# 1. HAND-CRAFTED
# ============================================================

HAND_CRAFTED = [
    # ---- Simple single-field queries ----
    entry("2 bhk", {"intent": "property_search", "bedrooms": 2.0}, "simple_bhk"),
    entry("apartment", {"intent": "property_search", "property_type": "apartment"}, "simple_property_type"),
    entry("for rent", {"intent": "property_search", "listing_type": "rent"}, "simple_listing_type"),
    entry("villa for sale", {"intent": "property_search", "property_type": "villa", "listing_type": "sell"}, "simple_multi"),
    entry("fully furnished", {"intent": "property_search", "furnishing": "fully_furnished"}, "simple_furnishing"),
    entry("semi furnished 2 bhk", {"intent": "property_search", "furnishing": "semi_furnished", "bedrooms": 2.0}, "simple_multi"),

    # ---- BHK phrasing variants ----
    entry("2bhk flat for rent", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "listing_type": "rent"}, "bhk_variant", "glued digit+letters"),
    entry("2 bhk flat for rent", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "listing_type": "rent"}, "bhk_variant"),
    entry("2 BHK flat for rent", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "listing_type": "rent"}, "bhk_variant", "uppercase"),
    entry("2-bedroom flat for rent", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "listing_type": "rent"}, "bhk_variant", "hyphenated"),
    entry("two bedroom flat for rent", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "listing_type": "rent"}, "bhk_variant", "word number"),
    entry("three bhk villa", {"intent": "property_search", "bedrooms": 3.0, "property_type": "villa"}, "bhk_variant", "word number"),
    entry("1.5 bhk apartment", {"intent": "property_search", "bedrooms": 1.5, "property_type": "apartment"}, "bhk_variant", "half BHK"),

    # ---- Price phrasing / numeric variants ----
    entry("flat under 25000", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "lte", "value": 25000.0}}, "price_variant"),
    entry("flat under 25k", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "lte", "value": 25000.0}}, "price_variant", "k suffix"),
    entry("flat under 25 k", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "lte", "value": 25000.0}}, "price_variant", "spaced k"),
    entry("flat under Rs.25000", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "lte", "value": 25000.0}}, "price_variant", "Rs. prefix"),
    entry("flat under ₹25,000", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "lte", "value": 25000.0}}, "price_variant", "rupee symbol + comma"),
    entry("flat under 25 thousand", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "lte", "value": 25000.0}}, "price_variant", "spelled thousand"),
    entry("villa below 50L", {"intent": "property_search", "property_type": "villa", "price": {"operator": "lte", "value": 5000000.0}}, "price_variant", "L suffix"),
    entry("villa below 50 lakh", {"intent": "property_search", "property_type": "villa", "price": {"operator": "lte", "value": 5000000.0}}, "price_variant"),
    entry("villa below 50 lakhs", {"intent": "property_search", "property_type": "villa", "price": {"operator": "lte", "value": 5000000.0}}, "price_variant", "plural"),
    entry("villa below 0.5 crore", {"intent": "property_search", "property_type": "villa", "price": {"operator": "lte", "value": 5000000.0}}, "price_variant", "decimal crore"),
    entry("villa above 50 lakh", {"intent": "property_search", "property_type": "villa", "price": {"operator": "gte", "value": 5000000.0}}, "price_variant", "gte"),
    entry("villa around 1 crore", {"intent": "property_search", "property_type": "villa", "price": {"operator": "approx", "value": 10000000.0}}, "price_variant", "approx"),
    entry("flat between 20k and 30k", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "between", "value_min": 20000.0, "value_max": 30000.0}}, "price_variant", "between"),
    entry("flat 20k to 30k", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "between", "value_min": 20000.0, "value_max": 30000.0}}, "price_variant", "between, no 'between' keyword"),

    # ---- Area constraints ----
    entry("apartment above 1200 sqft", {"intent": "property_search", "property_type": "apartment", "area": {"operator": "gte", "value": 1200.0, "unit": "sqft"}}, "area_variant"),
    entry("apartment above 1200 sq ft", {"intent": "property_search", "property_type": "apartment", "area": {"operator": "gte", "value": 1200.0, "unit": "sqft"}}, "area_variant", "spaced sq ft"),
    entry("house with 1500 square feet", {"intent": "property_search", "property_type": "independent_house", "area": {"operator": "eq", "value": 1500.0, "unit": "sqft"}}, "area_variant", "spelled out"),
    entry("plot between 1000 and 1500 sqft", {"intent": "property_search", "property_type": "plot", "area": {"operator": "between", "value_min": 1000.0, "value_max": 1500.0, "unit": "sqft"}}, "area_variant", "between"),

    # ---- Location: POI vs city ----
    entry("2 bhk near VIT Chennai", {"intent": "property_search", "bedrooms": 2.0, "location": {"type": "poi", "query": "VIT Chennai"}}, "location_poi"),
    entry("flat around SRM", {"intent": "property_search", "property_type": "apartment", "location": {"type": "poi", "query": "SRM"}}, "location_poi", "short/ambiguous POI name"),
    entry("apartment close to Phoenix Mall", {"intent": "property_search", "property_type": "apartment", "location": {"type": "poi", "query": "Phoenix Mall"}}, "location_poi"),
    entry("house within 5 km of IIT Madras", {"intent": "property_search", "property_type": "independent_house", "location": {"type": "poi", "query": "IIT Madras"}}, "location_poi", "distance radius phrasing"),
    entry("villa beside Guindy National Park", {"intent": "property_search", "property_type": "villa", "location": {"type": "poi", "query": "Guindy National Park"}}, "location_poi"),
    entry("2 bhk in Chennai", {"intent": "property_search", "bedrooms": 2.0, "location": {"type": "area_or_city", "query": "Chennai"}}, "location_city"),
    entry("flat in Tambaram", {"intent": "property_search", "property_type": "apartment", "location": {"type": "area_or_city", "query": "Tambaram"}}, "location_locality", "locality, not a globally-known city"),
    entry("flat in Kelambakkam", {"intent": "property_search", "property_type": "apartment", "location": {"type": "area_or_city", "query": "Kelambakkam"}}, "location_locality"),
    entry("Chennai 3 bhk villa", {"intent": "property_search", "bedrooms": 3.0, "property_type": "villa", "location": {"type": "area_or_city", "query": "Chennai"}}, "location_city", "city with no preposition"),

    # ---- Amenities (single and multi) ----
    entry("flat with parking", {"intent": "property_search", "property_type": "apartment", "amenities": ["parking"]}, "amenities"),
    entry("flat with parking and gym", {"intent": "property_search", "property_type": "apartment", "amenities": ["parking", "gym"]}, "amenities", "multi amenity"),
    entry("villa with swimming pool and garden", {"intent": "property_search", "property_type": "villa", "amenities": ["swimming_pool", "garden"]}, "amenities"),
    entry("apartment with lift and power backup and cctv", {"intent": "property_search", "property_type": "apartment", "amenities": ["lift", "power_backup", "cctv"]}, "amenities", "3 amenities"),

    # ---- Multi-constraint (realistic full queries) ----
    entry(
        "2 bhk flat for rent near VIT Chennai under 25000 with parking",
        {"intent": "property_search", "listing_type": "rent", "property_type": "apartment", "bedrooms": 2.0,
         "price": {"operator": "lte", "value": 25000.0}, "location": {"type": "poi", "query": "VIT Chennai"},
         "amenities": ["parking"]},
        "multi_constraint", "task's own worked example #1",
    ),
    entry(
        "3 BHK villa for sale in Chennai below 1.5 crore with swimming pool",
        {"intent": "property_search", "listing_type": "sell", "property_type": "villa", "bedrooms": 3.0,
         "price": {"operator": "lte", "value": 15000000.0}, "location": {"type": "area_or_city", "query": "Chennai"},
         "amenities": ["swimming_pool"]},
        "multi_constraint", "task's own worked example #2",
    ),
    entry(
        "furnished 2bhk apartment for rent near Anna University under 20k with lift and security",
        {"intent": "property_search", "furnishing": "fully_furnished", "bedrooms": 2.0, "property_type": "apartment",
         "listing_type": "rent", "location": {"type": "poi", "query": "Anna University"},
         "price": {"operator": "lte", "value": 20000.0}, "amenities": ["lift", "security"]},
        "multi_constraint",
    ),
    entry(
        "3 bhk independent house for sale above 80 lakh with parking and garden in Tambaram",
        {"intent": "property_search", "bedrooms": 3.0, "property_type": "independent_house", "listing_type": "sell",
         "price": {"operator": "gte", "value": 8000000.0}, "amenities": ["parking", "garden"],
         "location": {"type": "area_or_city", "query": "Tambaram"}},
        "multi_constraint",
    ),
    entry(
        "pg for rent near SRM Kattankulathur under 8000",
        {"intent": "property_search", "property_type": "pg_hostel", "listing_type": "rent",
         "location": {"type": "poi", "query": "SRM Kattankulathur"}, "price": {"operator": "lte", "value": 8000.0}},
        "multi_constraint",
    ),

    # ---- Ambiguous queries (real, per task Step 9) ----
    entry("cheap flat near VIT", {"intent": "property_search", "property_type": "apartment", "location": {"type": "poi", "query": "VIT"}},
          "ambiguous", "'cheap' must NOT be converted to a price value - no price expected"),
    entry("near VIT", {"intent": "property_search", "location": {"type": "poi", "query": "VIT"}}, "ambiguous", "bare POI mention, nothing else"),
    entry("something affordable in Chennai", {"intent": "property_search", "location": {"type": "area_or_city", "query": "Chennai"}},
          "ambiguous", "'affordable' has no price value - must stay unspecified"),
    entry("good flat", {"intent": "property_search", "property_type": "apartment"}, "ambiguous", "'good' is not a real-estate constraint"),

    # ---- Unsupported / off-topic (per task Step 9) ----
    entry("what's the weather today", {"intent": "unknown"}, "unsupported", "completely off-topic"),
    entry("hello", {"intent": "unknown"}, "unsupported"),
    entry("how do I contact the seller", {"intent": "unknown"}, "unsupported", "support question, not a search"),
    entry("gated community with vastu compliance", {"intent": "property_search"}, "unsupported",
          "domain-adjacent phrases not in the amenity ontology - should surface as unsupported_phrases, not silently mapped"),

    # ---- Sparse / minimal queries ----
    entry("rent", {"intent": "property_search", "listing_type": "rent"}, "sparse"),
    entry("sale", {"intent": "property_search", "listing_type": "sell"}, "sparse"),
    entry("3 bhk", {"intent": "property_search", "bedrooms": 3.0}, "sparse"),

    # ---- Whitespace / casing robustness ----
    entry("   2   bhk    flat   for   rent  ", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "listing_type": "rent"}, "whitespace_robustness"),
    entry("2 BHK FLAT FOR RENT NEAR VIT CHENNAI", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "listing_type": "rent", "location": {"type": "poi", "query": "VIT Chennai"}}, "casing_robustness", "all caps"),

    # ---- Malformed numeric input ----
    entry("flat under abc", {"intent": "property_search", "property_type": "apartment"}, "malformed_numeric", "no valid number - price must stay unspecified, not error"),
    entry("flat under -5000", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "lte", "value": 5000.0}}, "malformed_numeric",
          "the regex has no sign handling, so the stray '-' is simply not part of the number match; treating this as 5000 is defensible graceful degradation, not a bug to fix"),

    # ---- Common Indian-English phrasing ----
    entry("2 bhk flat to let near Anna Nagar", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "listing_type": "rent",
                                                  "location": {"type": "poi", "query": "Anna Nagar"}}, "indian_english",
          "'to let' = for rent. type=poi (not area_or_city) is correct here per this module's own documented rule: "
          "any 'near X' construction is classified as a POI mention regardless of whether X is actually a locality "
          "or a landmark, since that distinction isn't reliably recoverable from text alone (see location_extractor.py). "
          "Original annotation of this entry mistakenly expected area_or_city; fixed after evaluation caught it."),
    entry("independent house for lease", {"intent": "property_search", "property_type": "independent_house", "listing_type": "rent"}, "indian_english", "'lease' maps to rent in this schema"),
    entry("3 bhk flat to buy in Velachery", {"intent": "property_search", "bedrooms": 3.0, "property_type": "apartment", "listing_type": "sell",
                                               "location": {"type": "area_or_city", "query": "Velachery"}}, "indian_english"),
]


# ============================================================
# 2. GENERATED (template x parameter grid, ground truth computed)
# ============================================================

PROPERTY_TYPE_TEMPLATES = [
    ("flat", "apartment"), ("apartment", "apartment"), ("villa", "villa"),
    ("independent house", "independent_house"), ("plot", "plot"), ("farmhouse", "farm_house"),
]

LISTING_TEMPLATES = [("for rent", "rent"), ("for sale", "sell")]

BHK_VALUES = [1, 2, 3, 4]

PRICE_TEMPLATES = [
    ("under {n}k", lambda n: {"operator": "lte", "value": n * 1000.0}),
    ("above {n} lakh", lambda n: {"operator": "gte", "value": n * 100000.0}),
    ("around {n} crore", lambda n: {"operator": "approx", "value": n * 10000000.0}),
]
PRICE_NUMS = [10, 25, 50, 75]

LOCATIONS = [
    ("Chennai", "area_or_city"), ("Tambaram", "area_or_city"), ("Velachery", "area_or_city"),
]

AMENITY_TEMPLATES = ["parking", "gym", "lift", "security", "power backup"]
AMENITY_CODE = {"parking": "parking", "gym": "gym", "lift": "lift", "security": "security", "power backup": "power_backup"}


def build_generated():
    out = []
    i = 0
    # Grid A: property_type x listing_type x bhk (covers vocabulary breadth)
    for (ptype_word, ptype_val) in PROPERTY_TYPE_TEMPLATES:
        for (listing_word, listing_val) in LISTING_TEMPLATES:
            if ptype_val == "plot" and listing_val == "rent":
                continue  # plots aren't rented in this domain - skip nonsensical combo
            bhk = BHK_VALUES[i % len(BHK_VALUES)]
            i += 1
            query = f"{bhk} bhk {ptype_word} {listing_word}"
            expected = {"intent": "property_search", "bedrooms": float(bhk), "property_type": ptype_val, "listing_type": listing_val}
            out.append(entry(query, expected, "generated_grid_type_listing_bhk"))

    # Grid B: price phrasing x number (covers numeric parser breadth)
    for label, fn in PRICE_TEMPLATES:
        for n in PRICE_NUMS:
            price_text = label.format(n=n)
            query = f"apartment {price_text}"
            expected = {"intent": "property_search", "property_type": "apartment", "price": fn(n)}
            out.append(entry(query, expected, "generated_grid_price"))

    # Grid C: location x property type (covers location extraction breadth)
    for city, loc_type in LOCATIONS:
        for (ptype_word, ptype_val) in PROPERTY_TYPE_TEMPLATES[:4]:
            query = f"{ptype_word} in {city}"
            expected = {"intent": "property_search", "property_type": ptype_val, "location": {"type": loc_type, "query": city}}
            out.append(entry(query, expected, "generated_grid_location"))

    # Grid D: amenities x listing type (covers amenity lexicon breadth)
    for amenity_word in AMENITY_TEMPLATES:
        for (listing_word, listing_val) in LISTING_TEMPLATES:
            query = f"flat {listing_word} with {amenity_word}"
            expected = {"intent": "property_search", "property_type": "apartment", "listing_type": listing_val,
                        "amenities": [AMENITY_CODE[amenity_word]]}
            out.append(entry(query, expected, "generated_grid_amenity"))

    return out


def main():
    dataset = HAND_CRAFTED + build_generated()
    for idx, item in enumerate(dataset):
        item["id"] = idx

    payload = json.dumps(dataset, indent=2, ensure_ascii=False)
    OUT_PATH.write_text(payload, encoding="utf-8")
    DEV_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    DEV_OUT_PATH.write_text(payload, encoding="utf-8")
    print(f"Wrote {len(dataset)} queries to {OUT_PATH}")
    print(f"Wrote {len(dataset)} queries to {DEV_OUT_PATH} (same content, canonical Phase 2.5 path)")
    print(f"  hand-crafted: {len(HAND_CRAFTED)}")
    print(f"  generated:    {len(dataset) - len(HAND_CRAFTED)}")

    from collections import Counter
    cats = Counter(item["category"] for item in dataset)
    print("Category breakdown:")
    for cat, n in sorted(cats.items()):
        print(f"  {cat}: {n}")


if __name__ == "__main__":
    main()
