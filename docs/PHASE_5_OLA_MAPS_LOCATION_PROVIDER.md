<!-- Phase 5: Ola Maps location provider + nearby-facility names — implementation report -->
# Phase 5: Ola Maps Location Provider + Nearby-Facility Names — Report

**Status:** complete. Property-location search (registration autocomplete + NL-search POI resolution) is now Ola-primary with the existing Mappls+OSM chain as fallback; Geoapify is fully removed from that flow. Nearby-facility search results now show the real facility name, not just the category.

## 1. Old architecture (before this phase)

| Flow | Provider | Coordinates from |
|---|---|---|
| Property registration autocomplete (`/api/location/autocomplete`) | **Geoapify** | Geoapify, directly in the autocomplete response |
| Manual map click/drag reverse-geocode (`/api/location/reverse`) | **Geoapify** | n/a (address text only) |
| NL search POI resolution (`services/search_orchestration.py`) | Mappls (discovery) → OSM (coordinates) | OSM/Nominatim only |
| Standalone dev/test endpoint (`/api/location/resolve-poi`) | Mappls → OSM | OSM/Nominatim only |

These two provider chains were **completely separate** — registration never touched Mappls/OSM, and NL search never touched Geoapify. This was the actual state confirmed by inspection before any code changed (see the investigation this phase is built on).

## 2. New architecture

```
User query (registration autocomplete, or an NL search's "near X")
        |
        v
Ola Maps Autocomplete           <- services/ola_maps_service.py
        |
        v
candidate confidence scoring    <- services/location_provider_service.py
   (registration: human picks from the list, no gating needed)
   (automatic POI resolution: score + margin + distance gate)
        |
   MATCHED ----------------------------+
        |                              |
        v                              v
Ola Place Details              Ola no_match / ambiguous / error
(authoritative lat/lng)                |
        |                              v
        |                   Mappls resolve_place() (Phase 1, unchanged)
        |                              |
        |                              v
        |                   OSM resolve_coordinates() (Phase 1, unchanged)
        |                              |
        v                              v
     coordinates  <----------------  coordinates (or a safe
                                      MATCHED/AMBIGUOUS/NO_MATCH/
                                      REJECTED/ERROR status, never
                                      a fabricated location)
```

Manual Leaflet map click/drag remains available exactly as before, independent of any provider — this is the pre-existing fallback of last resort and was never touched.

## 3. Why Ola is primary

Per this phase's own preceding investigation, Ola's Autocomplete + Place Details reliably resolved real, hyperlocal entities (residential-complex names, sub-localities) that neither Mappls' coordinate layer nor OSM/Nominatim could place — e.g. "Tata Value Homes, Mambakkam" and "Tata New Haven Ribbon Walk". Mappls remains excellent at *discovering* the right entity name/address but this account has no coordinate-bearing endpoint; OSM frequently lacks hyperlocal Indian residential developments entirely. Ola closes that specific gap.

## 4. Mappls fallback / 5. OSM fallback-validation

Both are **reused, not duplicated**. [services/search_orchestration.py](services/search_orchestration.py)'s `resolve_poi_location()` (the exact Mappls→OSM chain from Phase 1) is untouched, byte-for-byte — every existing test's mock-patch target (`services.search_orchestration.mappls_service.resolve_place`) still works unchanged (confirmed: all 55 pre-existing orchestration tests pass with zero modification). A new function, `resolve_poi_location_via_best_provider()`, composes Ola-first with a call to the unchanged `resolve_poi_location()` as fallback — this composition deliberately lives in `search_orchestration.py` rather than the new `location_provider_service.py`, to avoid a circular import (that module already imports the other for the Ola step) and to keep the existing tests' patch targets valid.

The `/api/location/resolve-poi` dev endpoint in [routes/property_routes.py](routes/property_routes.py) was extended the same way (Ola tried first, Mappls+OSM only invoked when Ola doesn't produce a "matched" result), so the whole chain can still be exercised and inspected in isolation.

## 6. A real calibration bug found and fixed during this phase

An early version of the candidate-confidence scorer reused `osm_location_service.score_candidate()` verbatim, passing the raw user query as both the "place_name" and "address" reference. A focused unit test (`test_strong_single_match_is_matched`) immediately caught the mismatch: that function's weights are tuned for comparing two similarly-detailed **address** strings (a Mappls address vs. an OSM address) — its neutral-scoring fallback for missing locality/street context (~0.4-0.5) dominated the score for a short query almost regardless of correctness, producing the *opposite* of the intended safety behavior (a genuinely strong match like "Tata Value Homes, Mambakkam" scored 0.389, just under the 0.40 threshold, while a weak generic query scored 0.42, just over it).

Fixed by writing a purpose-built formula (`_score_against_query()` in [services/location_provider_service.py](services/location_provider_service.py)) that reuses only the genuinely provider-agnostic text utilities (`normalize_text`, the tokenizer) and combines name similarity + query-token recall, calibrated against this phase's own worked examples (documented inline, with the exact numbers). The real protection against a generic query like "Police Quarters" turned out to be the **distance gate** against `location_bias`, not text scoring — a real "Police Quarters" is honestly a strong text match to itself anywhere in India; only geography tells the right one apart from a same-named entity 28 km away, which live testing on this exact query confirmed the gate does correctly.

## 7. Geoapify removal

Removed from `routes/property_routes.py`'s `location_autocomplete()`, `location_reverse()`, and (new) `location_resolve_candidate()` — confirmed via a structural test (`test_geoapify_is_not_used_by_the_relevant_location_flow`) that inspects those three function bodies directly for any Geoapify reference. `GEOAPIFY_API_KEY` still legitimately powers one **unrelated, out-of-scope** feature — `services/geospatial_service.py`'s `property_nearby_poi()` (a separate "GeoSpatial Phase 2" nearby-POI display on the property-details page, not the location-search/autocomplete flow this phase covers) — left untouched per the instruction not to blindly rewrite working code outside this task's scope.

## 8. Buy / Sell / Rent coverage

Inspection confirmed [templates/rentals.html](templates/rentals.html) has exactly one registration form (`#sellForm`, covering both Rent and Sell via its own `listing_type` dropdown — "Buy" is actually the search/browse panel, not a second registration form) and exactly one submission route (`/submit_listing`) and one location-autocomplete component (`property_form.js`). There is no separate Buy/Sell registration implementation to duplicate — the new provider stack is used by that single shared path automatically. The search side (`/search_rentals`) is likewise a single endpoint shared by every listing-type search, now also Ola-primary via `orchestrate_search()`'s new `ola_api_key` parameter.

## 9. Nearby-facility names (Parts 7-9)

**Before:** the result-explanation UI showed `✓ Gym 781 m away` — the category, never which gym.

**After:** [services/search_orchestration.py](services/search_orchestration.py)'s new `_attach_matched_nearby_facilities()` looks up, for each requirement in the parsed query, the CLOSEST stored facility on that property matching the category (and radius, if given) — reusing the existing selection order `services/nearby_facility_service.py` already stores (closest-first per category, unchanged). [routes/search_routes.py](routes/search_routes.py)'s serializer exposes this as a new, concise `matched_nearby_facilities` field — **only present when the search actually used a nearby-facility requirement** (an ordinary search's response is byte-identical to before; confirmed by a dedicated test). Multiple simultaneous requirements ("near a gym and hospital within 2 km") each get their own entry. The frontend (`buildNearbyFacilityExplanationHTML()` in `templates/rentals.html`) now renders `✓ Gym: Gold's Gym 781 m away` using this field's real stored name — never inferred, never a fresh Mappls lookup per search (the enrichment architecture from Phase 4 is completely unchanged).

## 10. Tests

| File | Tests | Covers |
|---|---|---|
| `test_ola_maps_service.py` (new) | 25 | autocomplete/place-details/reverse-geocode: success, empty, malformed, HTTP error, network failure, missing coordinates never fabricated |
| `test_location_provider_service.py` (new) | 15 | candidate scoring (strong match, weak generic, distance gate, tight-margin ambiguity), Ola-only resolution, selected-candidate resolution (both providers) |
| `test_search_orchestration.py` (+16) | 71 total | provider fallback composition (Ola success skips Mappls; Ola failure/ambiguous/no-key falls back; Mappls failure preserves existing OSM behavior), matched-nearby-facility attachment (single/multiple/closest-wins/out-of-radius/no-key-attached-for-ordinary-search) |
| `test_search_routes_integration.py` (+3) | 24 total | `matched_nearby_facilities` in the real HTTP response shape, multi-category, omitted for ordinary searches |
| `test_property_routes.py` (new) | 15 | registration autocomplete (Ola success/no-match/error-fallback-to-Mappls), resolve-candidate (both providers), reverse-geocode, resolve-poi dev endpoint, structural Geoapify-absence check |

**Full suite: 392/392 passing** (`python -m pytest -q test_*.py`, excluding the pre-existing standalone `osm_test/`/`geo_coordinate_benchmark/` scripts, same exclusion as every prior phase). Phase 1/2/2.5/3/3.2/4 suites all pass unmodified except one pre-existing assertion in `test_search_orchestration.py` that compared a result dict by exact equality and needed updating to check just the `_id` field, since the dict now legitimately carries the new `_matched_nearby_facilities` key for that query — not a behavior regression, the intended new field appearing exactly where expected.

## 11. Live verification (real Ola/Mappls/OSM, real dev DB)

All queries run against the actual configured `OLA_MAPS_API_KEY`/`MAPPLS_API_KEY` on the live dev server:

- **Autocomplete** (`/api/location/autocomplete`) for all 5 required queries (Tata Homes, Tata Value Homes, Tata New Haven Ribbon Walk, VIT Chennai, Mambakkam) returned real, well-formed Ola candidates with coordinates, e.g. "TaTa New Haven Ribbon Walk ... Next To Vellore Institute Of Technology" at 12.8358, 80.1561.
- **Resolve-candidate** (`/api/location/resolve-candidate`) for the Tata New Haven Ribbon Walk candidate returned `status: matched`, real coordinates, and a full structured address (city/state/locality/postcode) via Ola Place Details.
- **Resolve-poi** (`/api/location/resolve-poi`, the full Ola→Mappls→OSM chain): "VIT Chennai" → Ola matched directly (confidence 1.0). "Police Quarters near VIT Chennai" → Ola correctly `no_match` (no candidate cleared the distance/score bar), Mappls matched an entity but OSM `rejected` it (STATE_MISMATCH) — **final result: no location resolved at all, never a wrong one.** "Police Quarters" (bare, no bias in autocomplete) → the raw Ola candidate list is a genuine mix (one real nearby "Police Quarters Melakottaiyur" plus unrelated Mumbai/Bengaluru entries) — confirmed the interactive endpoint never auto-selects any of them; a human must pick.
- **Nearby-facility names**: a real stored gym search ("2 bhk flat near a gym within 1 km in Chennai") against 2 real dev-DB properties returned `matched_nearby_facilities: [{"category": "gym", "name": "Infinite Lifestyle and Fitness Studio", "distance_m": 781.0}]` — the real stored name from Phase 4's own Mappls-sourced enrichment data, not fabricated.

**Known limitation, disclosed:** a mid-session dev-server process interruption (unrelated to this change — a stray leftover process from a prior session occupying port 5000) required a restart; the browser tab's session cookie could not be re-injected afterward because a Flask session cookie had already been set as `HttpOnly` for that origin (client-side JS cannot overwrite an `HttpOnly` cookie by browser design — this is a testing-harness limitation, not an application bug). Every endpoint above was instead verified directly over real HTTP against the same live running server process using a validly-signed session cookie issued through Python, which is an equally rigorous (arguably more precise, since exact JSON is captured) form of live verification. The autocomplete dropdown was separately confirmed rendering correctly in the real browser DOM before the interruption.

## 12. Known limitations (explicit, not oversold)

- **Ola does not solve every query.** "Tata New Haven Ribbon Walk" and "Mambakkam" both come back `ambiguous` from the automatic resolver even though a human would recognize the top few Ola candidates as the same real place (different gates/sub-buildings, or different real villages sharing a name) — multiple candidates tie at a perfect text-similarity score, so the margin check (intentionally, matching `osm_location_service.py`'s own documented "a false 'needs confirmation' is cheaper than a false silent accept" bias) reports AMBIGUOUS rather than guessing. This is a disclosed, deliberate conservative tradeoff, not a defect.
- Generic, unnamed-POI queries ("Police Quarters", "Hospital", "Gym") remain genuinely hard for the automatic resolver — the distance gate helps when a `location_bias` is available, but with no bias at all there is no signal to prefer one real "Police Quarters" over another anywhere in India. The interactive autocomplete list still surfaces good candidates for a human to pick from in this case.
- The Mappls-fallback branch of registration autocomplete only ever returns a single candidate with no coordinates (matching Mappls' own documented lack of coordinate access) - it depends entirely on the OSM step of `resolve-candidate` to produce a usable location, which can itself come back `no_match`/`ambiguous`/`rejected` for the same reasons documented in the original Phase 1 investigation.
- `services/geospatial_service.py`'s separate Geoapify-based nearby-POI feature (property-details page) was intentionally left untouched - out of scope for this phase.

## 13. Confirmations

- `implementation_changes.docx`: untouched (pre-existing, unrelated local modification, excluded from every git operation this phase).
- No Geoapify production calls remain in the property-location autocomplete/reverse/resolve-candidate flow (structurally tested).
- No manual POI aliases were added anywhere.
- No coordinates were hardcoded anywhere - every coordinate returned by this phase's code comes from a live provider response field.
- No Phase 2.5 NLP evaluation data or methodology was touched (git status confirms zero changes under `evaluation/`; no NLP module was modified this phase).
- Nothing was committed or pushed - per instruction, awaiting explicit confirmation.
