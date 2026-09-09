<!-- Phase 3: Natural-Language Search Integration — implementation report -->
# Phase 3: Natural-Language Search Integration — Report

**Status:** complete. Wires the existing Phase 2 NLP parser and Phase 1 POI resolver into `/search_rentals`, additively. The pre-existing structured search path is unchanged and unaffected.

## 1. Previous architecture

```
templates/rentals.html search form
        |
        v
POST /search_rentals  (routes/search_routes.py)
        |
        v
flat preferences dict {budget, city, locality, listing_type, property_type, bhk}
        |
        v
PropertyService.ranked_search(preferences)   (services/property_services.py)
        |
        v
fetch ALL active properties, score each in Python (soft, additive scoring;
no true MongoDB filter, no geospatial query - the existing 2dsphere index
on location.coordinates was created but never queried by anything)
        |
        v
sort by score, return
```

Phase 1 (`services/mappls_service.py` + `services/osm_location_service.py`, reachable only via `POST /api/location/resolve-poi`) and Phase 2 (`services/nlp/parser.py`, reachable only via `POST /api/search/parse-query`) both worked correctly in isolation but were never connected to this flow.

## 2. New architecture

```
POST /search_rentals  { ...existing structured fields..., "query": "<natural language>" }
        |
        v
"query" present and non-empty?
        |                                    \
       no                                     yes
        |                                      |
        v                                      v
UNCHANGED path:                    services.search_orchestration.orchestrate_search()
ranked_search(preferences)                     |
        |                            services.nlp.parser.parse(query)   (Phase 2, untouched)
        |                                      |
        |                            StructuredQuery
        |                                      |
        |                            merge_structured_fields()
        |                            (explicit structured fields ALWAYS win over parsed ones)
        |                                      |
        |                       location.type == "poi"?
        |                          /                    \
        |                        no                      yes
        |                         |                        |
        |                         v                        v
        |                  build_mongo_filter()   resolve_poi_location()
        |                  (real $gte/$lte/$all,   -> services.mappls_service (Phase 1, untouched)
        |                   no geo clause)         -> services.osm_location_service (Phase 1, untouched)
        |                         |                        |
        |                         |               MATCHED?  ---no--->  return {properties: [], location_resolution: <status>}
        |                         |                        |            (Mongo is NEVER queried for a failed POI - see §5/§6)
        |                         |                       yes
        |                         |                        |
        |                         |               build_mongo_filter() + $near clause
        |                         |               on the EXISTING location.coordinates
        |                         |               2dsphere index
        |                         v                        v
        |                  PropertyService.filtered_search(mongo_filter)   (Phase 3, new - real find())
        |                                      |
        v                                      v
        +--------------------- _serialize_property() (shared, unchanged) ------------------+
                                               |
                                               v
                                     jsonify({"properties": [...], ...})
```

`ranked_search()` is not modified, not deprecated, and not bypassed for any request that doesn't include `query` — it remains the exact algorithm it was before this phase.

## 3. NLP → search mapping

`services/search_orchestration.merge_structured_fields()` converts a `StructuredQuery.to_dict()` plus the request's already-validated explicit structured fields into one internal spec, field by field:

| StructuredQuery slot | Explicit request field | Merged spec key | Precedence |
|---|---|---|---|
| `listing_type.value` | `listing_type` | `listing_type` | explicit wins |
| `property_type.value` | `property_type` | `property_type` | explicit wins |
| `bedrooms.value` | `bhk` | `bhk` | explicit wins |
| `furnishing.value` | *(no explicit equivalent exists today)* | `furnishing` | parsed only |
| `price` (operator+value) | `budget` (`> 0`) → `{operator: "lte", value: budget}` | `price` | explicit wins |
| `area` (operator+value) | *(no explicit equivalent exists today)* | `area` | parsed only |
| `amenities[].value` | *(no explicit equivalent exists today)* | `amenities` | parsed only |
| `location` (`area_or_city`) | `city` / `locality` | `city` **and** `locality` | explicit wins |
| `location` (`poi`) | `city` / `locality` | `poi_query` | explicit `city`/`locality` wins (POI ignored if either is given) |

`build_mongo_filter()` then turns that spec into a real MongoDB filter — see §4's table for the exact operator mapping. Preserved exactly, per the task's explicit requirement: `<=` stays `<=`, `between` keeps both bounds, nothing is silently collapsed into equality or discarded (`test_search_orchestration.BuildMongoFilterTests` asserts this directly for every operator).

## 4. POI → geospatial search mapping

For a `location.type == "poi"` query, `resolve_poi_location()` runs the **identical** two-step chain `routes/property_routes.py`'s existing `/api/location/resolve-poi` endpoint already uses:

1. `mappls_service.resolve_place(poi_query, mappls_api_key, location_bias=...)` — Mappls remains the sole authority for *which* entity the query means.
2. If Mappls matched: `osm_location_service.resolve_coordinates({...})` — OSM only ever locates the entity Mappls already selected; it never re-ranks.

| Resolution status | Action |
|---|---|
| `matched` | `location.coordinates` gets `{"$near": {"$geometry": {type: "Point", coordinates: [lon, lat]}, "$maxDistance": radius_meters}}` added to the same filter dict from §3, then `PropertyService.filtered_search()` runs one real query. `$near` on the pre-existing 2dsphere index also returns results already sorted by distance — no custom ranking code was written for this (Step 13 of the task explicitly forbids that). |
| `ambiguous` / `no_match` / `rejected` / `error` | **No MongoDB query is executed at all.** The response returns `properties: []` and `location_resolution: {status: "...", ...}` so the caller can see exactly what happened, never a location-unfiltered result set masquerading as a match. |

Search radius: `SEARCH_POI_RADIUS_KM` (env-configurable via `app.py`, default **5.0 km** — matching the Phase 2 report's own "within 5 km of X" example), converted to meters for `$maxDistance`.

## 5. Area/city vs. POI handling

- **`area_or_city`** (e.g. `"in Chennai"`, `"in Adyar"`): mapped directly onto the **existing** `location.city` and `location.locality` fields via a case-insensitive regex `$or`, matching either field. No geocoding, no coordinate conversion, no external API call — exactly per the task's explicit instruction not to convert a city/locality name to coordinates without concrete reason. The same text is checked against both fields (rather than guessing which one it is) because `services/nlp/location_extractor.py` itself deliberately never distinguishes locality from city from text alone (documented in that module already, Phase 2) — checking both is the honest way to use that information rather than guessing.
- **`poi`** (e.g. `"near IIT Madras"`): the only case that goes through Phase 1's Mappls → OSM resolver at all. A bare city/locality mention is never sent to that resolver.

## 6. Failure handling

- **NLP**: `parser.parse()` already never raises for malformed/empty/unsupported input (verified by Phase 2's own boundary tests, and re-verified at the orchestration and route layers — `test_malformed_unsupported_query_does_not_crash`, `test_empty_query_does_not_crash`). An unrecognized query returns `intent: "unknown"` and an empty result set, not an error or a crash.
- **POI resolution**: every one of the 5 statuses (`matched`/`ambiguous`/`no_match`/`rejected`/`error`) is handled explicitly and distinctly (§4's table) — there is exactly one code path that ever populates `latitude`/`longitude` (the `matched` branch), enforced by `NoFabricatedCoordinatesTests.test_only_osm_matched_result_ever_supplies_coordinates` parametrized over all four non-matched statuses.
- **No silent fallback**: a failed POI resolution never falls back to running the search without the location constraint — that would silently return properties from an unrelated area as if they matched. `properties: []` plus an explicit `location_resolution` status is the deliberate, disclosed alternative.
- **No location mentioned at all**: normal filtered search runs with whatever other constraints were parsed/given, no geospatial restriction — this is `location_resolution: None` in the response, distinct from a *failed* resolution.

## 7. MongoDB geospatial query behavior

The existing 2dsphere index (`services/property_services.py`'s `ensure_indexes()`, already present before Phase 3, unmodified) is reused as-is. `$near` was chosen over `$geoWithin`/`$centerSphere` because it both filters *and* sorts by distance in one native operator, avoiding the need to write any custom distance/ranking code (straight-line or otherwise) — satisfying the task's explicit preference for MongoDB's own geospatial capabilities over manual Python distance calculation.

## 8. Backward compatibility

`POST /search_rentals` with no `query` field (or a `query` that's empty/whitespace-only after stripping) is **byte-for-byte unchanged**: same validation, same `preferences` dict, same `ranked_search()` call, same response shape (`{"properties": [...]}`, no new keys). `_serialize_property()` — the JSON-shaping logic for one property — was extracted verbatim from the original inline loop into a shared helper used by both paths; this is a pure mechanical extraction (confirmed via `git diff`, and via `BackwardCompatibilityTests` in `test_search_routes_integration.py`), not a behavior change. When `query` **is** present, the response gains three additive keys (`parsed_query`, `location_resolution`, `applied_filters`) — no existing key is removed, renamed, or reinterpreted.

## 9. Tests performed

All run via `python -m unittest <module>`, all passing:

| Suite | Tests | Notes |
|---|---|---|
| `test_nlp_parser` | 45 | Phase 2, unchanged, unaffected |
| `test_mappls_service` | 8 | Phase 1, unchanged, unaffected |
| `test_osm_location_service` | 24 | Phase 1, unchanged, unaffected |
| `test_geospatial_service` | 30 | Pre-existing, unrelated, unaffected |
| `test_search_orchestration` | 33 | **New** — merge precedence, filter operator preservation, all 5 POI statuses, no-fabricated-coordinates boundary |
| `test_search_routes_integration` | 12 | **New** — real Flask test client against a minimal app (fake `PropertyService`/`OSMLocationService`, patched `mappls_service.resolve_place`, no live MongoDB/Mappls/OSM dependency), covering backward compatibility and the end-to-end HTTP contract |
| **Total** | **152** | **All passing** |

End-to-end scenarios exercised (mapped to the task's required list): 2 BHK apartment for rent in Chennai (area_or_city, no geo) · furnished flat under a price bound in a city (explicit price + area_or_city) · apartments near a POI, matched (geospatial `$near`) · flats around a POI, ambiguous (empty result + explicit status) · houses near a POI, no_match (empty result + explicit status) · amenity-only query (`gym`/`swimming_pool` → exact `features` match; `parking` → OR-across-subtypes match) · malformed/off-topic query (`intent: "unknown"`, no crash) · explicit structured field overriding a conflicting parsed field. `rejected`/`error` POI statuses are covered at the orchestration layer (`test_search_orchestration.py`) rather than duplicated at the route layer, since the route's handling of all 4 non-matched statuses is identical (§4/§6).

## 10. Known limitations

- **The generic `"parking"` amenity code**: no single stored field represents "has parking" — `services/property_fields.py`'s schema only has 4 specific sub-types. This phase interprets NLP's generic `"parking"` as "any of the 4 sub-types present" (a disclosed OR, not a guess at one specific sub-type). This remains a genuinely open product question, carried over from Phase 2/2.5, not resolved here.
- **`area_or_city` text matching** uses a case-insensitive substring regex against both `city` and `locality` — forgiving by design (matching `ranked_search()`'s own existing forgiving behavior), but not a true geocoded/hierarchical area match. A misspelled or highly ambiguous area name will simply not match, with no error surfaced beyond an empty result set.
- **`furnishing` and `area` have no explicit-structured-field equivalent** in the current request contract — they can only be set via natural language today, not via a dedicated form field, since none exists yet in `services/property_fields.py`'s search-facing (as opposed to submission-facing) contract.
- **The `"approx"` price/area operator** (e.g. "around 80 lakh") uses a disclosed, symmetric ±10% tolerance band (`APPROX_PRICE_TOLERANCE`/`APPROX_AREA_TOLERANCE` in `services/search_orchestration.py`) since no natural-language query supplies an exact hard bound for "approximately." This is a reasonable, documented default, not a validated-against-real-usage figure.
- **No ranking beyond MongoDB's own `$near` distance-sort** is implemented for the new natural-language path, per the task's explicit "no sophisticated ranking in Phase 3" instruction — a non-geo natural-language search's result order is whatever `collection.find()` returns (insertion order), not a relevance score. This is an intentional scope boundary, not an oversight.
- **Typo tolerance remains unaddressed** (Phase 2.5's own carried-over open item) — a misspelled property type/amenity/furnishing word in a natural-language search query will simply not match, exactly as documented in `docs/PHASE_2_5_NLP_EVALUATION.md`.

## 11. What remains for the next phase

- Resolve the generic `"parking"` mapping with actual product input (this phase's OR-across-subtypes interpretation is a reasonable default, not a final decision).
- Decide whether/how to surface `location_resolution: "ambiguous"` to the end user in the actual UI (e.g. "did you mean...?" with the `alternates` OSM already returns) — this phase only guarantees the backend never silently mishandles it; no frontend work was done.
- Consider a relevance-ranking pass on top of the new geospatial/filtered results, once there's a real need beyond MongoDB's native distance sort — explicitly deferred here per Step 13.
- OSRM/Valhalla road-distance calculation remains deferred, as in every prior phase's own report.
- Typo tolerance (Phase 2.5 §19) remains open and unaddressed by this phase, as instructed.

---

## Files created
- `services/search_orchestration.py`
- `test_search_orchestration.py` (33 tests)
- `test_search_routes_integration.py` (12 tests)
- `docs/PHASE_3_SEARCH_INTEGRATION.md` (this file)

## Files modified
- `services/property_services.py` — added `filtered_search()` (pure addition; `ranked_search()` byte-unchanged, confirmed via `git diff`)
- `routes/search_routes.py` — extracted `_serialize_property()` (mechanical, no behavior change) from the original inline loop; added the optional `query`-driven branch in `search_rentals()`
- `app.py` — added `SEARCH_POI_RADIUS_KM` config (env-driven, default 5.0)

## Files explicitly NOT modified
- `services/nlp/*.py` (Phase 2)
- `services/mappls_service.py`, `services/osm_location_service.py` (Phase 1)
- `routes/property_routes.py`
- `services/property_fields.py`, `services/property_validation.py`
- `evaluation/nlp/**` (Phase 2.5 data/results)
- `implementation_changes.docx`
