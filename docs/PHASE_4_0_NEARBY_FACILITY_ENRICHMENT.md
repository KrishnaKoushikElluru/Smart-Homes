<!-- Phase 4.0: Nearby Facility Enrichment Layer — implementation report -->
# Phase 4.0: Nearby Facility Enrichment Layer — Report

**Status:** complete. A reusable, best-effort data layer that discovers and stores nearby real-world facilities for every registered property. No natural-language "gym nearby" search, ranking, or road distance is implemented here — this phase only builds and maintains the data those future phases would read.

## 1. Problem being solved

A property listing today stores nothing about what's actually *around* it beyond the address text a seller typed in. "2 BHK near a hospital" or "flat with a gym nearby" can't be answered from the property document alone. This phase adds a background enrichment step: when a property is registered with valid coordinates, discover real nearby facilities (gyms, hospitals, schools, etc.) across a configurable set of categories and store them on the property — without ever blocking or failing registration if the external POI provider is unavailable.

## 2. Architecture

```
routes/property_routes.py :: submit_listing()
        |
        v
property_service.create_property(property_data)  -> property_id   (UNCHANGED)
        |
        v
services.nearby_facility_service.enrich_property_nearby_facilities(property_id, ...)
        |
        v
property_service.get_property(property_id)   -> read stored coordinates   (existing method, reused)
        |
        v
for each of 17 facility categories:
        |
        v
    services.mappls_service.find_nearby_places(keyword, ref_location, radius_m, api_key)
    -> candidate places + MAPPLS' OWN provider-computed distance_m
       (verified live: this endpoint does not return lat/lon)
        |
        v
    normalize -> de-duplicate (by Mappls eLoc) -> sort by distance -> cap per category
        |
        v
    for the closest few per category (bounded - see radius/config section):
        services.osm_location_service.OSMLocationService.resolve_coordinates(...)
        -> best-effort coordinates (Phase 1's EXISTING chain, reused verbatim)
        |
        v
property_service.update_property(property_id, {
    "nearby_facilities": [...],
    "nearby_facilities_metadata": {...},
})   (existing method, reused)
```

`enrich_property_nearby_facilities()` is called directly, synchronously, right after `create_property()` returns its new `property_id` — see §12 for why, and the latency tradeoff this implies.

## 3. Registration flow (traced before writing anything)

There is exactly **one** application-level property creation path: `routes/property_routes.py`'s `submit_listing()`, which validates every field, requires valid `latitude`/`longitude` (via the existing `parse_latitude_longitude()` — a submission is rejected before this point if coordinates are missing/invalid), builds `property_data`, and calls `PropertyService.create_property()`. No seed/import script, no second route, no admin path exists. `test_mongodb.py`'s own use of `create_property()` is a standalone manual DB smoke test, not an application path.

**The only route change**: capture the now-used return value (`property_id = property_service.create_property(property_data)` — previously discarded) and call the new enrichment service right after. Nothing else in `submit_listing()` was touched.

## 4. Facility taxonomy

`services/nearby_facility_service.FACILITY_CATEGORIES` — a plain dict mapping each of the task's 17 required categories to the free-text keyword sent to Mappls' Nearby Search API:

```python
FACILITY_CATEGORIES = {
    "gym": "gym", "hospital": "hospital", "school": "school", "college": "college",
    "supermarket": "supermarket", "pharmacy": "pharmacy", "restaurant": "restaurant",
    "bank": "bank", "atm": "atm", "metro_station": "metro station",
    "railway_station": "railway station", "bus_stop": "bus stop",
    "shopping_mall": "shopping mall", "park": "park", "police_station": "police station",
    "fire_station": "fire station", "petrol_station": "petrol pump",
}
```

This is a **category → search-keyword taxonomy**, not a business-name alias table — it tells Mappls what word to search for, never which specific business belongs to which category (Mappls itself identifies the matching entities). Adding a new category later is one new dict entry; no other code changes. The keyword choices were taken from `mappls_geo_test/`'s own earlier capability investigation (already tested against this account) where available, and reasoned analogously for the rest — then verified live for several categories (§11).

## 5. Mappls / OSM roles (both reused, neither rewritten)

- **`services/mappls_service.py`** already had exactly one capability, `resolve_place()` (Phase 1, text-search-by-name, unchanged, untouched). This phase adds a **second, independent function to the same file** — `find_nearby_places(keywords, ref_location, radius_m, api_key)` — using the same static-key `access_token` auth and the same "never raises, `status: matched|no_match|error`" convention already established there. This was the explicit instruction: reuse the one Mappls integration point rather than build a second client.
- **Critical fact confirmed live against this account** (matching `mappls_geo_test/`'s own earlier finding for Text Search): **the Nearby endpoint does not return latitude/longitude either.** Every candidate place has a name, address, Mappls eLoc, type, and Mappls' own provider-computed `distance` in meters from the reference point — but no coordinates.
- **`services/osm_location_service.py`** (Phase 1) is used exactly as Phase 1/3 already use it — `resolve_coordinates({place_name, address})` — to best-effort resolve real coordinates for a bounded subset of candidates. Not modified in this phase.

## 6. Search radius

`NEARBY_FACILITY_RADIUS_KM` (env-configurable in `app.py`, default **2.0 km**) — deliberately tighter than Phase 3's `SEARCH_POI_RADIUS_KM` (5 km default), which answers a different question (how far an ambiguous *landmark* might reasonably spread for a property *search*) than this one (what counts as a *walkable, real-estate-relevant amenity* for a registered property). The radius actually used is stored on both the enrichment metadata (`radius_m`) and on every individual facility record (`search_radius_m`), so the data stays auditable even if the config value changes later.

## 7. Data model — chosen after inspecting the existing property document

**Decision: embedded, not a separate collection.** Reasoning, per the task's own checklist:

- **Query patterns**: no natural-language "nearby" search is implemented in this phase (explicitly deferred) — the dominant read pattern today is "show me this property's details," for which embedding avoids an extra collection lookup.
- **Document size**: bounded (≤17 categories × 5 kept results = ≤85 small sub-records, a few hundred bytes each — tens of KB, nowhere near MongoDB's 16MB document limit).
- **Update frequency**: low (once at registration, occasionally on a future refresh) — not the kind of high-churn data a separate collection is usually justified by.
- **Existing convention**: every other property-related structure in this codebase (`rooms`, `area`, `building`, `project`, `parking`, `type_details`, `legal`, `pg_details`, `amenities`, `rental`, `sale`) is already embedded directly on the property document. There is no precedent anywhere in this project for a separate property-linked collection except the OSM geocode *cache* (external-API response caching — a fundamentally different kind of data). Introducing a new architecture pattern here without a concrete need would contradict the task's own "do not introduce a separate architecture merely for theoretical scalability" instruction.
- **Future geospatial queries** ("within 1 km of a school") are still supported: each facility's `coordinates` field (when resolved) is stored in the **exact same GeoJSON `Point` shape** the project already uses for `location.coordinates` (`{"type": "Point", "coordinates": [lon, lat]}`), and `PropertyService.ensure_indexes()` now also builds a multikey `2dsphere` index on `nearby_facilities.coordinates` — unused by any query in this phase, added purely so a future phase can query it without a migration.

**Property document additions:**

```python
"nearby_facilities": [
    {
        "name": "RC Fitness Ladies Gym",
        "category": "gym",                       # canonical taxonomy key
        "address": "713, Mambakkam-Medavakkam Main Road, Chennai, Tamil Nadu, 600127",
        "latitude": None,                          # convenience mirror of "coordinates"
        "longitude": None,
        "coordinates": None,                       # GeoJSON Point, or None if unresolved
        "distance_m": 306.0,                        # Mappls' OWN provider distance - always
                                                      # present when Mappls matched, regardless
                                                      # of whether coordinates resolved
        "source": "mappls",
        "coordinate_source": None,                  # "osm" once/if resolved, else None
        "provider_id": "MX2MAT",                    # Mappls eLoc - stable, used for dedup
        "provider_type": "POI",
        "fetched_at": <UTC datetime>,
        "search_radius_m": 2000.0,
    },
    ...
],
"nearby_facilities_metadata": {
    "status": "completed" | "partial" | "failed" | "skipped" | "pending",
    "source": "mappls",
    "radius_m": 2000.0,
    "enriched_at": <UTC datetime>,
    "facility_count": 10,
    "categories_requested": ["gym", "hospital", "school"],
    "categories_failed": {},                        # {category: error_message}
    "error": None,
}
```

Deviations from the task's own illustrative example, and why: `coordinates` uses the project's real GeoJSON `Point` convention (not a bare `{latitude, longitude}` object) for index-readiness (§7 above); `coordinate_source` was added to distinguish "coordinates unresolved" from "coordinates resolved via OSM" without guessing; `provider_type` preserves Mappls' own `"POI"` type tag.

## 8. Distance

`distance_m` is **Mappls' own provider-computed straight-line distance** from the property's coordinates to the facility, returned directly in the Nearby API response — never derived, never called "walking"/"driving"/"travel time." This turned out to be a better design than resolving every candidate's coordinates and computing Haversine ourselves: it means a facility whose exact coordinates OSM can't confidently resolve (common for small local businesses — see §11) still has a reliable, correct distance. Coordinate resolution (via OSM) and distance (via Mappls directly) are two independent, separately-fallible pieces of information about the same facility — one failing never invalidates the other.

## 9. Deduplication

Within each category's result set, `_dedupe_places()` de-duplicates by Mappls' own `eLoc` (stable provider identity) first; only when `eLoc` is absent does it fall back to an exact match on an aggressively-normalized name (accents/punctuation/case stripped) — never fuzzy/similarity matching, and never across categories (a business legitimately matching two category searches, e.g. both "hospital" and a hypothetical "clinic" keyword, is kept once per category it was found under — that's two distinct, both-true facts, not a duplicate). Verified two businesses with genuinely different eLocs but similar names (`"Gold's Gym"` / `"Gold's Gym Annex"`) are never merged.

## 10. Failure handling

| Scenario | Behavior |
|---|---|
| Mappls unavailable (network/HTTP error) for a category | That category's error is recorded in `categories_failed`; other categories are unaffected; property registration succeeds regardless. |
| OSM unavailable / ambiguous / no_match / rejected for a candidate's coordinates | Not a category failure at all — the facility is still stored, still carries its Mappls `distance_m`, just with `coordinates: None`. |
| No nearby facilities in a category | `status: "completed"`, that category simply contributes 0 entries — never reported as a failure. |
| Malformed provider result (no name) | That single record is skipped; the rest of the category's results are unaffected. |
| Property has no/invalid coordinates | `status: "skipped"` (not "failed" — nothing was attempted, nothing went wrong externally) — never blocks registration, since coordinates are already required before a property can even be created via the real route. |
| Persisting the result itself fails (e.g. a transient Mongo error) | `status: "failed"`, with the specific error recorded — the discovery work isn't silently thrown away, but it's honestly reported as not saved. |
| Anything genuinely unexpected | Caught; the function still returns a well-formed metadata dict with `status: "failed"` and never raises — property registration is never at risk. |

`enrich_property_nearby_facilities()` is called directly from the route with **no** wrapping `try/except`, matching this codebase's established convention (`mappls_service`, `osm_location_service`, `geospatial_service` are all documented "never raises" and called the same way) — its own internal exception handling is the actual safety net, not a defensive wrapper at the call site.

## 11. Enrichment status

`nearby_facilities_metadata.status` distinguishes "there are no gyms nearby" (`status: "completed"`, `facility_count: 0` for that category) from "we haven't successfully enriched this property yet" (the field is simply absent, or `status: "failed"`/`"skipped"`) — exactly the distinction the task required. `"pending"` is a reserved, documented status value for a future async worker to use (e.g. mark it the moment a job is picked up) — this phase's own synchronous flow doesn't need to write it, since "no `nearby_facilities_metadata` field at all" already unambiguously means "not yet enriched."

## 12. Refresh / re-enrichment, and the latency tradeoff

`enrich_property_nearby_facilities(property_id, ...)` makes no assumption about when or why it's called — the same function is used by the registration route, `scripts/backfill_nearby_facilities.py`, and `scripts/manual_verify_nearby_enrichment.py`. Re-running it for the same property **replaces** (not appends to) `nearby_facilities` — verified (`test_re_running_enrichment_replaces_rather_than_appends`).

**Honest limitation, disclosed rather than hidden**: this phase runs enrichment **synchronously**, inline in the registration request. A full 17-category run took **~52 seconds** in live testing (§13) — the real cost is Nominatim's own documented 1-request/second policy for the (bounded, capped) OSM coordinate-resolution step, not Mappls' Nearby calls themselves (cheap, ~17 total, no documented rate limit). `NEARBY_FACILITY_COORDINATE_RESOLUTION_LIMIT_PER_CATEGORY` (default **1**, i.e. only the single closest candidate per category gets an OSM lookup) exists specifically to bound this. No background job/queue was introduced, per the task's explicit "don't build a complicated system yet" — a natural next step (not built here) is wrapping this same, already-reusable function in an async worker.

## 13. Existing properties / backfill

Per the task's explicit instruction, **no mass enrichment was run automatically**. Two standalone, manually-invoked scripts were built instead:

- **`scripts/backfill_nearby_facilities.py`** — safe and restartable: only processes properties with no `nearby_facilities_metadata` at all by default (`--retry-failed` additionally includes ones whose last attempt failed; `--force` re-does everything, used deliberately); commits each property's result immediately, so an interrupted run leaves already-processed properties enriched and picks up exactly where it left off on re-run; `--limit` bounds a single run; `--dry-run` lists what would be processed without any external call or write. **Verified via `--dry-run` only** (found the 3 existing properties, wrote nothing, called nothing external) — not executed for real against the whole database.
- **`scripts/manual_verify_nearby_enrichment.py`** — the "at least one controlled integration/manual verification against the real development APIs" the task asked for (matching this project's existing convention: `geo_coordinate_benchmark/manual_endpoint_test.py`, `mappls_geo_test/`). **This one WAS run for real** (§14) — a single, deliberate, controlled enrichment of one existing property, not a mass backfill.

## 14. Live verification (real Mappls, real OSM, real MongoDB)

A first run against a real existing property (`radius_km=2.0`, categories gym/hospital/school) failed outright: **HTTP 400 from Mappls for every category.** Root-caused live (isolated with a direct `requests.get` call varying only the `radius` value's type) to a real bug: **Mappls' Nearby API rejects a decimal `radius` parameter** (e.g. `"2000.0"`) with 400, but accepts an integer. `radius_km * 1000.0` naturally produces a float; `find_nearby_places()` now normalizes it to a clean `int` right where the HTTP request is built (`services/mappls_service.py`), with a regression test (`test_float_radius_is_sent_as_a_clean_integer`) pinned to this exact failure mode. Re-run after the fix: **`status: "completed"`, 10 real facilities** (RC Fitness Ladies Gym at 306m, Annai Hospital at 581m, Velammal Vidyashram School at 562m, etc. — real Mambakkam, Chennai businesses).

A second, full 17-category run against the same property: **`status: "completed"`, 51 real facilities, ~52 seconds.** Notably, **0 of the 51 facilities got OSM-resolved coordinates** — investigated directly (not assumed): a live `resolve_coordinates()` call for "HDFC Bank, Mambakkam Branch" (a major national chain, not an obscure business) returned `no_match`, and a raw Nominatim query confirmed the root cause is genuine — `"HDFC Bank, Chennai"` returns 5 results, but `"HDFC Bank, Mambakkam Branch"` / `"HDFC Bank Mambakkam"` return **zero**: Mambakkam (a small Chennai suburb) simply has sparse OpenStreetMap coverage for individual businesses. This is the honest, expected "never guess a coordinate" behavior working correctly, not a bug — and is exactly why `distance_m` is sourced from Mappls directly rather than depending on OSM resolution succeeding (§8).

## 15. Tests

**40 new tests, all passing** (full suite: **205/205**, up from 163 before this phase):

- `test_mappls_service.py` (+12): `find_nearby_places()` — empty keywords/missing ref location/missing key all error without a network call, successful search returns places with Mappls' own `distance_m` (never fabricates coordinates), no-match/204/HTTP-error/network-failure handling, malformed candidate entries skipped, params passed through correctly, **the float-radius regression** (§14), invalid radius handling.
- `test_nearby_facility_service.py` (new, 30 tests) covering every scenario the task listed: coordinate presence/absence gating, normalization + category preservation, coordinate validation, distance correctness, OSM resolution (matched/ambiguous, and the per-category resolution cap), deduplication (eLoc-based, and confirming similar-but-distinct names are never merged), empty results stored correctly, Mappls/persistence failure never crashing, partial-failure metadata, enrichment metadata correctness, repeated enrichment replacing not appending, configurable radius, provider ID/type preservation.

## 16. Known limitations

- Synchronous, in-request execution — latency scales with category count (§12); no background job built yet.
- OSM coordinate-resolution success rate is genuinely low for less-mapped suburban/semi-rural areas (§14) — this is an OpenStreetMap data-coverage fact, not something this phase can fix, and `distance_m` remains reliable regardless.
- The category → keyword taxonomy (§4) was verified live for several categories but not all 17 individually against this account.
- No natural-language "gym nearby" search, ranking, ETA/road-distance, or scheduled refresh — all explicitly out of scope for this phase.

## 17. Future query examples this data model now supports (not implemented here)

```
"flat with a gym nearby"            -> filter properties where nearby_facilities
                                        contains {category: "gym"}
"2 BHK near a hospital"             -> same pattern, category: "hospital"
"house close to metro"              -> category: "metro_station"
"property within 1 km of a school"  -> geospatial query using the new
                                        nearby_facilities.coordinates 2dsphere index,
                                        or a simple distance_m <= 1000 filter
```

---

## Files changed
- `services/mappls_service.py` — added `find_nearby_places()` (new function; `resolve_place()` untouched) + the radius-type fix (§14)
- `services/property_services.py` — added the new `nearby_facilities.coordinates` 2dsphere index to `ensure_indexes()` (pure addition; every other method untouched)
- `routes/property_routes.py` — capture `create_property()`'s return value; one new call to the enrichment service
- `app.py` — added `NEARBY_FACILITY_RADIUS_KM` config
- `test_mappls_service.py` — 12 new tests

## Files created
- `services/nearby_facility_service.py`
- `test_nearby_facility_service.py` (30 tests)
- `scripts/backfill_nearby_facilities.py`
- `scripts/manual_verify_nearby_enrichment.py`
- `docs/PHASE_4_0_NEARBY_FACILITY_ENRICHMENT.md` (this file)

## Files explicitly NOT changed
- `services/nlp/*`, `services/search_orchestration.py`, `services/osm_location_service.py`, `routes/search_routes.py`, `evaluation/nlp/**`, `templates/rentals.html`, `implementation_changes.docx`
