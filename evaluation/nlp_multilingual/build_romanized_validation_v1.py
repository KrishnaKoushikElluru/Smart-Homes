"""
EXPERIMENT-ONLY. Builds the Phase 5.7 validation dataset (100 genuinely
new Romanized/code-mixed queries - NOT reworded copies of the Phase 5.6
84-query dataset or its 13-query held-out set).

Run once, then the output is FROZEN (see freeze_romanized_validation_v1.py
for the checksum record) - this generator is a provenance record, not
something to be re-run and re-tuned against evaluation results. Per
Phase 5.7's own rules: no rule/gold-label changes after seeing results.

Deliberate design choices, all disclosed in docs/PHASE_5_7_ROMANIZED_VALIDATION.md:
  - 6 new POI names not seen in Phase 5.6 (Prestige Towers, Loyola
    College, Anna University, Apollo Hospital, Hiranandani Gardens, plus
    the 5 already-known ones reused: VIT Chennai, Tata Homes, Mambakkam,
    SRM/SBIOA) - to test whether proper-noun protection generalizes.
  - Several entries deliberately use Romanized spelling variants NOT in
    the frozen romanized_normalizer.py lexicon (kitta, deggara, irukanum,
    ulla) - an honest robustness/generalization-boundary test, not a bug
    in this generator. Expected to sometimes fail; that is the point.
  - "want"-words (venum/chahiye/kavali/irukkanum/undali) are attached
    directly to property attributes ("flat gym venum") for AMENITY
    queries (no near-word present -> nearby_facility_extractor does not
    fire -> falls through to the amenity lexicon, confirmed against
    services/nlp/nearby_facility_extractor.py's own preposition
    requirement), and attached after an explicit near-word (pakkathula/
    pakkam/kitta/ke paas/daggara/deggara) for NEARBY_FACILITY queries -
    this resolves what would otherwise be a genuine gold-label ambiguity
    (see Phase 5.7's task instructions section 7).
"""
from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT_PATH = HERE / "data" / "romanized_validation_v1.json"

_next_id = [30000]


def entry(query, expected, category, language, difficulty, notes=""):
    e = {
        "id": _next_id[0],
        "query": query,
        "expected": expected,
        "category": category,
        "language": language,
        "difficulty": difficulty,
        "notes": notes,
    }
    _next_id[0] += 1
    return e


def loc_poi(name):
    return {"type": "poi", "query": name}


def loc_city(name="Chennai"):
    return {"type": "area_or_city", "query": name}


def price_lte(v):
    return {"operator": "lte", "value": float(v)}


def area_eq(v):
    return {"operator": "eq", "value": float(v)}


DATA = []

# ============================================================
# TAMIL-ENGLISH (35)
# ============================================================
DATA += [
    entry("2 BHK flat venum", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment"},
          "simple_bhk", "ta-en", "easy"),
    entry("3 BHK apartment venum", {"intent": "property_search", "bedrooms": 3.0, "property_type": "apartment"},
          "simple_bhk", "ta-en", "easy"),
    entry("1 BHK house venum", {"intent": "property_search", "bedrooms": 1.0, "property_type": "independent_house"},
          "property_type", "ta-en", "easy"),
    entry("villa venum", {"intent": "property_search", "property_type": "villa"},
          "property_type", "ta-en", "easy"),
    entry("fully furnished flat venum", {"intent": "property_search", "property_type": "apartment", "furnishing": "fully_furnished"},
          "furnishing", "ta-en", "easy"),
    entry("semi furnished 2 BHK venum", {"intent": "property_search", "bedrooms": 2.0, "furnishing": "semi_furnished"},
          "furnishing", "ta-en", "easy"),
    entry("unfurnished 3 BHK flat venum", {"intent": "property_search", "bedrooms": 3.0, "property_type": "apartment", "furnishing": "unfurnished"},
          "furnishing", "ta-en", "easy"),
    entry("rent ku 2 BHK flat venum", {"intent": "property_search", "listing_type": "rent", "bedrooms": 2.0, "property_type": "apartment"},
          "rent", "ta-en", "easy"),
    entry("sale ku 3 BHK flat venum", {"intent": "property_search", "listing_type": "sell", "bedrooms": 3.0, "property_type": "apartment"},
          "sell", "ta-en", "easy"),
    entry("2 BHK flat irukanum", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment"},
          "simple_bhk", "ta-en", "easy",
          "spelling variant 'irukanum' (single-k) is NOT in the frozen lexicon (only 'irukkanum' is) - want-word does not gate any field, so this is expected to still pass, confirming the want-rule was never load-bearing."),
    entry("2 BHK flat 20k kulla venum", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "price": price_lte(20000)},
          "price_variant", "ta-en", "medium"),
    entry("3 BHK flat 25k kulla venum", {"intent": "property_search", "bedrooms": 3.0, "property_type": "apartment", "price": price_lte(25000)},
          "price_variant", "ta-en", "medium"),
    entry("flat 40 thousand kulla venum", {"intent": "property_search", "property_type": "apartment", "price": price_lte(40000)},
          "price_variant", "ta-en", "medium"),
    entry("2 BHK flat 1 lakh kulla venum", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "price": price_lte(100000)},
          "price_variant", "ta-en", "medium"),
    entry("2 BHK flat gym venum", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "amenities": ["gym"]},
          "amenities", "ta-en", "medium"),
    entry("flat parking balcony venum", {"intent": "property_search", "property_type": "apartment", "amenities": ["parking", "balcony"]},
          "amenities", "ta-en", "medium"),
    entry("hospital kitta 2 BHK flat venum", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "nearby_facilities": [{"category": "hospital"}]},
          "nearby_facility", "ta-en", "medium",
          "'kitta' (near) is NOT in the frozen lexicon - deliberate robustness/generalization-boundary test, expected to likely fail (hospital falls through to the amenity lexicon instead of nearby_facility)."),
    entry("school pakkathula 3 BHK flat venum", {"intent": "property_search", "bedrooms": 3.0, "property_type": "apartment", "nearby_facilities": [{"category": "school"}]},
          "nearby_facility", "ta-en", "medium"),
    entry("supermarket pakkam flat venum", {"intent": "property_search", "property_type": "apartment", "nearby_facilities": [{"category": "supermarket"}]},
          "nearby_facility", "ta-en", "medium"),
    entry("Chennai la 2 BHK semi furnished flat venum", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "furnishing": "semi_furnished", "location": loc_city()},
          "multi_constraint", "ta-en", "medium"),
    entry("rent ku 2 BHK flat 25k kulla venum", {"intent": "property_search", "listing_type": "rent", "bedrooms": 2.0, "property_type": "apartment", "price": price_lte(25000)},
          "multi_constraint", "ta-en", "medium"),
    entry("Chennai la 3 BHK villa 50k kulla venum", {"intent": "property_search", "bedrooms": 3.0, "property_type": "villa", "location": loc_city(), "price": price_lte(50000)},
          "multi_constraint", "ta-en", "medium"),
    entry("Prestige Towers pakkathula 2 BHK flat venum", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "location": loc_poi("Prestige Towers")},
          "location_poi", "ta-en", "hard", "NEW POI, not in Phase 5.6."),
    entry("Loyola College pakkam flat venum", {"intent": "property_search", "property_type": "apartment", "location": loc_poi("Loyola College")},
          "location_poi", "ta-en", "hard", "NEW POI, not in Phase 5.6."),
    entry("Apollo Hospital pakkathula 2 BHK flat venum", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "location": loc_poi("Apollo Hospital")},
          "location_poi", "ta-en", "hard", "NEW POI; specific named hospital (POI), distinct from the generic 'hospital' nearby_facility category tested elsewhere."),
    entry("SBIOA pakkam 3 BHK house venum", {"intent": "property_search", "bedrooms": 3.0, "property_type": "independent_house", "location": loc_poi("SBIOA")},
          "location_poi", "ta-en", "hard"),
    entry("VIT Chennai pakkathula 2 BHK semi furnished flat venum 30k kulla",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "furnishing": "semi_furnished", "location": loc_poi("VIT Chennai"), "price": price_lte(30000)},
          "multi_constraint", "ta-en", "hard", "POI + furnishing + price all in one query."),
    entry("Mambakkam pakkam 3 BHK house venum parking irukkanum",
          {"intent": "property_search", "bedrooms": 3.0, "property_type": "independent_house", "location": loc_poi("Mambakkam"), "amenities": ["parking"]},
          "multi_constraint", "ta-en", "hard"),
    entry("flat 1.5 crore kulla venum", {"intent": "property_search", "property_type": "apartment", "price": price_lte(15000000)},
          "numeric_unit", "ta-en", "hard", "decimal-value price."),
    entry("3 BHK villa 80 lakh kulla venum", {"intent": "property_search", "bedrooms": 3.0, "property_type": "villa", "price": price_lte(8000000)},
          "numeric_unit", "ta-en", "hard"),
    entry("gym pakkathula flat venum 1 km ulla",
          {"intent": "property_search", "property_type": "apartment", "nearby_facilities": [{"category": "gym", "radius_m": 1000.0}]},
          "distance", "ta-en", "hard",
          "'ulla' (within/inside) is NOT in the frozen lexicon (only 'kulla' is) - radius extraction is not scored by the reused slot-comparison framework (see report methodology note); included to observe real behavior, not scored on radius specifically."),
    entry("hospital pakkam 2 km kulla flat venum",
          {"intent": "property_search", "property_type": "apartment", "nearby_facilities": [{"category": "hospital", "radius_m": 2000.0}]},
          "distance", "ta-en", "hard", "'kulla' reused here for a distance radius rather than price - overload/robustness test."),
    entry("1000 sqft flat venum", {"intent": "property_search", "property_type": "apartment", "area": area_eq(1000)},
          "area", "ta-en", "medium"),
    entry("2 BHK flat 1200 sqft venum", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "area": area_eq(1200)},
          "area", "ta-en", "medium"),
    entry("2 BHK flat rent ku venum Chennai la",
          {"intent": "property_search", "listing_type": "rent", "bedrooms": 2.0, "property_type": "apartment", "location": loc_city()},
          "simple_multi", "ta-en", "easy"),
]

# ============================================================
# HINDI-ENGLISH (30)
# ============================================================
DATA += [
    entry("2 BHK flat chahiye", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment"},
          "simple_bhk", "hi-en", "easy"),
    entry("3 BHK apartment chahiye", {"intent": "property_search", "bedrooms": 3.0, "property_type": "apartment"},
          "simple_bhk", "hi-en", "easy"),
    entry("1 BHK ghar chahiye", {"intent": "property_search", "bedrooms": 1.0, "property_type": "independent_house"},
          "property_type", "hi-en", "easy"),
    entry("villa chahiye", {"intent": "property_search", "property_type": "villa"},
          "property_type", "hi-en", "easy"),
    entry("fully furnished flat chahiye", {"intent": "property_search", "property_type": "apartment", "furnishing": "fully_furnished"},
          "furnishing", "hi-en", "easy"),
    entry("semi furnished 2 BHK chahiye", {"intent": "property_search", "bedrooms": 2.0, "furnishing": "semi_furnished"},
          "furnishing", "hi-en", "easy"),
    entry("unfurnished 3 BHK flat chahiye", {"intent": "property_search", "bedrooms": 3.0, "property_type": "apartment", "furnishing": "unfurnished"},
          "furnishing", "hi-en", "easy"),
    entry("rent ke liye 2 BHK flat chahiye", {"intent": "property_search", "listing_type": "rent", "bedrooms": 2.0, "property_type": "apartment"},
          "rent", "hi-en", "easy"),
    entry("sale ke liye 3 BHK flat chahiye", {"intent": "property_search", "listing_type": "sell", "bedrooms": 3.0, "property_type": "apartment"},
          "sell", "hi-en", "easy"),
    entry("Chennai me 2 BHK flat chahiye", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "location": loc_city()},
          "simple_bhk", "hi-en", "easy", "'me' spelling variant of 'mein' - both are no-ops under the frozen normalizer (the 'in' rule was removed in Phase 5.6); Chennai is still recognized directly."),
    entry("2 BHK flat 20k ke andar chahiye", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "price": price_lte(20000)},
          "price_variant", "hi-en", "medium"),
    entry("3 BHK flat 30 hazaar ke andar chahiye", {"intent": "property_search", "bedrooms": 3.0, "property_type": "apartment", "price": price_lte(30000)},
          "price_variant", "hi-en", "medium"),
    entry("flat 50 hazaar ke andar chahiye", {"intent": "property_search", "property_type": "apartment", "price": price_lte(50000)},
          "price_variant", "hi-en", "medium"),
    entry("2 BHK flat 1 lakh ke andar chahiye", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "price": price_lte(100000)},
          "price_variant", "hi-en", "medium"),
    entry("2 BHK flat gym chahiye", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "amenities": ["gym"]},
          "amenities", "hi-en", "medium"),
    entry("flat parking balcony chahiye", {"intent": "property_search", "property_type": "apartment", "amenities": ["parking", "balcony"]},
          "amenities", "hi-en", "medium"),
    entry("hospital ke paas 2 BHK flat chahiye", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "nearby_facilities": [{"category": "hospital"}]},
          "nearby_facility", "hi-en", "medium"),
    entry("school ke paas 3 BHK flat chahiye", {"intent": "property_search", "bedrooms": 3.0, "property_type": "apartment", "nearby_facilities": [{"category": "school"}]},
          "nearby_facility", "hi-en", "medium"),
    entry("1000 sqft flat chahiye", {"intent": "property_search", "property_type": "apartment", "area": area_eq(1000)},
          "area", "hi-en", "medium"),
    entry("Chennai mein 2 BHK semi furnished flat chahiye", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "furnishing": "semi_furnished", "location": loc_city()},
          "multi_constraint", "hi-en", "medium"),
    entry("rent ke liye 2 BHK flat 25k ke andar chahiye", {"intent": "property_search", "listing_type": "rent", "bedrooms": 2.0, "property_type": "apartment", "price": price_lte(25000)},
          "multi_constraint", "hi-en", "medium"),
    entry("gym ke paas flat chahiye 1 km ke andar",
          {"intent": "property_search", "property_type": "apartment", "nearby_facilities": [{"category": "gym", "radius_m": 1000.0}]},
          "distance", "hi-en", "hard", "'ke andar' reused for a distance radius rather than price - overload/robustness test; radius not scored by the reused framework."),
    entry("Prestige Towers ke paas 2 BHK flat chahiye", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "location": loc_poi("Prestige Towers")},
          "location_poi", "hi-en", "hard", "NEW POI, not in Phase 5.6."),
    entry("Anna University ke paas flat chahiye", {"intent": "property_search", "property_type": "apartment", "location": loc_poi("Anna University")},
          "location_poi", "hi-en", "hard", "NEW POI, not in Phase 5.6."),
    entry("Apollo Hospital ke paas 2 BHK flat chahiye", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "location": loc_poi("Apollo Hospital")},
          "location_poi", "hi-en", "hard", "NEW POI; specific named hospital, distinct from the generic 'hospital' facility category."),
    entry("SBIOA ke paas 3 BHK ghar chahiye", {"intent": "property_search", "bedrooms": 3.0, "property_type": "independent_house", "location": loc_poi("SBIOA")},
          "location_poi", "hi-en", "hard"),
    entry("VIT Chennai ke paas 2 BHK semi furnished flat chahiye 30k ke andar",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "furnishing": "semi_furnished", "location": loc_poi("VIT Chennai"), "price": price_lte(30000)},
          "multi_constraint", "hi-en", "hard"),
    entry("Mambakkam ke paas 3 BHK ghar chahiye parking chahiye",
          {"intent": "property_search", "bedrooms": 3.0, "property_type": "independent_house", "location": loc_poi("Mambakkam"), "amenities": ["parking"]},
          "multi_constraint", "hi-en", "hard"),
    entry("flat 1.5 crore ke andar chahiye", {"intent": "property_search", "property_type": "apartment", "price": price_lte(15000000)},
          "numeric_unit", "hi-en", "hard"),
    entry("3 BHK villa 80 lakh ke andar chahiye", {"intent": "property_search", "bedrooms": 3.0, "property_type": "villa", "price": price_lte(8000000)},
          "numeric_unit", "hi-en", "hard"),
]

# ============================================================
# TELUGU-ENGLISH (35)
# ============================================================
DATA += [
    entry("2 BHK flat kavali", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment"},
          "simple_bhk", "te-en", "easy"),
    entry("3 BHK apartment kavali", {"intent": "property_search", "bedrooms": 3.0, "property_type": "apartment"},
          "simple_bhk", "te-en", "easy"),
    entry("1 BHK illu kavali", {"intent": "property_search", "bedrooms": 1.0, "property_type": "independent_house"},
          "property_type", "te-en", "easy"),
    entry("villa kavali", {"intent": "property_search", "property_type": "villa"},
          "property_type", "te-en", "easy"),
    entry("fully furnished flat kavali", {"intent": "property_search", "property_type": "apartment", "furnishing": "fully_furnished"},
          "furnishing", "te-en", "easy"),
    entry("semi furnished 2 BHK kavali", {"intent": "property_search", "bedrooms": 2.0, "furnishing": "semi_furnished"},
          "furnishing", "te-en", "easy"),
    entry("unfurnished 3 BHK flat kavali", {"intent": "property_search", "bedrooms": 3.0, "property_type": "apartment", "furnishing": "unfurnished"},
          "furnishing", "te-en", "easy"),
    entry("rent ki 2 BHK flat kavali", {"intent": "property_search", "listing_type": "rent", "bedrooms": 2.0, "property_type": "apartment"},
          "rent", "te-en", "easy"),
    entry("sale ki 3 BHK flat kavali", {"intent": "property_search", "listing_type": "sell", "bedrooms": 3.0, "property_type": "apartment"},
          "sell", "te-en", "easy"),
    entry("2 BHK flat undali", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment"},
          "simple_bhk", "te-en", "easy", "'undali' IS in the frozen lexicon (mapped to 'want')."),
    entry("2 BHK flat 20k lopala kavali", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "price": price_lte(20000)},
          "price_variant", "te-en", "medium"),
    entry("3 BHK flat 30 vela lopala kavali", {"intent": "property_search", "bedrooms": 3.0, "property_type": "apartment", "price": price_lte(30000)},
          "price_variant", "te-en", "medium"),
    entry("flat 50 vela lopala kavali", {"intent": "property_search", "property_type": "apartment", "price": price_lte(50000)},
          "price_variant", "te-en", "medium"),
    entry("2 BHK flat 1 lakh lopala kavali", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "price": price_lte(100000)},
          "price_variant", "te-en", "medium"),
    entry("2 BHK flat gym kavali", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "amenities": ["gym"]},
          "amenities", "te-en", "medium"),
    entry("flat parking balcony kavali", {"intent": "property_search", "property_type": "apartment", "amenities": ["parking", "balcony"]},
          "amenities", "te-en", "medium"),
    entry("hospital daggara 2 BHK flat kavali", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "nearby_facilities": [{"category": "hospital"}]},
          "nearby_facility", "te-en", "medium"),
    entry("school daggara 3 BHK flat kavali", {"intent": "property_search", "bedrooms": 3.0, "property_type": "apartment", "nearby_facilities": [{"category": "school"}]},
          "nearby_facility", "te-en", "medium"),
    entry("supermarket deggara flat kavali", {"intent": "property_search", "property_type": "apartment", "nearby_facilities": [{"category": "supermarket"}]},
          "nearby_facility", "te-en", "medium",
          "'deggara' spelling variant of 'daggara' is NOT in the frozen lexicon - deliberate robustness/generalization-boundary test, expected to likely fail."),
    entry("Chennai lo 2 BHK semi furnished flat kavali", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "furnishing": "semi_furnished", "location": loc_city()},
          "multi_constraint", "te-en", "medium"),
    entry("rent ki 2 BHK flat 25k lopala kavali", {"intent": "property_search", "listing_type": "rent", "bedrooms": 2.0, "property_type": "apartment", "price": price_lte(25000)},
          "multi_constraint", "te-en", "medium"),
    entry("Chennai lo 3 BHK villa 50k lopala kavali", {"intent": "property_search", "bedrooms": 3.0, "property_type": "villa", "location": loc_city(), "price": price_lte(50000)},
          "multi_constraint", "te-en", "medium"),
    entry("Prestige Towers daggara 2 BHK flat kavali", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "location": loc_poi("Prestige Towers")},
          "location_poi", "te-en", "hard", "NEW POI, not in Phase 5.6."),
    entry("Hiranandani Gardens daggara flat kavali", {"intent": "property_search", "property_type": "apartment", "location": loc_poi("Hiranandani Gardens")},
          "location_poi", "te-en", "hard", "NEW POI, not in Phase 5.6."),
    entry("Apollo Hospital daggara 2 BHK flat kavali", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "location": loc_poi("Apollo Hospital")},
          "location_poi", "te-en", "hard", "NEW POI; specific named hospital, distinct from the generic 'hospital' facility category."),
    entry("SBIOA daggara 3 BHK illu kavali", {"intent": "property_search", "bedrooms": 3.0, "property_type": "independent_house", "location": loc_poi("SBIOA")},
          "location_poi", "te-en", "hard"),
    entry("VIT Chennai daggara 2 BHK semi furnished flat kavali 30k lopala",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "furnishing": "semi_furnished", "location": loc_poi("VIT Chennai"), "price": price_lte(30000)},
          "multi_constraint", "te-en", "hard"),
    entry("Mambakkam daggara 3 BHK illu kavali parking undali",
          {"intent": "property_search", "bedrooms": 3.0, "property_type": "independent_house", "location": loc_poi("Mambakkam"), "amenities": ["parking"]},
          "multi_constraint", "te-en", "hard"),
    entry("flat 1.5 crore lopala kavali", {"intent": "property_search", "property_type": "apartment", "price": price_lte(15000000)},
          "numeric_unit", "te-en", "hard"),
    entry("3 BHK villa 80 lakh lopala kavali", {"intent": "property_search", "bedrooms": 3.0, "property_type": "villa", "price": price_lte(8000000)},
          "numeric_unit", "te-en", "hard"),
    entry("1000 sqft flat kavali", {"intent": "property_search", "property_type": "apartment", "area": area_eq(1000)},
          "area", "te-en", "medium"),
    entry("2 BHK flat 1200 sqft kavali", {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment", "area": area_eq(1200)},
          "area", "te-en", "medium"),
    entry("gym daggara flat kavali 1 km lopala",
          {"intent": "property_search", "property_type": "apartment", "nearby_facilities": [{"category": "gym", "radius_m": 1000.0}]},
          "distance", "te-en", "hard", "radius not scored by the reused framework; included to observe real behavior."),
    entry("hospital daggara 2 km lopala flat kavali",
          {"intent": "property_search", "property_type": "apartment", "nearby_facilities": [{"category": "hospital", "radius_m": 2000.0}]},
          "distance", "te-en", "hard"),
    entry("2 BHK flat rent ki kavali Chennai lo",
          {"intent": "property_search", "listing_type": "rent", "bedrooms": 2.0, "property_type": "apartment", "location": loc_city()},
          "simple_multi", "te-en", "easy"),
]

assert len(DATA) == 100, f"expected 100 entries, got {len(DATA)}"
assert len({e['id'] for e in DATA}) == 100, "duplicate ids"

OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
OUT_PATH.write_text(json.dumps(DATA, indent=2, ensure_ascii=False), encoding="utf-8")
print(f"Wrote {len(DATA)} entries to {OUT_PATH}")

from collections import Counter
print("by language:", dict(Counter(e["language"] for e in DATA)))
print("by category:", dict(Counter(e["category"] for e in DATA)))
print("by difficulty:", dict(Counter(e["difficulty"] for e in DATA)))
