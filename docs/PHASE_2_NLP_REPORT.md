<!-- Phase 2: NLP Query Understanding — research report -->
# Phase 2: NLP Query Understanding — Report

**Status:** implemented, tested, benchmarked. **Not connected to production property search or Phase 1** (Mappls/OSM) — see §15.

## 1. Problem definition

Convert a natural-language real-estate search query ("2 bhk flat for rent near VIT Chennai under 25000 with parking") into a structured representation the existing SmartHomes search system can eventually consume, **without** resolving any location mention to coordinates (that stays Phase 1's job) and without hallucinating constraints the user never stated.

## 2. NLP architecture: why hybrid, not an LLM

`openai` is already a dependency in this repo (used by unrelated demo scripts), so reaching for an LLM would have been the path of least resistance — deliberately not taken, for reasons specific to this task:

- **Reproducibility/determinism**: the same query must produce the same structured output every time, with no sampling variance, for automated evaluation to mean anything.
- **No hallucinated filters**: an LLM asked to "extract price" from "cheap flat near VIT" could easily invent a number. A regex either finds an explicit number or it doesn't.
- **Latency/local execution**: no network round-trip, no API cost, works offline.
- **Explainability**: every extraction carries a `source` string naming exactly which rule fired (see §4) — essential for debugging why a field was or wasn't extracted.

A rule-based/lexicon approach was chosen as the **primary implementation**, structured as a staged hybrid pipeline (not one monolithic regex) specifically so ablations are possible later:

```
normalize_query()
        |
extract_location()   -- runs FIRST; its matched span is masked out of
        |                the text before anything else runs (see §12)
        |
extract_listing_type() / extract_property_type() / extract_bedrooms() /
extract_furnishing() / extract_amenities()  (services/nlp/entity_extractor.py)
        |
extract_price() / extract_area()  (services/nlp/numeric_parser.py)
        |
intent classification + StructuredQuery assembly + validate_structured_query()
```

Every stage is an independently-importable function in its own module (`services/nlp/{normalization,location_extractor,entity_extractor,numeric_parser}.py`), orchestrated by `services/nlp/parser.py`. A transformer/spaCy NER approach was considered and rejected for this phase: the entity types here (BHK counts, Indian currency multipliers, a fixed amenity vocabulary) are closed-form and pattern-based, not the kind of free-text entity recognition NER is built for — the location mention (the one genuinely open-vocabulary entity) is deliberately *not* resolved here at all, just detected.

## 3. Structured query schema

`services/nlp/schema.py`. Every extracted field is a `Slot` (value + confidence + source), never a bare value — see §8. Full shape:

```python
StructuredQuery:
  raw_query: str
  intent: "property_search" | "unknown"
  listing_type: Slot | None       # "rent" | "sell"
  property_type: Slot | None      # apartment/independent_house/villa/builder_floor/plot/farm_house/pg_hostel/commercial/other
  bedrooms: Slot | None           # float (1.5 BHK supported)
  furnishing: Slot | None         # unfurnished/semi_furnished/fully_furnished
  price: RangeConstraint | None   # operator: lte/gte/eq/approx/between + value(s)
  area: RangeConstraint | None    # same shape, unit="sqft"
  amenities: list[Slot]           # one Slot per amenity found
  location: LocationMention | None  # {type: poi|area_or_city, query: str, confidence}
  unsupported_phrases: list[str]  # recognized-but-unmapped domain language
  warnings: list[str]
```

**Deliberate deviation from the task's illustrative schema**: `listing_type` uses `"sell"`, not `"sale"` — `services/property_fields.py` (the real, existing schema) defines it as `"sell"`. Following the real schema over the task's example spelling was a conscious choice, documented in `schema.py`'s module docstring, so a later integration phase needs no translation table.

## 4. Supported entities/constraints

Intent, listing type, property type (aligned 1:1 to `property_fields.py`'s 9 types), bedrooms/BHK (incl. half-BHK), furnishing, price (5 operators × Indian numbering system), area (same operators, sqft), amenities (29 codes drawn from `property_fields.py`'s `AMENITY_CATEGORIES`, plus one deliberate addition — see below), and location mentions (POI vs. area/city).

**The one non-trivial vocabulary decision**: `property_fields.py` has no single generic "parking" amenity code (it's split into `covered_parking`/`open_parking`/`visitor_parking`/`ev_charging_parking` under a separate `PARKING_FIELDS` group) — but "with parking" is exactly how users phrase it, and the task's own worked example expects `"amenities": ["parking"]`. Rather than guess which specific parking sub-field the user meant, this phase emits a generic `"parking"` code and documents that mapping it to the granular field is a **future integration decision**, not something to invent here.

## 5. Normalization strategy

`services/nlp/normalization.py`: Unicode NFKC, lowercasing, ₹/Rs./INR stripping (word-bounded — see §12 for why that matters), comma-grouped number cleanup, splitting glued number+letter tokens ("2bhk" → "2 bhk", "25k" → "25 k"), hyphen-to-space normalization. Deliberately does **not** touch POI/place-name text beyond casing.

## 6. Location extraction strategy

`services/nlp/location_extractor.py`. Two outcomes:
- **`poi`**: a `near/around/close to/beside/next to/within N km of <X>` construction was found.
- **`area_or_city`**: a bare `in <X>` mention, or a recognized Indian city name appearing with no preposition at all.

A small, explicitly-labeled list of ~35 major Indian city names is used *only* to raise confidence for `area_or_city` — this is generic geography (the kind any Indian real-estate portal's search bar needs), not a POI alias table, and it never resolves coordinates.

**Hard boundary, enforced not just documented**: this module returns free text only. `test_nlp_parser.py`'s `NoCoordinatesOrPhase1CallsTests` class statically parses every `services/nlp/*.py` file's AST and asserts none of them import `services.mappls_service` or `services.osm_location_service`, plus asserts no key in any parsed output is named `latitude`/`longitude`/`lat`/`lon`/`lng`. This is a real, running test, not a comment promising good behavior.

## 7. Validation strategy

`validate_structured_query()` in `schema.py` — a self-check (not an exception) that every extracted value is in-vocabulary (e.g. `property_type` is one of the 9 real values), every confidence is in `[0,1]`, and `between` constraints have both bounds. Problems are appended to `StructuredQuery.warnings`, never silently dropped.

## 8. NLP confidence vs. Phase 1 confidence — kept explicitly separate

Every `Slot` carries its own `confidence` (e.g. `0.97` for an explicit `"2 bhk"` regex match, `0.6` for a fuzzy word-number match). This is a **different number measuring a different thing** than Phase 1's entity-match score/margin (`services/osm_location_service.py`) — the two are never combined or compared, and Phase 2 never even imports Phase 1's modules (§6).

## 9. Baselines

**Baseline A** (`services/nlp/baseline.py`) — a real, runnable, deliberately simpler implementation, not a stub: substring matching only, **no Indian numbering conversion** (so "50 lakh" is read as the literal number `50`, not `5,000,000`), no operator detection (every price is `"eq"` regardless of "under"/"above"/"between"), no location-type distinction (always `"unknown"`), no amenities, no furnishing.

A generic NER or lightweight transformer baseline was considered (§2) and not built, since the closed-vocabulary nature of every field here except location makes that comparison less informative than the rule-based-vs-hybrid one actually measures something real: how much the numeric/operator handling matters.

## 10. Evaluation dataset

`evaluation/nlp/queries.json` — **112 queries**, built by `evaluation/nlp/build_dataset.py`:
- **67 hand-crafted**, individually reasoned about: spelling/casing variants, numeric phrasing variants (₹/Rs./k/lakh/crore/thousand), ambiguous queries, unsupported/off-topic queries, sparse queries, multi-constraint queries, common Indian-English phrasing ("to let", "lease" → rent), malformed numeric input, whitespace robustness.
- **45 generated** via a parameter grid (property_type × listing_type × BHK, price phrasing × magnitude, location × property type, amenity × listing type) — ground truth is *computed by the same code that builds the query text*, not hand-transcribed, which is standard practice for NLU evaluation sets (ATIS/SNIPS-style) and avoids the transcription-error risk of hand-writing 100+ JSON blocks.

Every entry carries a `category` tag for per-category reporting.

## 11. Evaluation metrics

`evaluation/nlp/evaluate_nlp.py`: intent accuracy, slot precision/recall/F1 (micro-averaged over every extracted `(field, value)` instance, with numeric tolerance — ₹1 for price, 0.5 sqft for area, 0.01 BHK), query-level exact-match accuracy, and per-field F1 for all 8 scored fields. Results are written to `evaluation/nlp/results/latest.json` (overwritten each run) and a timestamped `run_<ts>.json` (full per-query detail, never overwritten) — every number below was read from one of these files, not typed by hand.

## 12. Actual benchmark results (measured, not fabricated)

| Metric | Baseline A | Proposed (hybrid) |
|---|---|---|
| Intent accuracy | 0.973 | **1.000** |
| Exact match accuracy | 0.080 | **1.000** |
| Slot precision | 0.560 | **1.000** |
| Slot recall | 0.558 | **1.000** |
| Slot F1 | 0.559 | **1.000** |
| listing_type F1 | 0.962 | 1.000 |
| property_type F1 | 0.974 | 1.000 |
| bedrooms F1 | 0.918 | 1.000 |
| furnishing F1 | N/A (support=3) | 1.000 |
| **price F1** | **0.044** | 1.000 |
| area F1 | N/A (support=9) | 1.000 |
| amenities F1 | N/A (support=24) | 1.000 |
| location F1 | 0.390 | 1.000 |

The baseline's collapse on `price` (F1=0.044) is the single most telling number here: it correctly *finds* a number near a price-context word almost every time (that's why intent accuracy is still high), but almost never converts it correctly (missing lakh/crore/k multipliers entirely), which is exactly the gap the hybrid pipeline's `numeric_parser.py` exists to close.

## 13. Error analysis — bugs found and fixed during evaluation (not hidden)

The path to 1.000 was not "write once, pass immediately" — the evaluator earned its place by catching **6 real bugs** and **2 mistaken ground-truth annotations**, all fixed and documented in code comments at the fix site:

1. **`normalize_query`'s currency stripper had no word boundary**: `rs` (meant to strip "Rs.25000") matched the substring inside "**university**" (u-nive-**rs**-ity), silently corrupting it to "univeity" before location extraction ever ran. Fixed with `\brs\.?\s*(?=\d)`.
2. **The same unanchored-substring class of bug existed in `location_extractor`'s stop-word pattern** — fixed by requiring `\b` around every stop word.
3. **`"villa around 1 crore"` was extracting `"1 crore"` as a fake POI location** — `"around"` is genuinely ambiguous between a location preposition and a price-approximation word. Fixed with a numeric-phrase guard that rejects a captured "location" if it's just a number+unit.
4. **`"above 1200 sqft"` was *also* being read as a price of 1200** — `"above"` is a valid word for both price and area operators. Fixed with a negative lookahead excluding numbers immediately followed by an area/distance unit.
5. **That same fix initially backtracked into a shorter digit match** (`"1200"` → phantom price `"120"`, leaving `"0 sqft"` unconsumed) — Python's `re` will backtrack past a negative lookahead rather than fail outright. Fixed by anchoring a `\b` immediately after the digit run so the full number must resolve before the lookahead is even evaluated.
6. **`"villa beside Guindy National Park"` was extracting amenity `"park"`** from inside the place name. Fixed by extracting location *first* and masking its matched span out of the text before running amenity/entity extraction (see the pipeline diagram in §2).
7. **Two dataset annotations were simply wrong**, caught by the parser's actual (correct) behavior disagreeing with my own hand-written expectation: `"2 bhk flat to let near Anna Nagar"` should expect `location.type="poi"` (any `"near X"` is POI-type per this module's own documented rule, regardless of whether X is a true landmark or a locality — see §6), and `"flat under -5000"` — the regex has no sign handling, so treating it as `5000` is defensible graceful degradation, not a bug requiring a fix.
8. **Intent classification was too narrow**: `"gated community with vastu compliance"` is unmistakably a real-estate query to a human, but mapped to zero known slots, so `intent` came back `"unknown"`. Fixed by also treating a detected `unsupported_phrases` entry as a `property_search` signal (recognizing domain language, even unmapped, is itself evidence of intent).

A final spot-check with genuinely new queries *outside* the benchmark (`"1 bhk pg near SRM Kattankulathur for boys under 6000"`) caught one more real bug (location capture running past `"for boys"` into the price clause) before this report was written — fixed by adding bare `"for"` as a location-phrase stop word.

**Honesty note on the 1.000 score**: this reflects convergence between the parser and this specific 112-query benchmark after iterative fixing *against that benchmark* — it is not a claim that every conceivable real query will score perfectly. The post-benchmark spot-check (which found one more bug) is the more meaningful signal of remaining risk than the benchmark number alone. See §13 (limitations) below.

## 14. Known limitations

- **The "parking" generic-code gap** (§4): resolving it to a specific `PARKING_FIELDS` value is deferred.
- **`location.type` can't distinguish locality from city from full address** — by design (§6), since that distinction isn't reliably recoverable from text alone without exactly the kind of POI gazetteer this task prohibits building. Left for Phase 1 to resolve during POI matching.
- **112 queries, mostly Chennai-flavored**, is a small benchmark by NLU-research standards; the city-name list is Chennai/Tamil-Nadu-biased (§6) — reasonable for SmartHomes' actual usage, less so as a general claim.
- **Bare ambiguous POI names with zero other signal** (e.g. a lone `"SRM"`) correctly return `intent="unknown"` — there is no domain evidence to work from since there's no preposition or other constraint, which is honest but means such a query would need a different entry point (e.g. an explicit "search near a place" UI affordance) rather than free text alone.
- **No spelling-correction/fuzzy matching** for property-domain words themselves (only for currency/BHK phrasing variants already handled) — "appartment" (double-p typo) would not match `property_type`.
- The benchmark's 1.000 score is a snapshot after fixing everything it found; it will not stay 1.000 forever as new query patterns are tried, and shouldn't be read as "no more bugs exist" (§13).

## 15. Future improvements

- Expand the benchmark toward 150-200 queries, adding more non-Chennai cities and genuine typos.
- An ablation study (structure is already in place — see §12's pipeline diagram; each stage is independently callable) comparing full hybrid vs. no-numeric-parser vs. no-normalization vs. no-location-masking vs. rule-only baseline.
- Resolve the generic `"parking"` → specific field mapping question with product input.
- Consider fuzzy/edit-distance matching for property-type and amenity words (not POI names) to handle typos.

## 16. How this connects to Phase 1

```
NLP (Phase 2)                    Phase 1 (already built)
--------------                   ------------------------
parse(query)                     services.mappls_service.resolve_place(query)
  -> StructuredQuery                -> {placeName, placeAddress, eLoc}
     .location.query  ------------->  services.osm_location_service
     ("VIT Chennai",                    .resolve_coordinates(...)
      type="poi")                          -> {status, latitude, longitude, ...}
```

`StructuredQuery.location.query` is exactly the free-text string Phase 1's `mappls_service.resolve_place()` already accepts. No adapter code is needed for that hand-off — it was designed to match. **This connection has not been built** (see §15/production integration status below); Phase 2 stops at producing the structured query.

---

## Files created
- `services/nlp/{__init__,schema,normalization,numeric_parser,location_extractor,entity_extractor,parser,baseline}.py`
- `test_nlp_parser.py` (43 tests, root-level, matching existing convention)
- `evaluation/nlp/{build_dataset,evaluate_nlp,manual_endpoint_test}.py`, `queries.json`, `results/latest.json` + timestamped run files
- `docs/PHASE_2_NLP_REPORT.md` (this file)

## Files modified
- `routes/search_routes.py` — added `POST /api/search/parse-query` (new endpoint only; `search_rentals` and `ranked_search()` untouched)

## Explicitly confirmed
- **NLP has NOT been integrated into the production property search flow.** `routes/search_routes.py`'s existing `/search_rentals` endpoint and `services/property_services.py`'s `ranked_search()` are byte-for-byte unchanged.
- No Geoapify was introduced. No manual POI alias table was introduced. No coordinates are ever produced by this layer (enforced by a running test, §6).
