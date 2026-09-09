<!-- Phase 3.2: Ambiguous-Location "Did You Mean?" Picker — implementation report -->
# Phase 3.2: Ambiguous-Location Picker — Report

**Status:** complete. A user-reported dead end — searching `"flat near VIT Chennai"` always returned zero results — is now a working "did you mean one of these?" picker.

## 1. What was reported and what was actually happening

The user tried `"a flat near VIT CHENNAI"` and got the AMBIGUOUS message with zero results. Live debugging (`services.mappls_service.resolve_place` + `services.osm_location_service.OSMLocationService.resolve_coordinates`, called directly against the real Mappls/OSM APIs) confirmed this was **not a bug** — VIT Chennai's campus is tagged in OpenStreetMap as several separate buildings (Administrative Block, Academic Block 1, Academic Block 3, a Library Block) a few hundred meters apart, all scoring almost identically (~0.44–0.49). The margin between the top two (0.022) sits well below the system's `MIN_MARGIN` (0.05) safety threshold, so it correctly refuses to guess between them — exactly the "never silently accept a weak/ambiguous match" rule this whole location pipeline was built around since Phase 1. The practical effect, though, was that **any query mentioning this landmark returned a dead end**, with no way for the user to say which building they meant.

## 2. What was built

When `location_resolution.status === "ambiguous"`, the rentals page now renders each of OSM's top candidates as a clickable option (name + full address). Clicking one re-runs the exact same search, anchored at that specific building's coordinates, and results render normally.

## 3. The one genuine gap this required fixing

`services/osm_location_service.py`'s `resolve_coordinates()` already returned an `alternates` list for transparency, but **only for candidates ranked 2nd–4th** (`scored[1:4]`) — the actual top-ranked candidate (the one that made the result "ambiguous" rather than "no_match" in the first place) was never exposed in that branch at all. A picker built only from ranks 2–4 would have been missing the single most likely option. This is a real, narrow gap in the existing code, not a design choice explained anywhere in that module's docstring.

**The fix** (the only change to a Phase 1 file in this whole project since Phase 1 itself): inside the `ambiguous` branch specifically, `alternates` is now built from `scored[:4]` (top 4, including rank 1) instead of `scored[1:4]`. Every other branch (`matched`, `rejected`, `no_match`) is byte-for-byte unchanged — confirmed via `git diff` (a single, additive, ~20-line block) and the full existing 24-test `test_osm_location_service.py` suite passing unmodified, plus a new deterministic regression test (`test_ambiguous_alternates_include_the_top_ranked_candidate`) pinned to the real VIT Chennai scores observed live. `latitude`/`longitude`/`matched_name` at the top level of the ambiguous result remain `None`, exactly as before — "ambiguous never implies a resolved coordinate" still holds; `alternates` is a separate, explicit list of un-chosen options, never a silent pick.

## 4. Backend: `services/search_orchestration.py`

- `resolve_poi_location()` now passes `alternates` through from the OSM result into its own return value (previously discarded entirely).
- `orchestrate_search()` gained an optional `explicit_coordinates: (lat, lon)` parameter. When given, **Mappls/OSM resolution is skipped entirely** for that request — used when the frontend already knows exactly which place the user meant (they clicked an alternate from a *previous* ambiguous response). Re-resolving the same query text would just be ambiguous again, since nothing about the text changed; explicit coordinates let the rest of the pipeline (parsed price/BHK/amenities/etc, the `$near` geospatial filter, `PropertyService.filtered_search()`) run exactly as it would for a normal match, just skipping straight to "here's where to search."

## 5. Route: `routes/search_routes.py`

Two new, fully optional JSON fields on `POST /search_rentals`: `location_lat` / `location_lon`. Both must be present and valid together (or neither is used) — a malformed or lone value returns `400`, since that's a client bug, not a legitimate search input, and should not be silently ignored. Their absence changes nothing about the existing request/response contract (verified: `test_no_coordinates_falls_back_to_normal_poi_resolution`).

## 6. Frontend: `templates/rentals.html`

- `searchNaturalLanguage(event)` is now a thin validation wrapper around a new shared `performNlpSearch(queryText, explicitLocation)`, used by both the normal search submit (`explicitLocation = null`) and the new picker's click handlers (`explicitLocation = {lat, lon, label}`).
- `renderNlpFeedback()` gained a dedicated `ambiguous` branch (`renderAmbiguousLocationPicker()`) that renders `location_resolution.alternates` as clickable cards. Only `matched_name`/`matched_address`/`latitude`/`longitude` are used — the `score` field present in each alternate is deliberately never shown to the user (kept internal, consistent with every other status message already not exposing OSM/Mappls confidence values).
- After a picked-location search resolves, a small `"📍 Showing results near {name}"` confirmation renders above the usual "understood filters" chips — built entirely from the label the user just clicked, no extra backend round-trip needed for it.
- **A real CSS bug found and fixed during live testing**: the picker's option cards initially rendered as solid blue full-width buttons instead of the intended light cards, because the pre-existing `.sub-form button` rule (class + element selector) has higher specificity than a bare `.nlp-location-option` class selector. Fixed by scoping the rule to `.nlp-location-picker .nlp-location-option` (two classes), which now correctly wins.

## 7. Tests

All new, all passing alongside the full existing suite (**163/163** total):

- `test_osm_location_service.py`: +1 (`test_ambiguous_alternates_include_the_top_ranked_candidate`, deterministic via a patched `score_candidate`, pinned to the real VIT Chennai scores).
- `test_search_orchestration.py`: +6 (alternates threaded through for ambiguous / defaulted to `[]` when absent; `explicit_coordinates` skips Mappls/OSM entirely and still applies every other parsed filter correctly).
- `test_search_routes_integration.py`: +6 (`location_lat`/`location_lon` accepted and used, malformed/out-of-range/lone-value rejected with 400, absence changes nothing, ambiguous response actually carries `alternates`).

## 8. Live verification

Using the real dev server, real MongoDB, and real Mappls/OSM APIs (a throwaway test account created and removed afterward):

1. `"a flat near VIT Chennai"` → AMBIGUOUS, picker rendered with the 4 real OSM candidates (VIT Chennai library Block, VIT Chennai Administrative Block, VIT Academic Block 1, VIT Academic Block 3), each with its full address.
2. Clicking "VIT Chennai Administrative Block" → a second real request fired automatically with `location_lat`/`location_lon` set → `location_resolution.status === "matched"` → `"📍 Showing results near VIT Chennai Administrative Block"` shown → one real property rendered via the same shared card UI.
3. Caught and fixed the CSS specificity bug above during this same session.

**One data-quality observation, not a bug in this feature**: the property that matched in step 2 above is labeled `city: "Kurnool"` in its own document but has `locality: "khizhakottayur"` and stored coordinates genuinely within the VIT Chennai area — confirmed by directly querying MongoDB. The `$near` geospatial filter correctly matched on the real stored coordinates (which is exactly what it's supposed to do); the misleading `city` label is pre-existing seed/test data, unrelated to and not modified by this or any prior phase.

## 9. Backward compatibility

- Every existing manual and NLP-without-alternates flow is unaffected — `location_lat`/`location_lon` are optional and ignored when absent; `alternates` is simply a new, additive key in `location_resolution` that older/other callers (e.g. `/api/location/resolve-poi`, which surfaces its OWN `alternates` from the same OSM service, entirely unaffected by this change since that endpoint doesn't distinguish "ambiguous" for its own display logic) already tolerate.
- `MATCHED`/`REJECTED`/`NO_MATCH`/`ERROR` handling from Phase 3.1 is completely untouched.

## Files changed
- `services/osm_location_service.py` (the one targeted, additive fix — §3)
- `services/search_orchestration.py` (`alternates` threaded through; `explicit_coordinates` parameter)
- `routes/search_routes.py` (`location_lat`/`location_lon` request fields)
- `templates/rentals.html` (picker UI, `performNlpSearch()` refactor, CSS fix)
- `test_osm_location_service.py`, `test_search_orchestration.py`, `test_search_routes_integration.py` (new regression tests)

## Files NOT changed
- `services/nlp/*`, `services/mappls_service.py`, `services/property_services.py`, `evaluation/nlp/**`, `implementation_changes.docx`
