<!-- Phase 4, Stage 1: Registration Performance — implementation report -->
# Phase 4, Stage 1: Registration Performance — Report

**Status:** complete. Nearby-facility enrichment now runs in a background thread; property registration no longer waits for it.

## 1. Problem

Phase 4.0 wired `enrich_property_nearby_facilities()` directly into `submit_listing()`, called synchronously. Live measurement in that phase showed a full 17-category run taking **~52 seconds** — meaning a user submitting a listing waited up to a minute for a redirect that has nothing to do with whether their property was saved (it already was, before enrichment even started).

## 2. What changed

```
BEFORE (Phase 4.0):                       AFTER (Stage 1):

create_property()                         create_property()
        |                                         |
        v                                         v
enrich_property_nearby_facilities()       claim_nearby_facilities_enrichment()
  (BLOCKS - up to ~52s)                     (fast, synchronous, marks "pending")
        |                                         |
        v                                         v
flash + redirect                          threading.Thread(...).start()  (returns immediately)
                                                    |
                                                    v
                                           flash + redirect  (<0.05s)
                                                    |
                                                    |   (background, unattended)
                                                    v
                                           enrich_property_nearby_facilities()
                                             -> completed/partial/failed
```

`enrich_property_nearby_facilities()` itself — the actual Mappls/OSM/normalize/dedupe/persist logic from Phase 4.0 — is **completely unchanged**. Confirmed via `git diff`: zero changes to `services/mappls_service.py` or `services/osm_location_service.py` this stage. Stage 1 only changes *where* that function runs, not what it does.

## 3. Inspection performed before editing

- Re-read `submit_listing()`'s tail (property creation → the single enrichment call point).
- Re-read `nearby_facility_service.py` in full (the Phase 4.0 synchronous core).
- Re-read `mongo_service.py`: a single `pymongo.MongoClient` (documented thread-safe) wrapped once at app startup; `property_service`/`osm_service` are single shared instances in `app.extensions`, already implicitly relied upon to be safe under Flask's normal concurrent-request handling — Stage 1 does not introduce a new thread-safety assumption, it exercises the same one more often.
- Confirmed `nearby_facility_service.py` already took every dependency as an explicit argument (no `current_app`/`request`/`g` anywhere in it) — this is exactly what made a bare background thread safe to build without a Flask app context.
- Checked for an existing test file for `property_services.py` (none existed) before adding one.

## 4. New: at-most-one-worker-per-property (requirement 10)

`PropertyService.claim_nearby_facilities_enrichment(property_id, pending_metadata)` — a single atomic MongoDB `update_one` that only succeeds if the property is **not already** `status: "pending"`:

```python
self.collection.update_one(
    {"_id": ObjectId(property_id), "nearby_facilities_metadata.status": {"$ne": "pending"}},
    {"$set": {"nearby_facilities_metadata": pending_metadata, ...}},
)
```

`start_background_enrichment()` calls this **before** starting any thread; if the claim fails, no thread is started at all. This guarantee comes from MongoDB's own atomic single-document update — it holds even across multiple app processes, not just multiple threads within one, which a simple in-process Python lock would not have provided.

## 5. Enrichment lifecycle (requirement 8/9)

`nearby_facilities_metadata.status` now has 5 named values (`services/nearby_facility_service.py`'s `STATUS_*` constants): `pending`, `completed`, `partial`, `failed`, `skipped`. `"pending"` is written **synchronously**, before the thread starts — a property is never left with no `nearby_facilities_metadata` at all while enrichment is genuinely in flight, so "not yet enriched" is never confusable with "enriched, zero facilities found." A new `queued_at` timestamp (distinct from `enriched_at`, which stays `None` while pending) lets a stuck/abandoned pending entry be told apart from a normal in-progress one later.

## 6. Exception containment (requirement 7)

`_run_enrichment_in_background()` (the actual thread target) wraps `enrich_property_nearby_facilities()` in a broad `try/except` — a deliberate last-resort net, since by the time this runs there is no Flask request context left to report an error to at all. On any exception, the property is marked `status: "failed"` with the exception text; if even *that* write fails, the function gives up silently (there is genuinely nothing safer left to do). Verified both by a mocked unit test (`test_worker_exception_is_contained_and_recorded_as_failed`) and structurally: an uncaught exception on a Python background thread never crashes the hosting process, it only kills that one thread — but leaving a property stuck at `"pending"` forever with no explanation would have been a real, silent regression this net prevents.

## 7. Backfill script updated for the new "pending" state

`scripts/backfill_nearby_facilities.py --retry-failed` now also picks up `"pending"` entries — but **only** ones older than `--stale-pending-minutes` (default 10). A fresh `"pending"` entry might be a real, currently-running registration-time worker; re-running it from the backfill script too would race that live worker and defeat the entire point of §4's atomic claim. This was a real design question worth getting right, not an afterthought: the atomic claim intentionally treats "pending" as "someone's already on it" everywhere else, so recovery of a *genuinely abandoned* pending entry needed its own, separate, time-based signal.

## 8. Performance measurement (real, not mocked)

**A/B — HTTP registration latency:**

| | Latency | Notes |
|---|---|---|
| **BEFORE** (Phase 4.0, blocking) | **~52 seconds** | Measured live in Phase 4.0 (`docs/PHASE_4_0_NEARBY_FACILITY_ENRICHMENT.md` §14) — the exact same `enrich_property_nearby_facilities()` call, called directly (unmodified), full 17-category run, cold cache. |
| **AFTER** (Stage 1, background) | **0.036 seconds** | Measured live this stage (`scripts/stage1_performance_measurement.py`) — the exact call `submit_listing()` now makes (`start_background_enrichment()`), same real Mappls key, same real OSM service, same 17 categories, same real property. |

**~1,450x faster registration response** (52 / 0.036). This is the metric the task correctly emphasized as the important one — total enrichment work is unchanged, only *where* the request waits for it changed.

**C/D/E — background completion (same live run):**

| | Value |
|---|---|
| Total background enrichment duration | **38.98 seconds** |
| Final status | **`completed`** |
| Facilities stored | **60** |

(This run's 39s vs. Phase 4.0's earlier 52s for a comparably-sized run is most likely partial OSM/Nominatim cache reuse from this session's own prior testing at a nearby coordinate — not a Stage 1 effect, since the underlying enrichment function is byte-for-byte unchanged. Flagged here rather than left to look like an unexplained discrepancy.)

**F — real Mappls failure** (a genuinely invalid API key, not mocked — `scripts/`, run live):

```json
{
  "status": "failed",
  "categories_failed": {
    "gym": "Mappls nearby search failed (HTTP 401).",
    "hospital": "Mappls nearby search failed (HTTP 401)."
  },
  "error": "All facility categories failed to resolve."
}
```

Registration itself (the property document) was completely unaffected — confirmed by the property existing and being fully saved before this failure was ever recorded.

**G — background worker exception:** covered by `test_worker_exception_is_contained_and_recorded_as_failed` (mocked — a genuine unhandled crash isn't something to induce against the real Mappls/OSM APIs on demand). A raw `RuntimeError` injected into `enrich_property_nearby_facilities()` is caught by the thread target, the property is correctly marked `"failed"` with the exception text, and — critically — the test process itself never sees an unhandled exception propagate out of `thread.join()`.

## 9. Concurrency / thread-safety considerations

- **`pymongo.MongoClient`**: documented thread-safe; the app already relies on this for ordinary concurrent request handling, Stage 1 does not add a new requirement here.
- **The atomic claim** (§4) is the actual safety mechanism for "at most one worker per property" — not a Python-level lock, which would only have protected against races within one process.
- **`services/osm_location_service.py`'s rate limiter** (`_RateLimiter`, enforcing Nominatim's 1 req/sec policy) is a single shared instance with unsynchronized `_last_request_time` read/write. This is a **pre-existing** characteristic (already true the moment two concurrent Flask requests both resolve a POI, e.g. two simultaneous Phase 3 searches) — Stage 1 increases how often it's exercised concurrently (a background enrichment thread can now overlap with a foreground search request), but does not introduce the underlying condition. Left unmodified per the explicit instruction not to touch OSM resolver internals beyond what's required — the worst case is an occasional sub-second violation of a *courtesy* rate limit, not a correctness bug, and fixing it would mean editing Phase 1 code Stage 1 was explicitly told to leave alone.
- **Daemon threads**: enrichment threads are daemons, so an app restart/shutdown does not hang waiting for them - the tradeoff (an abandoned mid-run enrichment, recoverable via §7's backfill path) is disclosed, not hidden.

## 10. Tests

**16 new tests, all passing** (full suite: **221/221**, up from 205 at the end of Phase 4.0):

- `test_property_services.py` (new file, 6 tests): `claim_nearby_facilities_enrichment()` — succeeds for a never-enriched/completed/failed property, fails when already pending (and leaves the existing pending record untouched), fails for a nonexistent property, and a sequential two-claim race where only the first succeeds.
- `test_nearby_facility_service.py` (+10): `build_pending_metadata()` shape; registration does **not** wait for the full enrichment (proven with a controllable `threading.Event`, not a sleep/timing guess); the property is marked `"pending"` synchronously before the thread finishes; the worker receives its real dependencies and transitions `pending → completed`; `pending → partial`; `pending → failed`; a worker exception is contained and recorded; a second call against an already-`"pending"` property starts no second worker; a claim-write exception starts no worker and doesn't raise.

Existing tests (Phase 1–4.0, all suites) confirmed unaffected: **205 pre-existing tests still pass unmodified.**

## Files changed
- `routes/property_routes.py` — one call site changed (`enrich_property_nearby_facilities` → `start_background_enrichment`), comment updated
- `services/nearby_facility_service.py` — added `STATUS_*` constants, `build_pending_metadata()`, `start_background_enrichment()`, `_run_enrichment_in_background()`; the existing synchronous core is untouched
- `services/property_services.py` — added `claim_nearby_facilities_enrichment()`; every existing method untouched
- `scripts/backfill_nearby_facilities.py` — `--retry-failed` now also recovers stale `"pending"` entries (with a staleness guard, §7)
- `test_nearby_facility_service.py` — +10 tests

## Files created
- `test_property_services.py` (6 tests)
- `scripts/stage1_performance_measurement.py` (the live before/after measurement in §8)
- `docs/PHASE_4_STAGE_1_REGISTRATION_PERFORMANCE.md` (this file)

## Files explicitly NOT changed
- `services/mappls_service.py`, `services/osm_location_service.py` (zero diff — confirmed via `git diff --stat`)
- `services/nlp/*`, `services/search_orchestration.py`, `routes/search_routes.py`, `templates/rentals.html`, `evaluation/nlp/**`
- `services/property_services.py`'s `ranked_search()`, `filtered_search()`, and every other pre-existing method
- `implementation_changes.docx`

## Confirmation
Registration remains fully responsive under this change (0.036s measured), Phase 1/2/2.5/3/3.2 behavior is unaffected (zero diff on every file those phases own), and no new infrastructure dependency (Celery/Redis/RabbitMQ/task queue) was introduced — Python's stdlib `threading` only, exactly as instructed.
