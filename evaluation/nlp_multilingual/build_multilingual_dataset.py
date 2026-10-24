"""
Builds evaluation/nlp_multilingual/data/multilingual_dev_queries.json -
the multilingual/code-mixed benchmark dataset for the IndicTrans2
translation-then-parse benchmark.

COMPLETELY SEPARATE from evaluation/nlp/data/*.json (the existing
244-query English evaluation set) - this file NEVER reads, imports, or
modifies anything under evaluation/nlp/. See docs proposal from the
prior "Multilingual NLP Search" design phase for the full rationale.

Same `entry()` convention as evaluation/nlp/build_test_dataset.py, with
one addition: every entry carries a "language" tag (ISO-ish code, with
"-en" suffix for a Latin-script code-mixed variant of that language):

    en      English (control group - never translated, parsed directly)
    ta      Tamil (native script)
    ta-en   Tanglish (Tamil-English romanized code-mixing)
    hi      Hindi (native script)
    hi-en   Hinglish (Hindi-English romanized code-mixing)
    te      Telugu (native script)
    te-en   Telugu-English romanized code-mixing

`expected` is the SAME StructuredQuery-partial shape the existing
evaluator already understands (services.nlp.schema field names) - it
describes the TRUE semantic content of the query, i.e. what a perfect
translation + the existing, unmodified English parser should together
produce. This is deliberately NOT "what IndicTrans2 happens to output
today" - the whole point of the benchmark is to measure the gap between
this and reality, honestly.

Categories mirror a representative subset of evaluation/nlp/'s existing
31 categories (simple_bhk, simple_furnishing, price_variant,
location_poi, amenities, nearby_facility, multi_constraint, numeric_*),
re-authored per language rather than copied - direct translations of
the SAME small set of underlying real-estate intents, which is what
makes the language/category breakdown meaningful (comparing apples to
apples across languages, not different difficulty per language).

POI names are drawn from ones already used elsewhere in this project's
own test data/docs (VIT Chennai, SRM, Mambakkam, Tata Homes) - never
invented, so a translation failure on them is directly comparable to
this project's own prior English-only findings about those exact names.
"""

import json
from pathlib import Path

OUT_PATH = Path(__file__).resolve().parent / "data" / "multilingual_dev_queries.json"


def entry(query, expected, category, language, notes=""):
    return {
        "query": query,
        "expected": expected,
        "category": category,
        "language": language,
        "notes": notes,
    }


# ============================================================
# 1. ENGLISH CONTROL GROUP
#
# Never translated - parsed directly by services.nlp.parser.parse(),
# exactly like evaluation/nlp/'s existing dataset. Exists so the
# benchmark can report "translated-language accuracy" against a
# same-session "English accuracy" baseline computed the SAME way, not
# just cited from a different evaluation run.
# ============================================================

ENGLISH_CONTROL = [
    entry("2 BHK flat in Chennai",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "location": {"type": "area_or_city", "query": "Chennai"}},
          "simple_bhk", "en"),

    entry("flat for rent near VIT Chennai",
          {"intent": "property_search", "listing_type": "rent", "property_type": "apartment",
           "location": {"type": "poi", "query": "VIT Chennai"}},
          "location_poi", "en"),

    entry("2 BHK flat under 30000",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "price": {"operator": "lte", "value": 30000.0}},
          "price_variant", "en"),

    entry("semi furnished 2 BHK near SRM",
          {"intent": "property_search", "furnishing": "semi_furnished", "bedrooms": 2.0,
           "location": {"type": "poi", "query": "SRM"}},
          "multi_constraint", "en"),

    entry("villa for sale in Chennai",
          {"intent": "property_search", "property_type": "villa", "listing_type": "sell",
           "location": {"type": "area_or_city", "query": "Chennai"}},
          "simple_multi", "en"),

    entry("flat near a gym",
          {"intent": "property_search", "property_type": "apartment",
           "nearby_facilities": [{"category": "gym"}]},
          "nearby_facility", "en"),

    entry("2 BHK apartment near Mambakkam under 30k",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "location": {"type": "poi", "query": "Mambakkam"},
           "price": {"operator": "lte", "value": 30000.0}},
          "multi_constraint", "en"),

    entry("flat near Tata Homes",
          {"intent": "property_search", "property_type": "apartment",
           "location": {"type": "poi", "query": "Tata Homes"}},
          "location_poi", "en"),

    entry("1200 sqft flat",
          {"intent": "property_search", "property_type": "apartment",
           "area": {"operator": "eq", "value": 1200.0}},
          "area_variant", "en"),

    entry("flat between 20k and 30k",
          {"intent": "property_search", "property_type": "apartment",
           "price": {"operator": "between", "value_min": 20000.0, "value_max": 30000.0}},
          "price_variant", "en"),

    entry("3 BHK house near a railway station",
          {"intent": "property_search", "bedrooms": 3.0, "property_type": "independent_house",
           "nearby_facilities": [{"category": "railway_station"}]},
          "nearby_facility", "en"),

    entry("flat near a hospital in Chennai",
          {"intent": "property_search", "property_type": "apartment",
           "location": {"type": "area_or_city", "query": "Chennai"},
           "nearby_facilities": [{"category": "hospital"}]},
          "nearby_facility", "en"),
]


# ============================================================
# 2. TAMIL (native script)
# ============================================================

TAMIL = [
    entry("சென்னையில் 2 BHK பிளாட் வேண்டும்",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "location": {"type": "area_or_city", "query": "Chennai"}},
          "simple_bhk", "ta", "user's own worked example - 'in Chennai, 2 BHK flat needed'"),

    entry("30 ஆயிரத்திற்கு கீழ் 2 BHK பிளாட்",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "price": {"operator": "lte", "value": 30000.0}},
          "price_variant", "ta", "'2 BHK flat under 30 thousand' - ஆயிரம் = thousand"),

    entry("VIT சென்னை அருகில் பிளாட்",
          {"intent": "property_search", "property_type": "apartment",
           "location": {"type": "poi", "query": "VIT Chennai"}},
          "location_poi", "ta", "POI kept in Latin script within the Tamil sentence, as commonly written"),

    entry("பாதி பர்னிஷ் செய்யப்பட்ட 2 BHK",
          {"intent": "property_search", "furnishing": "semi_furnished", "bedrooms": 2.0},
          "simple_furnishing", "ta", "'partially furnished 2 BHK' - தமிழில் furnishing statuses have no fixed native term"),

    entry("வாடகைக்கு வில்லா",
          {"intent": "property_search", "property_type": "villa", "listing_type": "rent"},
          "simple_multi", "ta", "'villa for rent'"),

    entry("ஜிம் அருகில் பிளாட்",
          {"intent": "property_search", "property_type": "apartment",
           "nearby_facilities": [{"category": "gym"}]},
          "nearby_facility", "ta", "'flat near a gym'"),

    entry("மாம்பாக்கம் அருகில் 3 BHK வீடு",
          {"intent": "property_search", "bedrooms": 3.0, "property_type": "independent_house",
           "location": {"type": "poi", "query": "Mambakkam"}},
          "location_poi", "ta", "Mambakkam TRANSLITERATED into Tamil script - the harder POI case"),

    entry("1200 சதுர அடி பிளாட்",
          {"intent": "property_search", "property_type": "apartment",
           "area": {"operator": "eq", "value": 1200.0}},
          "area_variant", "ta", "'1200 square feet flat'"),
]


# ============================================================
# 3. TANGLISH (Tamil-English romanized code-mixing)
# ============================================================

TANGLISH = [
    entry("Chennai la 2 BHK flat venum",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "location": {"type": "area_or_city", "query": "Chennai"}},
          "simple_bhk", "ta-en", "user's own worked example"),

    entry("Chennai la 2 BHK flat venum 30k kulla",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "location": {"type": "area_or_city", "query": "Chennai"},
           "price": {"operator": "lte", "value": 30000.0}},
          "multi_constraint", "ta-en", "user's own worked example - 'kulla' = within/under"),

    entry("VIT Chennai pakkathula flat venum",
          {"intent": "property_search", "property_type": "apartment",
           "location": {"type": "poi", "query": "VIT Chennai"}},
          "location_poi", "ta-en", "'pakkathula' = near"),

    entry("Mambakkam pakkam 3 BHK veedu venum",
          {"intent": "property_search", "bedrooms": 3.0, "property_type": "independent_house",
           "location": {"type": "poi", "query": "Mambakkam"}},
          "location_poi", "ta-en", "'veedu' = house"),

    entry("semi furnished 2 BHK flat Chennai la",
          {"intent": "property_search", "furnishing": "semi_furnished", "bedrooms": 2.0,
           "property_type": "apartment", "location": {"type": "area_or_city", "query": "Chennai"}},
          "multi_constraint", "ta-en"),

    entry("rent ku villa venum",
          {"intent": "property_search", "property_type": "villa", "listing_type": "rent"},
          "simple_multi", "ta-en", "'ku' = for/to"),

    entry("gym pakkathula flat",
          {"intent": "property_search", "property_type": "apartment",
           "nearby_facilities": [{"category": "gym"}]},
          "nearby_facility", "ta-en"),

    entry("30 thousand kulla 2 BHK",
          {"intent": "property_search", "bedrooms": 2.0,
           "price": {"operator": "lte", "value": 30000.0}},
          "price_variant", "ta-en"),

    entry("Tata Homes pakkam flat venum",
          {"intent": "property_search", "property_type": "apartment",
           "location": {"type": "poi", "query": "Tata Homes"}},
          "location_poi", "ta-en"),

    entry("1200 sqft flat Chennai la venum",
          {"intent": "property_search", "property_type": "apartment",
           "location": {"type": "area_or_city", "query": "Chennai"},
           "area": {"operator": "eq", "value": 1200.0}},
          "multi_constraint", "ta-en"),
]


# ============================================================
# 4. HINDI (native script)
# ============================================================

HINDI = [
    entry("चेन्नई में 2 BHK फ्लैट चाहिए",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "location": {"type": "area_or_city", "query": "Chennai"}},
          "simple_bhk", "hi"),

    entry("30 हज़ार के अंदर 2 BHK फ्लैट",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "price": {"operator": "lte", "value": 30000.0}},
          "price_variant", "hi", "हज़ार = thousand"),

    entry("VIT चेन्नई के पास फ्लैट",
          {"intent": "property_search", "property_type": "apartment",
           "location": {"type": "poi", "query": "VIT Chennai"}},
          "location_poi", "hi"),

    entry("अर्ध सुसज्जित 2 BHK",
          {"intent": "property_search", "furnishing": "semi_furnished", "bedrooms": 2.0},
          "simple_furnishing", "hi", "'semi furnished 2 BHK'"),

    entry("किराए के लिए विला",
          {"intent": "property_search", "property_type": "villa", "listing_type": "rent"},
          "simple_multi", "hi", "'villa for rent'"),

    entry("जिम के पास फ्लैट",
          {"intent": "property_search", "property_type": "apartment",
           "nearby_facilities": [{"category": "gym"}]},
          "nearby_facility", "hi"),

    entry("मंबक्कम के पास 3 BHK घर",
          {"intent": "property_search", "bedrooms": 3.0, "property_type": "independent_house",
           "location": {"type": "poi", "query": "Mambakkam"}},
          "location_poi", "hi", "Mambakkam transliterated into Devanagari"),

    entry("1200 वर्ग फुट फ्लैट",
          {"intent": "property_search", "property_type": "apartment",
           "area": {"operator": "eq", "value": 1200.0}},
          "area_variant", "hi"),
]


# ============================================================
# 5. HINGLISH (Hindi-English romanized code-mixing)
# ============================================================

HINGLISH = [
    entry("Chennai mein 30k ke andar 2 BHK flat chahiye",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "location": {"type": "area_or_city", "query": "Chennai"},
           "price": {"operator": "lte", "value": 30000.0}},
          "multi_constraint", "hi-en", "user's own worked example"),

    entry("Chennai mein 2 BHK flat chahiye",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "location": {"type": "area_or_city", "query": "Chennai"}},
          "simple_bhk", "hi-en"),

    entry("VIT Chennai ke paas flat chahiye",
          {"intent": "property_search", "property_type": "apartment",
           "location": {"type": "poi", "query": "VIT Chennai"}},
          "location_poi", "hi-en"),

    entry("Mambakkam ke paas 3 BHK ghar chahiye",
          {"intent": "property_search", "bedrooms": 3.0, "property_type": "independent_house",
           "location": {"type": "poi", "query": "Mambakkam"}},
          "location_poi", "hi-en"),

    entry("semi furnished 2 BHK flat chahiye",
          {"intent": "property_search", "furnishing": "semi_furnished", "bedrooms": 2.0,
           "property_type": "apartment"},
          "simple_furnishing", "hi-en"),

    entry("rent ke liye villa chahiye",
          {"intent": "property_search", "property_type": "villa", "listing_type": "rent"},
          "simple_multi", "hi-en"),

    entry("gym ke paas flat chahiye",
          {"intent": "property_search", "property_type": "apartment",
           "nearby_facilities": [{"category": "gym"}]},
          "nearby_facility", "hi-en"),

    entry("30 hazaar ke andar 2 BHK",
          {"intent": "property_search", "bedrooms": 2.0,
           "price": {"operator": "lte", "value": 30000.0}},
          "price_variant", "hi-en", "user's own worked numeric example - 'hazaar' = thousand"),

    entry("Tata Homes ke paas flat chahiye",
          {"intent": "property_search", "property_type": "apartment",
           "location": {"type": "poi", "query": "Tata Homes"}},
          "location_poi", "hi-en"),

    entry("1200 sqft flat chahiye Chennai mein",
          {"intent": "property_search", "property_type": "apartment",
           "location": {"type": "area_or_city", "query": "Chennai"},
           "area": {"operator": "eq", "value": 1200.0}},
          "multi_constraint", "hi-en"),
]


# ============================================================
# 6. TELUGU (native script)
# ============================================================

TELUGU = [
    entry("చెన్నైలో 2 BHK ఫ్లాట్ కావాలి",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "location": {"type": "area_or_city", "query": "Chennai"}},
          "simple_bhk", "te", "user's own worked example"),

    entry("30 వేలలోపు 2 BHK ఫ్లాట్",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "price": {"operator": "lte", "value": 30000.0}},
          "price_variant", "te", "వేలు = thousand"),

    entry("VIT చెన్నై దగ్గర ఫ్లాట్",
          {"intent": "property_search", "property_type": "apartment",
           "location": {"type": "poi", "query": "VIT Chennai"}},
          "location_poi", "te"),

    entry("సెమీ ఫర్నిష్డ్ 2 BHK",
          {"intent": "property_search", "furnishing": "semi_furnished", "bedrooms": 2.0},
          "simple_furnishing", "te"),

    entry("అద్దెకు విల్లా",
          {"intent": "property_search", "property_type": "villa", "listing_type": "rent"},
          "simple_multi", "te", "'villa for rent'"),

    entry("జిమ్ దగ్గర ఫ్లాట్",
          {"intent": "property_search", "property_type": "apartment",
           "nearby_facilities": [{"category": "gym"}]},
          "nearby_facility", "te"),

    entry("మాంబాక్కం దగ్గర 3 BHK ఇల్లు",
          {"intent": "property_search", "bedrooms": 3.0, "property_type": "independent_house",
           "location": {"type": "poi", "query": "Mambakkam"}},
          "location_poi", "te", "Mambakkam transliterated into Telugu script"),

    entry("1200 చదరపు అడుగుల ఫ్లాట్",
          {"intent": "property_search", "property_type": "apartment",
           "area": {"operator": "eq", "value": 1200.0}},
          "area_variant", "te"),
]


# ============================================================
# 7. TELUGU-ENGLISH (romanized code-mixing)
# ============================================================

TELUGU_ENGLISH = [
    entry("Chennai lo 30k lopala 2 BHK flat kavali",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "location": {"type": "area_or_city", "query": "Chennai"},
           "price": {"operator": "lte", "value": 30000.0}},
          "multi_constraint", "te-en", "user's own worked example - 'lopala' = within/under"),

    entry("Chennai lo 2 BHK flat kavali",
          {"intent": "property_search", "bedrooms": 2.0, "property_type": "apartment",
           "location": {"type": "area_or_city", "query": "Chennai"}},
          "simple_bhk", "te-en"),

    entry("VIT Chennai daggara flat kavali",
          {"intent": "property_search", "property_type": "apartment",
           "location": {"type": "poi", "query": "VIT Chennai"}},
          "location_poi", "te-en", "'daggara' = near"),

    entry("Mambakkam daggara 3 BHK illu kavali",
          {"intent": "property_search", "bedrooms": 3.0, "property_type": "independent_house",
           "location": {"type": "poi", "query": "Mambakkam"}},
          "location_poi", "te-en", "'illu' = house"),

    entry("semi furnished 2 BHK flat kavali",
          {"intent": "property_search", "furnishing": "semi_furnished", "bedrooms": 2.0,
           "property_type": "apartment"},
          "simple_furnishing", "te-en"),

    entry("rent ki villa kavali",
          {"intent": "property_search", "property_type": "villa", "listing_type": "rent"},
          "simple_multi", "te-en"),

    entry("gym daggara flat kavali",
          {"intent": "property_search", "property_type": "apartment",
           "nearby_facilities": [{"category": "gym"}]},
          "nearby_facility", "te-en"),

    entry("30 vela lopala 2 BHK",
          {"intent": "property_search", "bedrooms": 2.0,
           "price": {"operator": "lte", "value": 30000.0}},
          "price_variant", "te-en", "user's own worked numeric example - 'vela' = thousand"),

    entry("Tata Homes daggara flat kavali",
          {"intent": "property_search", "property_type": "apartment",
           "location": {"type": "poi", "query": "Tata Homes"}},
          "location_poi", "te-en"),

    entry("1200 sqft flat kavali Chennai lo",
          {"intent": "property_search", "property_type": "apartment",
           "location": {"type": "area_or_city", "query": "Chennai"},
           "area": {"operator": "eq", "value": 1200.0}},
          "multi_constraint", "te-en"),
]


# ============================================================
# 8. DEDICATED NUMERIC-PRESERVATION TESTS (Step E)
#
# Isolated numeric fragments (not full sentences) - the point is
# specifically whether the NUMBER survives translation with its correct
# magnitude, not whether the sentence is grammatical.
# ============================================================

NUMERIC_TESTS = [
    entry("20k flat", {"intent": "property_search", "price": {"operator": "eq", "value": 20000.0}},
          "numeric_unit", "en", "control - bare digit+k"),
    entry("30k flat", {"intent": "property_search", "price": {"operator": "eq", "value": 30000.0}},
          "numeric_unit", "en"),
    entry("50k flat", {"intent": "property_search", "price": {"operator": "eq", "value": 50000.0}},
          "numeric_unit", "en"),
    entry("30 thousand rupees flat",
          {"intent": "property_search", "price": {"operator": "eq", "value": 30000.0}},
          "numeric_unit", "en", "control - spelled-out English unit"),
    entry("30 hazaar wala flat",
          {"intent": "property_search", "price": {"operator": "eq", "value": 30000.0}},
          "numeric_unit", "hi-en", "hazaar = thousand"),
    entry("30 ஆயிரம் ரூபாய் பிளாட்",
          {"intent": "property_search", "price": {"operator": "eq", "value": 30000.0}},
          "numeric_unit", "ta", "ஆயிரம் = thousand"),
    entry("30 వేలు రూపాయలు ఫ్లాట్",
          {"intent": "property_search", "price": {"operator": "eq", "value": 30000.0}},
          "numeric_unit", "te", "వేలు = thousand"),
    entry("50 lakh flat", {"intent": "property_search", "price": {"operator": "eq", "value": 5000000.0}},
          "numeric_unit", "en", "lakh already Latin-script in most code-mixed usage"),
    entry("1.5 crore villa",
          {"intent": "property_search", "property_type": "villa", "price": {"operator": "eq", "value": 15000000.0}},
          "numeric_unit", "en"),
    entry("1200 square feet flat",
          {"intent": "property_search", "area": {"operator": "eq", "value": 1200.0}},
          "numeric_unit", "en", "spelled-out area unit, not 'sqft'"),
]


# ============================================================
# 9. DEDICATED POI-PRESERVATION TESTS (Step D)
#
# Explicit, varied-script coverage of the exact POI names named in the
# task, beyond the one-per-language-section coverage above.
# ============================================================

POI_TESTS = [
    entry("VIT Chennai அருகில் பிளாட் வேண்டும்",
          {"intent": "property_search", "location": {"type": "poi", "query": "VIT Chennai"}},
          "location_poi", "ta", "POI name in Latin script embedded in a Tamil sentence"),
    entry("SRM University pakkam flat venum",
          {"intent": "property_search", "location": {"type": "poi", "query": "SRM University"}},
          "location_poi", "ta-en"),
    entry("ரயில் நிலையம் அருகில் பிளாட்",
          {"intent": "property_search", "nearby_facilities": [{"category": "railway_station"}]},
          "nearby_facility", "ta", "'railway station' fully in Tamil, not a proper noun - தமிழில் generic facility term"),
    entry("hospital ke paas flat",
          {"intent": "property_search", "nearby_facilities": [{"category": "hospital"}]},
          "nearby_facility", "hi-en"),
    entry("mall daggara flat kavali",
          {"intent": "property_search", "nearby_facilities": [{"category": "shopping_mall"}]},
          "nearby_facility", "te-en"),
    entry("Tata Homes అపార్ట్మెంట్ కావాలి",
          {"intent": "property_search", "location": {"type": "poi", "query": "Tata Homes"}},
          "location_poi", "te", "POI in Latin script embedded in a Telugu sentence"),
    entry("Mambakkam mein flat chahiye",
          {"intent": "property_search", "location": {"type": "poi", "query": "Mambakkam"}},
          "location_poi", "hi-en", "'mein' here reads as bare area/city framing, not 'near' - deliberately ambiguous poi/area_or_city case"),
    entry("SRM க்கு அருகில் பிளாட்",
          {"intent": "property_search", "location": {"type": "poi", "query": "SRM"}},
          "location_poi", "ta", "short POI abbreviation stress-test"),
]


def build():
    dataset = (
        ENGLISH_CONTROL + TAMIL + TANGLISH + HINDI + HINGLISH + TELUGU +
        TELUGU_ENGLISH + NUMERIC_TESTS + POI_TESTS
    )
    for i, item in enumerate(dataset):
        item["id"] = i

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(dataset, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Wrote {len(dataset)} queries to {OUT_PATH}")

    by_lang = {}
    for item in dataset:
        by_lang[item["language"]] = by_lang.get(item["language"], 0) + 1
    for lang in sorted(by_lang):
        print(f"  {lang:6s} {by_lang[lang]}")


if __name__ == "__main__":
    build()
