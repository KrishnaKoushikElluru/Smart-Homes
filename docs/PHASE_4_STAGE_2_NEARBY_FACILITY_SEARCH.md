<!-- Phase 4, Stage 2: Nearby-Facility Natural-Language Search — implementation report -->
# Phase 4, Stage 2: Nearby-Facility Natural-Language Search — Report

**Status:** complete. The existing NL search (Phase 2/2.5/3/3.2) now also understands "near a gym" / "within 1 km of a hospital" style requirements and matches them against Stage 1's stored `nearby_facilities` data — with zero live Mappls calls per search.

## 1. The core distinction (requirement, preserved exactly)

| Phrase | Meaning | Where it's stored | Where it's matched |
|---|---|---|---|
| "flat **with** a gym" | the property itself has a gym | `property.features` (Phase 2 amenity extraction, unchanged) | `entity_extractor.py` (unchanged) |
| "flat **near** a gym" / "gym **nearby**" | a gym exists near the property | `nearby_facilities[]` (Stage 1 enrichment) | new `nearby_facility_extractor.py` |

A bare facility noun with no proximity wrapper ("gym", "hospital") is **never** treated as a nearby-facility mention — see `test_nearby_facility_extractor.py::BareFacilityWordTests`.

## 2. NLP extension (2A) — `services/nlp/nearby_facility_extractor.py` (new)

A new, small, deterministic extraction stage — regex only, no ML, no embeddings. Runs **before** location extraction in the pipeline (`services/nlp/parser.py::_parse_configured()`), because a proximity phrase like "near VIT Chennai" and "near a gym" share the word "near"; extracting facility mentions first and masking their matched span out of the text prevents the location extractor from ever seeing (and mis-claiming) a facility phrase, and vice versa. This is the same masking-order pattern Phase 2 already used between its own stages (see the "Guindy National Park" fix), applied one stage earlier.

```
normalize
   |
   v
extract_nearby_facilities()   <- NEW, first
   |  (masks its own matched spans)
   v
extract_location()            <- unchanged function, now sees pre-masked text
   |  (masks its own matched span)
   v
extract_entities() / extract_numeric_constraints()   <- unchanged, now see pre-masked text
```

`StructuredQuery` gained one new field: `nearby_facilities: List[NearbyFacilityRequirement]` (`services/nlp/schema.py`), each with `category`, `radius_m` (nullable), `raw_text`, `confidence`. Backward compatible: existing queries with no nearby-facility mention simply get `nearby_facilities=[]`, and every existing field is untouched.

**Deliberate taxonomy duplication.** `nearby_facility_extractor.py` and `schema.py` declare their own 17-category `NEARBY_FACILITY_CATEGORIES` set rather than importing it from `services/nearby_facility_service.py`. This preserves the architectural boundary `test_nlp_parser.py` already enforces (AST/`sys.modules`-based tests asserting `services/nlp/` never transitively imports Mappls/OSM-calling code) — `services/nlp/` must stay callable with zero network dependencies. `test_nearby_facility_extractor.py::TaxonomyConsistencyTests` is the drift check: it imports the real `nearby_facility_service.FACILITY_CATEGORIES` and asserts the two sets are equal, so a category added to one side without the other fails a test immediately instead of silently drifting.

**Worked examples (all verified against the real parser, not just unit-mocked):**

| Query | Result |
|---|---|
| `"flat with a gym"` | amenity=gym, `nearby_facilities=[]` |
| `"flat near a gym"` | `nearby_facilities=[{category: gym, radius_m: null}]`, no amenity |
| `"flat near VIT Chennai with a gym nearby"` | `location.query="VIT Chennai"` **and** `nearby_facilities=[gym]` — both preserved simultaneously |
| `"2 BHK near hospital within 1 km"` | `nearby_facilities=[{category: hospital, radius_m: 1000.0}]` |

## 3. Search-orchestration extension (2B) — `services/search_orchestration.py`

`merge_structured_fields()` copies `StructuredQuery.nearby_facilities` into `merged["nearby_facility_requirements"]` (list of `{category, radius_m}`). `build_mongo_filter()` turns each requirement into its own `$elemMatch` clause, combined with `$and` (a single `$elemMatch` cannot require two different array elements at once, e.g. both a gym *and* a hospital within range):

```python
{"nearby_facilities": {"$elemMatch": {"category": "gym", "distance_m": {"$lte": 1000}}}}
```

This queries Stage 1's **already-stored** `nearby_facilities` array — `orchestrate_search()` makes zero Mappls/OSM calls for a nearby-facility requirement. The only network calls a search makes are the pre-existing Phase 3 POI-resolution ones (resolving a *primary location* mention like "VIT Chennai" — unchanged, unrelated to facility search). `distance_m` compared here is the Mappls-provided straight-line distance stored during Stage 1 enrichment — **not** driving/walking distance or travel time, and no routing engine (OSRM/Valhalla/etc.) was introduced, per the task's explicit exclusion list.

**Enrichment-readiness caveat.** A property with no `nearby_facilities_metadata` yet, or `status` in `{pending, failed, skipped}`, cannot be truthfully said to lack a gym — it simply hasn't been checked. `_nearby_facility_enrichment_caveat()` counts such active listings whenever a search includes a nearby-facility requirement, and `orchestrate_search()` returns it as `nearby_facility_enrichment_caveat: {unenriched_active_listings, note}` (present, with `note: null`, when the count is 0; the frontend only renders a banner when `note` is truthy). This is returned from **every** branch of `orchestrate_search()` (explicit-coordinates, POI-not-matched, POI-matched, no-POI), so the caveat is never silently dropped depending on which resolution path a query took.

**Phase 3.2's ambiguous-location picker keeps working unmodified.** When a POI mention is ambiguous, `orchestrate_search()` still returns `location_resolution.status="ambiguous"` with `alternates`, exactly as before — but now `applied_filters.nearby_facilities` is already populated from the parsed query, so a gym requirement is never silently dropped while the user is picking a location. Verified live: `"flat near VIT Chennai with a gym nearby"` → ambiguous, gym requirement present in `applied_filters`, `properties=[]`. Re-running with the frontend's picked coordinates (`location_lat`/`location_lon`, Phase 3.2's existing explicit-coordinates mechanism) → `status="matched"`, gym requirement **still** present, 2 real properties returned (matching both the POI radius and the stored gym).

## 4. API surface (2D groundwork) — `routes/search_routes.py`

- Response JSON gained `nearby_facility_enrichment_caveat` (passthrough of the orchestration result).
- `_serialize_property()` gained a trimmed `nearby_facilities` field: only `category`, `name`, `distance_m` per entry — deliberately excluding `provider_id`, `coordinates`, `fetched_at` (internal-only fields from Stage 1's stored documents), so the frontend result-explanation UI can show "Gym 650 m away" using only real, already-computed data.

## 5. Frontend (2D/2E) — `templates/rentals.html`

No change to the manual-filter form or the "OR USE FILTERS" divider. All additions are inside the existing NL search script block (verified with `node --check` after every edit) and are purely additive:

- **Understood-filter chips** (`buildUnderstoodFiltersChips()`): a nearby-facility requirement renders as its own chip, worded and colored distinctly from a property-amenity chip — e.g. `🏋 Gym within 1 km` / `🏥 Hospital Nearby` (green, `.nlp-chip-facility`) vs. a plain `Gym` amenity chip (blue, `.nlp-chip`). Never renders bare `"Gym"` for a nearby-facility match.
- **Enrichment caveat banner** (`renderNlpFeedback()`): renders `nearby_facility_enrichment_caveat.note` as an info banner whenever the backend reports unenriched active listings for the query — reusing the existing `.nlp-message-info` style already used elsewhere in Phase 3.1.
- **Result explanation** (`buildNearbyFacilityExplanationHTML()`, called from `buildPropertyCardElement()`): for each requested nearby-facility category, looks up that property's own matching entry in the newly-serialized `property.nearby_facilities` array and renders `✓ Gym 781 m away` using **only** the real `distance_m` value returned by the backend — never an estimated or fabricated one; a category with no matching entry on a given property is simply omitted, not guessed at.
- `renderPropertyResults(properties, nearbyFacilityCategories)` and `buildPropertyCardElement(property, nearbyFacilityCategories)` both take the new parameter as optional, defaulting to `[]`. The manual-filter search path (`searchRentals()`) calls `renderPropertyResults(data.properties)` with no second argument — byte-identical behavior to before Stage 2.

**Live browser verification** (real dev server, real MongoDB, real stored Stage 1 enrichment data, logged in as an existing dev user):

- `"2 bhk flat near a gym within 1 km in Chennai"` → chip `🏋 Gym within 1 km` (green/facility-styled), enrichment caveat banner shown (3 unenriched active listings correctly reported), 2 real properties returned, each showing `✓ Gym 781 m away` (a real stored distance, confirmed against the actual `nearby_facilities` document).
- `"2 bhk flat with a gym in Chennai"` (property amenity, not nearby) → chip renders as plain `Gym` (blue, non-facility-styled), **no** enrichment caveat (correctly, since no nearby-facility requirement was parsed), `"No properties found matching your criteria."` (correct: no test property has a stored `gym` amenity feature) — confirming the amenity and nearby-facility paths stay fully independent.
- No console errors in either run.

## 6. Tests (2F)

272 tests pass across the full suite (`python -m pytest -q test_*.py`; the two pre-existing manual/live-network scratch scripts under `osm_test/` and `geo_coordinate_benchmark/` are excluded, as they were before Stage 2 — they are standalone scripts, not part of the suite, and make live external calls at import time).

| File | Tests | Covers |
|---|---|---|
| `test_nearby_facility_extractor.py` (new) | 29 | taxonomy drift, bare-word exclusion, proximity wrappers, radius parsing/units, multi-facility, category vocabulary |
| `test_nlp_parser.py` | 46 (+2 vs. pre-Stage-2) | nearby-facility module added to the NLP-boundary import check; new test asserting nearby-facility output never leaks coordinates |
| `test_search_orchestration.py` | 55 (+19) | `merge_structured_fields`/`build_mongo_filter` nearby-facility handling, enrichment-caveat computation, full `orchestrate_search()` flows including VIT-Chennai-ambiguous-then-picked-with-gym-preserved |
| `test_search_routes_integration.py` | 21 (+3) | nearby-gym response shape, amenity-only query produces no caveat, trimmed `nearby_facilities` present in serialized results |
| (Stage 1 files, unchanged this stage) | 121 | `test_property_services.py` (6), `test_nearby_facility_service.py` (40), remaining pre-existing suites |

Explicit cross-check against the task's 14 named scenarios:

1. Property amenity ("with a gym") — `test_nlp_parser`/`test_search_orchestration` amenity-path tests; live-verified above.
2. Nearby gym ("near a gym") — `ProximityWrapperTests`; live-verified above.
3. Nearby hospital — `ProximityWrapperTests::test_close_to_a_hospital`.
4. Radius constraint ("within 1 km") — `RadiusExtractionTests`; live-verified above.
5. Multiple nearby-facility requirements — `MultipleFacilitiesTests`, `BuildMongoFilterNearbyFacilitiesTests` (multi-category `$and`).
6. Nearby facility + price — `BuildMongoFilterNearbyFacilitiesTests` (combination case).
7. + furnishing — same test class, combination case.
8. + BHK — same test class, combination case.
9. VIT Chennai + nearby gym — `OrchestrateSearchNearbyFacilityTests::test_vit_chennai_matched_plus_nearby_gym_together`; live-verified above.
10. Ambiguous POI + nearby facility — `test_ambiguous_poi_does_not_discard_the_nearby_facility_requirement`; live-verified above.
11. Enrichment pending — `NearbyFacilityEnrichmentCaveatTests`; live-verified (caveat banner shown).
12. Enrichment failed — same caveat mechanism (status is one of `pending`/`failed`/`skipped`, all counted identically as "not yet checked").
13. No nearby facility for a property — `buildNearbyFacilityExplanationHTML()`'s lookup simply omits a category with no match; covered implicitly (no test property lacking all facilities was asserted separately, since the caveat/omission logic is category-per-property and already exercised by the "amenity, not nearby" live run returning zero matches).
14. Existing queries unchanged — the full pre-Stage-2 suite (all Phase 2/2.5/3/3.2 tests) still passes unmodified; `renderPropertyResults`'s manual-search call site is unchanged (single-argument call).

## 7. Known limitation (pre-existing, not introduced or fixed this stage)

While live-testing a query shaped like the task's own worked example — `"a flat near VIT Chennai, it should be semi furnished, Chennai"` — a **pre-existing** bug in `location_extractor.py` (Phase 1/2, untouched by Stage 2) was found: `location_extractor.py`'s `_STOP_WORDS` list does not treat a comma as a phrase boundary, so a POI capture can over-extend past an intended clause break, e.g. `location.query` becomes `"VIT Chennai, it should be semi"` instead of `"VIT Chennai"`. This corrupts the remaining text handed to the furnishing extractor, which then falls back to a lower-confidence bare match. This is **orthogonal** to nearby-facility search — it affects any multi-clause, comma-separated query regardless of whether a nearby-facility mention is present — and reproduces identically with the gym clause removed. Per this task's explicit "do not rewrite the existing NLP parser" instruction, it was **not** fixed; it is disclosed here as a known limitation. A query phrased without the comma (e.g. `"a flat near VIT Chennai with a gym nearby, semi furnished, Chennai"` restructured, or simply omitting the comma before "it should be") is unaffected.

## 8. What was explicitly NOT introduced (per task instruction)

No pretrained NLP model, no embeddings, no vector database, no LLM-based parsing, no road routing (OSRM/Valhalla), no walking/driving distance or travel time, no recommendation/ranking layer, no Geoapify, no manual POI alias table, no LLM-generated coordinates, no relaxed POI-ambiguity thresholds. `nearby_facility_extractor.py` is pure regex; `distance_m` is Mappls' own straight-line value stored in Stage 1, never derived from a routing call.
