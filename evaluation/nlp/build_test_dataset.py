"""
Builds evaluation/nlp/data/test_queries.json - the Phase 2.5 HELD-OUT
TEST SET.

This is a SEPARATE dataset from evaluation/nlp/queries.json /
data/development_queries.json (the Phase 2 development set). It exists
to answer a criticism the development-set-only 1.000 score cannot
answer: "your parser got 100% because you tested only a small curated
dataset it was tuned against." See evaluation/nlp/README.md for the
full development-vs-test methodology and the no-tuning-against-this-set
rule this file's queries must obey.

Every query here is either:
  - HAND-AUTHORED: individually written for this file, targeting a
    property type, city, amenity, or phrasing pattern the development
    set under-represents or does not cover at all (new cities beyond
    Chennai, amenity codes never exercised in dev, Indian-English
    request-framings dev doesn't use, and deliberately UNCORRECTED
    typos - see the TYPOS section below).
  - GENERATED: a parameter-grid generator, same ATIS/SNIPS-style
    methodology as build_dataset.py's generated half (ground truth
    computed from the same parameters used to build the query text),
    but built from DIFFERENT axes than dev's grid (different property
    words, different price operators/magnitudes, different cities,
    different amenity codes) so it is not just dev's grid re-run with
    new random seeds.

CRITICAL RULE: nothing in this file may be edited to make the parser's
score on it higher. If evaluation/nlp/evaluate_nlp.py reports a failure
against a query below, the fix (if any) belongs in services/nlp/*.py,
verified against the DEVELOPMENT set, with a NEW regression case added
to test_nlp_parser.py or build_dataset.py - never by editing this file's
expected block to match whatever the parser happened to output. See
docs/PHASE_2_5_NLP_EVALUATION.md section 6 (methodology).
"""
import json
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent / "data" / "test_queries.json"


def entry(query, expected, category, notes=""):
    return {"query": query, "expected": expected, "category": category, "notes": notes}


# ============================================================
# 1. HAND-AUTHORED
# ============================================================

HAND_AUTHORED = [

    # ---- Property types under-represented or absent in the dev set ----
    entry("builder floor for rent in Gurgaon", {"intent": "property_search", "property_type": "builder_floor", "listing_type": "rent", "location": {"type": "area_or_city", "query": "Gurgaon"}}, "property_type_coverage", "builder_floor never appears in dev set at all"),
    entry("office space for rent in Bengaluru", {"intent": "property_search", "property_type": "commercial", "listing_type": "rent", "location": {"type": "area_or_city", "query": "Bengaluru"}}, "property_type_coverage"),
    entry("shop for sale in Coimbatore", {"intent": "property_search", "property_type": "commercial", "listing_type": "sell", "location": {"type": "area_or_city", "query": "Coimbatore"}}, "property_type_coverage"),
    entry("warehouse for rent near the port", {"intent": "property_search", "property_type": "commercial", "listing_type": "rent", "location": {"type": "poi", "query": "the port"}}, "property_type_coverage"),
    entry("farmhouse for sale near Kanchipuram", {"intent": "property_search", "property_type": "farm_house", "listing_type": "sell", "location": {"type": "poi", "query": "Kanchipuram"}}, "property_type_coverage"),
    entry("farm house with garden and swimming pool", {"intent": "property_search", "property_type": "farm_house", "amenities": ["garden", "swimming_pool"]}, "property_type_coverage"),
    entry("residential plot for sale in Hosur", {"intent": "property_search", "property_type": "plot", "listing_type": "sell", "location": {"type": "area_or_city", "query": "Hosur"}}, "property_type_coverage", "'Hosur' is not in the known-city gazetteer - tests area_or_city detection via bare 'in <place>' alone"),
    entry("land for sale in Salem", {"intent": "property_search", "property_type": "plot", "listing_type": "sell", "location": {"type": "area_or_city", "query": "Salem"}}, "property_type_coverage", "'land' -> plot"),
    entry("pg for boys near VIT Vellore", {"intent": "property_search", "property_type": "pg_hostel", "location": {"type": "poi", "query": "VIT Vellore"}}, "property_type_coverage"),
    entry("hostel for girls in Manipal", {"intent": "property_search", "property_type": "pg_hostel", "location": {"type": "area_or_city", "query": "Manipal"}}, "property_type_coverage", "Manipal not in known-city gazetteer"),
    entry("paying guest accommodation near Infosys campus", {"intent": "property_search", "property_type": "pg_hostel", "location": {"type": "poi", "query": "Infosys campus"}}, "property_type_coverage", "'paying guest' phrasing, not 'pg'"),
    entry("independent house for sale in Coimbatore", {"intent": "property_search", "property_type": "independent_house", "listing_type": "sell", "location": {"type": "area_or_city", "query": "Coimbatore"}}, "property_type_coverage"),

    # ---- BHK phrasing not exercised in dev ----
    entry("four bhk villa for sale", {"intent": "property_search", "bedrooms": 4.0, "property_type": "villa", "listing_type": "sell"}, "bhk_variant", "word number 'four', not in dev's word-number tests"),
    entry("one bedroom flat for rent", {"intent": "property_search", "bedrooms": 1.0, "property_type": "apartment", "listing_type": "rent"}, "bhk_variant"),
    entry("1.5bhk apartment near Anna Nagar", {"intent": "property_search", "bedrooms": 1.5, "property_type": "apartment", "location": {"type": "poi", "query": "Anna Nagar"}}, "bhk_variant", "glued 1.5bhk, dev only tests glued integer bhk"),
    entry("5 bhk villa for sale in Mumbai", {"intent": "property_search", "bedrooms": 5.0, "property_type": "villa", "listing_type": "sell", "location": {"type": "area_or_city", "query": "Mumbai"}}, "bhk_variant", "5 BHK not tested anywhere in dev"),

    # ---- Price expressions not literally covered in dev ----
    entry("flat below 25000", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "lte", "value": 25000.0}}, "price_variant"),
    entry("flat less than 25000", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "lte", "value": 25000.0}}, "price_variant", "'less than' phrasing, untested in dev"),
    entry("flat less than ₹25,000", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "lte", "value": 25000.0}}, "price_variant", "'less than' + rupee symbol + comma combined"),
    entry("apartment up to 25 thousand", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "lte", "value": 25000.0}}, "price_variant"),
    entry("villa below 75 lakh", {"intent": "property_search", "property_type": "villa", "price": {"operator": "lte", "value": 7500000.0}}, "price_variant"),
    entry("villa under 1 crore", {"intent": "property_search", "property_type": "villa", "price": {"operator": "lte", "value": 10000000.0}}, "price_variant", "'under' + crore combo untested in dev (dev only tests under+k, below+crore)"),
    entry("flat between 20 lakh and 30 lakh", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "between", "value_min": 2000000.0, "value_max": 3000000.0}}, "price_variant", "'between' at lakh magnitude - dev only tests between at k magnitude"),
    entry("villa above 50L", {"intent": "property_search", "property_type": "villa", "price": {"operator": "gte", "value": 5000000.0}}, "price_variant", "'above' + L short-form combo untested in dev (dev tests below+L and above+lakh separately, not above+L)"),
    entry("flat around 80 lakh", {"intent": "property_search", "property_type": "apartment", "price": {"operator": "approx", "value": 8000000.0}}, "price_variant", "approx at lakh magnitude, not just crore as in dev"),
    entry("2 bhk flat starting from 15000", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "price": {"operator": "gte", "value": 15000.0}}, "price_variant", "'starting from' gte phrasing, untested in dev"),
    entry("villa over 2 crore", {"intent": "property_search", "property_type": "villa", "price": {"operator": "gte", "value": 20000000.0}}, "price_variant", "'over' gte phrasing at crore magnitude"),

    # ---- Area expressions ----
    entry("apartment with 1000 sqft", {"intent": "property_search", "property_type": "apartment", "area": {"operator": "eq", "value": 1000.0, "unit": "sqft"}}, "area_variant"),
    entry("villa between 800 and 1200 sqft", {"intent": "property_search", "property_type": "villa", "area": {"operator": "between", "value_min": 800.0, "value_max": 1200.0, "unit": "sqft"}}, "area_variant"),
    entry("independent house above 2000 square feet", {"intent": "property_search", "property_type": "independent_house", "area": {"operator": "gte", "value": 2000.0, "unit": "sqft"}}, "area_variant"),
    entry("plot up to 2400 sqft", {"intent": "property_search", "property_type": "plot", "area": {"operator": "lte", "value": 2400.0, "unit": "sqft"}}, "area_variant", "'up to' as area operator, untested in dev"),

    # ---- Amenity codes never exercised in the dev set ----
    entry("flat with intercom and fire safety", {"intent": "property_search", "property_type": "apartment", "amenities": ["intercom", "fire_safety"]}, "amenities_coverage"),
    entry("apartment with 24x7 water supply and solar", {"intent": "property_search", "property_type": "apartment", "amenities": ["water_supply", "solar"]}, "amenities_coverage"),
    entry("villa with ev charging and clubhouse", {"intent": "property_search", "property_type": "villa", "amenities": ["ev_charging", "clubhouse"]}, "amenities_coverage"),
    entry("flat with jogging track and children's play area", {"intent": "property_search", "property_type": "apartment", "amenities": ["jogging_track", "childrens_play_area"]}, "amenities_coverage"),
    entry("apartment with modular kitchen and pooja room", {"intent": "property_search", "property_type": "apartment", "amenities": ["modular_kitchen", "pooja_room"]}, "amenities_coverage"),
    entry("flat with balcony and private terrace", {"intent": "property_search", "property_type": "apartment", "amenities": ["balcony", "private_terrace"]}, "amenities_coverage"),
    entry("villa with home theatre and terrace garden", {"intent": "property_search", "property_type": "villa", "amenities": ["home_theatre", "terrace_garden"]}, "amenities_coverage"),
    entry("apartment with study room and store room", {"intent": "property_search", "property_type": "apartment", "amenities": ["study_room", "store_room"]}, "amenities_coverage"),
    entry("independent house with servant room and lawn", {"intent": "property_search", "property_type": "independent_house", "amenities": ["servant_room", "lawn"]}, "amenities_coverage"),
    entry("flat with indoor games and sports facilities", {"intent": "property_search", "property_type": "apartment", "amenities": ["indoor_games", "sports_facilities"]}, "amenities_coverage"),

    # ---- Furnishing phrasings not in dev's dataset entries ----
    entry("unfurnished 2 bhk flat", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "furnishing": "unfurnished"}, "furnishing_variant", "dev's dataset entries never test unfurnished, only the standalone unit test does"),
    entry("apartment for rent, not furnished", {"intent": "property_search", "property_type": "apartment", "listing_type": "rent", "furnishing": "unfurnished"}, "furnishing_variant", "'not furnished' phrasing"),
    entry("semi-furnished villa for sale", {"intent": "property_search", "property_type": "villa", "listing_type": "sell", "furnishing": "semi_furnished"}, "furnishing_variant", "hyphenated form"),
    entry("furnished flat near IT Park", {"intent": "property_search", "property_type": "apartment", "furnishing": "fully_furnished", "location": {"type": "poi", "query": "IT Park"}}, "furnishing_variant", "bare 'furnished' (low-confidence fallback path), untested in dev's dataset entries"),

    # ---- Multi-city coverage (dev is Chennai/Tamil-Nadu-heavy) ----
    entry("2 bhk flat for rent in Bengaluru", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "listing_type": "rent", "location": {"type": "area_or_city", "query": "Bengaluru"}}, "multi_city"),
    entry("3 bhk villa for sale in Hyderabad", {"intent": "property_search", "bedrooms": 3.0, "property_type": "villa", "listing_type": "sell", "location": {"type": "area_or_city", "query": "Hyderabad"}}, "multi_city"),
    entry("1 bhk flat for rent in Mumbai under 30000", {"intent": "property_search", "bedrooms": 1.0, "property_type": "apartment", "listing_type": "rent", "location": {"type": "area_or_city", "query": "Mumbai"}, "price": {"operator": "lte", "value": 30000.0}}, "multi_city"),
    entry("2 bhk apartment for rent in Delhi", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "listing_type": "rent", "location": {"type": "area_or_city", "query": "Delhi"}}, "multi_city"),
    entry("independent house for sale in Pune", {"intent": "property_search", "property_type": "independent_house", "listing_type": "sell", "location": {"type": "area_or_city", "query": "Pune"}}, "multi_city"),
    entry("2 bhk flat in Kolkata with parking", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "location": {"type": "area_or_city", "query": "Kolkata"}, "amenities": ["parking"]}, "multi_city"),
    entry("flat for rent in Vellore near VIT", {"intent": "property_search", "property_type": "apartment", "listing_type": "rent", "location": {"type": "poi", "query": "VIT"}}, "multi_city", "location extraction prefers the POI construction ('near VIT') over the earlier bare city mention 'in Vellore' - POI check runs first in extract_location"),
    entry("3 bhk villa for sale in Ahmedabad", {"intent": "property_search", "bedrooms": 3.0, "property_type": "villa", "listing_type": "sell", "location": {"type": "area_or_city", "query": "Ahmedabad"}}, "multi_city"),

    # ---- POI mentions (new landmarks, new prepositions) ----
    entry("flat close to IIT Madras", {"intent": "property_search", "property_type": "apartment", "location": {"type": "poi", "query": "IIT Madras"}}, "location_poi", "'close to' preposition, dev tests 'close to Phoenix Mall' only"),
    entry("2 bhk near airport", {"intent": "property_search", "bedrooms": 2.0, "location": {"type": "poi", "query": "airport"}}, "location_poi", "generic single-word POI"),
    entry("villa around Phoenix Mall", {"intent": "property_search", "property_type": "villa", "location": {"type": "poi", "query": "Phoenix Mall"}}, "location_poi", "'around' as location preposition, not price approximation - dev tests 'around' only for price"),
    entry("flat within 5 km of Anna University", {"intent": "property_search", "property_type": "apartment", "location": {"type": "poi", "query": "Anna University"}}, "location_poi"),
    entry("2 bhk within 3 km of Vellore Fort", {"intent": "property_search", "bedrooms": 2.0, "location": {"type": "poi", "query": "Vellore Fort"}}, "location_poi"),
    entry("flat next to Central Railway Station", {"intent": "property_search", "property_type": "apartment", "location": {"type": "poi", "query": "Central Railway Station"}}, "location_poi", "'next to' preposition, untested in dev"),
    entry("house beside Marina Beach", {"intent": "property_search", "property_type": "independent_house", "location": {"type": "poi", "query": "Marina Beach"}}, "location_poi"),

    # ---- Indian-English request framings absent from dev ----
    entry("flat available to let in Adyar", {"intent": "property_search", "property_type": "apartment", "listing_type": "rent", "location": {"type": "area_or_city", "query": "Adyar"}}, "indian_english"),
    entry("house required for rent near railway station", {"intent": "property_search", "property_type": "independent_house", "listing_type": "rent", "location": {"type": "poi", "query": "railway station"}}, "indian_english"),
    entry("looking for a flat near Anna University", {"intent": "property_search", "property_type": "apartment", "location": {"type": "poi", "query": "Anna University"}}, "indian_english"),
    entry("need a 2bhk around Velachery", {"intent": "property_search", "bedrooms": 2.0, "location": {"type": "poi", "query": "Velachery"}}, "indian_english", "'around' correctly read as location preposition here, not price - no number+unit follows it"),
    entry("want villa for sale in Coimbatore", {"intent": "property_search", "property_type": "villa", "listing_type": "sell", "location": {"type": "area_or_city", "query": "Coimbatore"}}, "indian_english"),
    entry("property to let in Nungambakkam", {"intent": "property_search", "listing_type": "rent", "location": {"type": "area_or_city", "query": "Nungambakkam"}}, "indian_english", "'property' itself has no property_type mapping - only listing_type + location expected"),
    entry("urgently required 2 bhk flat for rent", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "listing_type": "rent"}, "indian_english"),

    # ---- Typos: measured honestly, NOT fixed in the parser ----
    entry("appartment for rent in Chennai", {"intent": "property_search", "property_type": "apartment", "listing_type": "rent", "location": {"type": "area_or_city", "query": "Chennai"}}, "typo",
          "double-p typo on 'apartment' - property_type is expected to be MISSED (regex requires exact 'apartments?'); listing_type and location should still be extracted correctly. This is a known, documented limitation (no fuzzy matching), not a bug - see docs/PHASE_2_5_NLP_EVALUATION.md error analysis."),
    entry("furnshed 2bhk flat for rent", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "listing_type": "rent", "furnishing": "fully_furnished"}, "typo",
          "'furnshed' typo - furnishing is expected to be MISSED; bedrooms/property_type/listing_type unaffected since they don't depend on that token."),
    entry("flat with parkin and gym", {"intent": "property_search", "property_type": "apartment", "amenities": ["parking", "gym"]}, "typo",
          "'parkin' typo - the 'parking' amenity is expected to be MISSED while 'gym' (spelled correctly) is still found. Tests that one typo doesn't corrupt sibling extractions."),
    entry("villaa for sale near Tambaram", {"intent": "property_search", "property_type": "villa", "listing_type": "sell", "location": {"type": "poi", "query": "Tambaram"}}, "typo",
          "double-a typo on 'villa' - property_type is expected to be MISSED; listing_type and location unaffected. NOTE: 'villaa' does NOT accidentally match \\bvilla\\b because \\b requires a non-word character or string boundary immediately after 'villa', and 'a' is a word character - the regex correctly fails here, this is not a coincidental pass."),

    # ---- Ambiguous queries ----
    entry("flat near SRM", {"intent": "property_search", "property_type": "apartment", "location": {"type": "poi", "query": "SRM"}}, "ambiguous", "short/ambiguous POI name with 'near' (dev only tests this POI with 'around')"),
    entry("house near airport", {"intent": "property_search", "property_type": "independent_house", "location": {"type": "poi", "query": "airport"}}, "ambiguous"),
    entry("VIT", {"intent": "unknown"}, "ambiguous", "a bare landmark name with zero preposition/constraint has no domain signal at all and correctly returns unknown - it is not itself a known city, and without 'near'/'in' there is nothing to classify"),
    entry("nice apartment", {"intent": "property_search", "property_type": "apartment"}, "ambiguous", "'nice' must not be converted into any field"),
    entry("cheap apartment", {"intent": "property_search", "property_type": "apartment"}, "ambiguous", "'cheap' alone, no location this time - must not produce a price"),
    entry("budget friendly 2 bhk", {"intent": "property_search", "bedrooms": 2.0}, "ambiguous", "'budget friendly' must not produce a price value despite containing the word 'budget'"),

    # ---- Unsupported / domain-adjacent language ----
    entry("pet friendly 2 bhk flat for rent", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "listing_type": "rent"}, "unsupported", "'pet friendly' is a recognized unsupported phrase; mapped fields still extracted normally alongside it"),
    entry("corner flat for sale", {"intent": "property_search", "property_type": "apartment", "listing_type": "sell"}, "unsupported", "'corner' is only recognized as unsupported in the fixed phrase 'corner plot', not 'corner flat' - intent is still correctly property_search because 'flat' itself maps to a real property_type. Documents a real (non-scored) ontology gap."),
    entry("good ventilation and natural light", {"intent": "unknown"}, "unsupported", "no known amenity, property type, or unsupported-phrase pattern matches any of this - correctly falls through to unknown, an honest 'we don't understand this at all' rather than a guess"),
    entry("ready to move 3 bhk apartment", {"intent": "property_search", "bedrooms": 3.0, "property_type": "apartment"}, "unsupported", "'ready to move' is a recognized unsupported phrase"),

    # ---- Multi-constraint realistic queries (new combinations) ----
    entry("2 bhk builder floor for rent in Gurgaon under 20000 with power backup",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "builder_floor", "listing_type": "rent",
           "location": {"type": "area_or_city", "query": "Gurgaon"}, "price": {"operator": "lte", "value": 20000.0},
           "amenities": ["power_backup"]}, "multi_constraint"),
    entry("3 bhk villa for sale in Hyderabad below 1 crore with clubhouse and gym",
          {"intent": "property_search", "bedrooms": 3.0, "property_type": "villa", "listing_type": "sell",
           "location": {"type": "area_or_city", "query": "Hyderabad"}, "price": {"operator": "lte", "value": 10000000.0},
           "amenities": ["clubhouse", "gym"]}, "multi_constraint"),
    entry("unfurnished 1 bhk flat for rent near Anna University under 12000",
          {"intent": "property_search", "furnishing": "unfurnished", "bedrooms": 1.0, "property_type": "apartment",
           "listing_type": "rent", "location": {"type": "poi", "query": "Anna University"},
           "price": {"operator": "lte", "value": 12000.0}}, "multi_constraint"),
    entry("pg for rent near VIT Vellore under 7000 with wifi",
          {"intent": "property_search", "property_type": "pg_hostel", "listing_type": "rent",
           "location": {"type": "poi", "query": "VIT Vellore"}, "price": {"operator": "lte", "value": 7000.0}},
          "multi_constraint", "'wifi' has no amenity mapping - expected amenities list is empty; only tests the other fields"),
    entry("2 bhk independent house for sale in Coimbatore above 60 lakh with solar and balcony",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "independent_house", "listing_type": "sell",
           "location": {"type": "area_or_city", "query": "Coimbatore"}, "price": {"operator": "gte", "value": 6000000.0},
           "amenities": ["solar", "balcony"]}, "multi_constraint"),
]


# ============================================================
# 2. GENERATED (different axes than build_dataset.py's grid)
# ============================================================

# Grid A: property_type x "N bedroom" phrasing (dev's grid only used the
# word "bhk", never "bedroom", at scale).
PROPERTY_TYPE_TEMPLATES_2 = [
    ("flat", "apartment"), ("villa", "villa"), ("independent house", "independent_house"),
    ("builder floor", "builder_floor"), ("farmhouse", "farm_house"),
]
LISTING_TEMPLATES_2 = [("for rent", "rent"), ("for sale", "sell")]
BHK_VALUES_2 = [1, 2, 3, 4]


def build_grid_bedroom_phrasing():
    out = []
    i = 0
    for (ptype_word, ptype_val) in PROPERTY_TYPE_TEMPLATES_2:
        for (listing_word, listing_val) in LISTING_TEMPLATES_2:
            bhk = BHK_VALUES_2[i % len(BHK_VALUES_2)]
            i += 1
            query = f"{bhk} bedroom {ptype_word} {listing_word}"
            expected = {"intent": "property_search", "bedrooms": float(bhk), "property_type": ptype_val, "listing_type": listing_val}
            out.append(entry(query, expected, "generated_grid_bedroom_phrasing"))
    return out


# Grid B: price phrasing x number, different operator words/magnitudes
# than dev's grid (which used under/above/around x [10,25,50,75]).
PRICE_TEMPLATES_2 = [
    ("below {n} lakh", lambda n: {"operator": "lte", "value": n * 100000.0}),
    ("up to {n} lakh", lambda n: {"operator": "lte", "value": n * 100000.0}),
    ("over {n} lakh", lambda n: {"operator": "gte", "value": n * 100000.0}),
]
PRICE_NUMS_2 = [15, 35, 60, 90]


def build_grid_price():
    out = []
    for label, fn in PRICE_TEMPLATES_2:
        for n in PRICE_NUMS_2:
            price_text = label.format(n=n)
            query = f"villa {price_text}"
            expected = {"intent": "property_search", "property_type": "villa", "price": fn(n)}
            out.append(entry(query, expected, "generated_grid_price"))
    return out


# Grid C: bare city mention (no preposition), across cities dev's grid
# never used at all (dev's location grid only used Chennai/Tambaram/Velachery).
CITIES_2 = ["Bengaluru", "Hyderabad", "Mumbai", "Delhi", "Pune", "Kolkata", "Coimbatore", "Vellore"]


def build_grid_city():
    out = []
    for city in CITIES_2:
        query = f"{city} 2 bhk flat for rent"
        expected = {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "listing_type": "rent",
                    "location": {"type": "area_or_city", "query": city}}
        out.append(entry(query, expected, "generated_grid_city", "bare city name with no preposition, at the START of the query"))
    return out


# Grid D: amenity codes dev's amenity grid never touched (dev's grid used
# only parking/gym/lift/security/power backup).
AMENITY_TEMPLATES_2 = [
    ("intercom", "intercom"), ("fire safety", "fire_safety"), ("solar", "solar"),
    ("clubhouse", "clubhouse"), ("jogging track", "jogging_track"), ("balcony", "balcony"),
    ("home theatre", "home_theatre"), ("pooja room", "pooja_room"),
]


def build_grid_amenity():
    out = []
    for (amenity_word, amenity_code) in AMENITY_TEMPLATES_2:
        for (listing_word, listing_val) in LISTING_TEMPLATES_2:
            query = f"villa {listing_word} with {amenity_word}"
            expected = {"intent": "property_search", "property_type": "villa", "listing_type": listing_val,
                        "amenities": [amenity_code]}
            out.append(entry(query, expected, "generated_grid_amenity"))
    return out


def build_generated():
    return build_grid_bedroom_phrasing() + build_grid_price() + build_grid_city() + build_grid_amenity()


def main():
    dataset = HAND_AUTHORED + build_generated()
    for idx, item in enumerate(dataset):
        item["id"] = idx

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(dataset)} queries to {OUT_PATH}")
    print(f"  hand-authored: {len(HAND_AUTHORED)}")
    print(f"  generated:     {len(dataset) - len(HAND_AUTHORED)}")

    from collections import Counter
    cats = Counter(item["category"] for item in dataset)
    print("Category breakdown:")
    for cat, n in sorted(cats.items()):
        print(f"  {cat}: {n}")


if __name__ == "__main__":
    main()
