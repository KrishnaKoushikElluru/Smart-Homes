"""
Phase 4.0: nearby-facility enrichment for a registered property.

    property.location.coordinates (already stored, required at
    submission - see routes/property_routes.py's submit_listing())
            |
            v
    for each facility category (see FACILITY_CATEGORIES):
            |
            v
    Mappls Nearby search (services.mappls_service.find_nearby_places)
    -> candidate places, each with MAPPLS' OWN provider-computed
       distance_m from the property's coordinates - verified live
       against this account (Sep 2026): this endpoint does NOT return
       latitude/longitude for a result (same limitation already
       documented in services/mappls_service.py)
            |
            v
    normalize + de-duplicate (by Mappls eLoc within each category)
            |
            v
    persist nearby_facilities[] + nearby_facilities_metadata on the
    property document via the EXISTING PropertyService.get_property()/
    update_property() methods - no new MongoDB access pattern

ARCHITECTURE DECISION (superseding an earlier version of this module):
Mappls Nearby is the SOLE discovery/distance provider for nearby
facilities - there is no OSM/Nominatim coordinate-resolution step. An
earlier version of this module best-effort-resolved each facility's
lat/lon via services.osm_location_service.OSMLocationService, on the
theory that a future "property within 1 km of a school" geospatial
query might want it. That capability was never built: every existing
and planned nearby-facility search (see
services/search_orchestration.py's build_mongo_filter() and
_attach_matched_nearby_facilities()) filters and ranks purely on
`category` + Mappls' own `distance_m`, never on coordinates - "we
don't know exactly where this is on a map" was never actually a
problem anywhere downstream, only "how far is it", and Mappls already
tells us that directly. The OSM step also turned out to be actively
harmful: a facility OSM couldn't resolve was stored with a literal
`coordinates: None`, which breaks MongoDB's 2dsphere index key
extraction for the WHOLE nearby_facilities[] array on write (confirmed
live - see this module's git history). Removing the step removes that
failure mode entirely, not just works around it. This module's own
required inputs are unchanged: property_service and mappls_api_key -
no osm_service parameter anywhere in this file anymore.

This module NEVER raises. Property registration must succeed
regardless of what happens here (Mappls down, malformed provider data,
zero results) - every failure mode is caught and recorded in
nearby_facilities_metadata instead, never silently swallowed and never
allowed to look like a real "no facilities found" result. See
enrich_property_nearby_facilities()'s docstring.

NOT implemented here (deliberately, per this phase's scope): natural-
language "gym nearby" search, ranking/recommendation, road/walking/
driving distance, a scheduled refresh job. This module only builds and
maintains the data those future phases would read.

STAGE 1 ADDITION - BACKGROUND EXECUTION
----------------------------------------
enrich_property_nearby_facilities() itself is unchanged (still fully
synchronous, still fully testable/callable directly - e.g. by
scripts/backfill_nearby_facilities.py). What's new is
start_background_enrichment(), which runs it on a plain
threading.Thread rather than blocking the caller - see that function's
own docstring for the full design (why a bare thread rather than
Celery/RQ/etc, how "at most one worker per property" is guaranteed,
why no Flask request/app context is needed or used inside the thread).
No Celery/Redis/RabbitMQ/task-queue dependency was introduced - Python
stdlib threading only.
"""

from __future__ import annotations

import re
import threading
import unicodedata
from datetime import datetime, timezone
from typing import Optional

from services import mappls_service


# ============================================================
# ENRICHMENT STATUS VALUES
#
# Named here so both the synchronous core (below) and the Stage 1
# background-worker orchestration (further below) refer to the exact
# same literal values - "pending" specifically means "a worker has
# been started/claimed for this property but hasn't finished yet",
# never "no facilities were found" (see build_pending_metadata()).
# ============================================================

STATUS_PENDING = "pending"
STATUS_COMPLETED = "completed"
STATUS_PARTIAL = "partial"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

# ============================================================
# FACILITY TAXONOMY
#
# Canonical SmartHomes facility category -> the free-text keyword sent
# to Mappls' Nearby Search API (services.mappls_service.find_nearby_places).
# This is a category-to-search-term mapping (a taxonomy), NOT a
# business-name alias table - it never says "this specific business IS
# a gym", only "search Mappls for the word 'gym' to find gyms". Mappls
# itself identifies the actual matching entities.
#
# Extending the taxonomy later is just adding one more entry here - no
# other code needs to change.
# ============================================================

FACILITY_CATEGORIES: dict = {
    "gym": "gym",
    "hospital": "hospital",
    "school": "school",
    "college": "college",
    "supermarket": "supermarket",
    "pharmacy": "pharmacy",
    "restaurant": "restaurant",
    "bank": "bank",
    "atm": "atm",
    "metro_station": "metro station",
    "railway_station": "railway station",
    "bus_stop": "bus stop",
    "shopping_mall": "shopping mall",
    "park": "park",
    "police_station": "police station",
    "fire_station": "fire station",
    "petrol_station": "petrol pump",
}


# ============================================================
# CONFIGURATION DEFAULTS
#
# Real values are read from environment variables in app.py and passed
# in explicitly by the caller (matching services/osm_location_service.py's
# convention: this module never reads os.environ or current_app itself).
# ============================================================

# A real-estate-relevant "walkable/nearby" radius - deliberately tighter
# than Phase 3's SEARCH_POI_RADIUS_KM (5 km), which answers a different
# question ("how far will an ambiguous landmark's area spread affect a
# property SEARCH") than this one ("what counts as a nearby AMENITY for
# someone evaluating a home").
DEFAULT_RADIUS_KM = 2.0

# How many facilities to keep (after de-duplication) per category. Bounds
# document size and keeps the common case (a handful of genuinely close
# options) without silently dropping category coverage.
DEFAULT_MAX_RESULTS_PER_CATEGORY = 5


# ============================================================
# NORMALIZATION / VALIDATION
# ============================================================

def _is_valid_coordinate(latitude, longitude) -> bool:
    try:
        latitude = float(latitude)
        longitude = float(longitude)
    except (TypeError, ValueError):
        return False
    return -90 <= latitude <= 90 and -180 <= longitude <= 180


def _normalize_name_for_dedup(name: Optional[str]) -> str:
    """Lowercase, strip accents/punctuation/whitespace - used ONLY as a
    fallback dedup key when Mappls' own eLoc is missing (rare). Never
    used to merge two records just because their names look similar
    once normalized THIS aggressively is not attempted - see
    _dedupe_places()'s docstring."""
    if not name:
        return ""
    text = unicodedata.normalize("NFKD", name)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return text.strip()


def _normalize_place(raw_place: dict, category: str, radius_m: float) -> Optional[dict]:
    """Turns one services.mappls_service.find_nearby_places() place dict
    into this module's internal facility shape. Returns None for a
    malformed entry (no usable name) rather than raising - a single bad
    record must never take down the rest of a category's results."""

    if not isinstance(raw_place, dict):
        return None

    name = (raw_place.get("place_name") or "").strip()

    if not name:
        return None

    distance_m = raw_place.get("distance_m")

    try:
        distance_m = float(distance_m) if distance_m is not None else None
    except (TypeError, ValueError):
        distance_m = None

    return {
        "name": name,
        "category": category,
        "address": raw_place.get("place_address") or None,
        "distance_m": distance_m,
        "source": "mappls",
        "provider_id": raw_place.get("eloc") or None,
        "provider_type": raw_place.get("type") or None,
        "fetched_at": datetime.now(timezone.utc),
        "search_radius_m": radius_m,
    }


def _dedupe_places(places: list) -> list:
    """De-duplicates a list of normalized facility dicts (already all
    the same category) using stable provider identity (Mappls eLoc)
    first, falling back to normalized-name-only when eLoc is absent.
    Never merges two DIFFERENT businesses just because their names are
    similar - the fallback key is exact-match-after-normalization, not
    fuzzy matching, and is only reached when the provider gave us no
    stable identity to rely on at all."""

    seen = set()
    deduped = []

    for place in places:

        provider_id = place.get("provider_id")

        if provider_id:
            key = ("id", provider_id)
        else:
            key = ("name", _normalize_name_for_dedup(place.get("name")))

        if key in seen:
            continue

        seen.add(key)
        deduped.append(place)

    return deduped


# ============================================================
# PER-CATEGORY DISCOVERY
# ============================================================

def _discover_category(
    category: str,
    keyword: str,
    ref_location: str,
    radius_m: float,
    mappls_api_key,
    max_results: int,
) -> tuple:
    """Returns (places, error). `error` is a short human-readable
    string if the Mappls call for THIS category failed outright (never
    raises); `places` is always a list (possibly empty)."""

    mappls_result = mappls_service.find_nearby_places(
        keyword, ref_location, radius_m, mappls_api_key
    )

    if mappls_result["status"] == "error":
        return [], mappls_result.get("error") or "Mappls nearby search failed."

    if mappls_result["status"] == "no_match":
        return [], None

    normalized = [
        _normalize_place(raw, category, radius_m)
        for raw in mappls_result["places"]
    ]
    normalized = [p for p in normalized if p is not None]

    deduped = _dedupe_places(normalized)

    # Mappls already returns results ordered by its own relevance/
    # distance ranking (see orderIndex in the raw response) - sorting
    # again by the provider distance we trust keeps this deterministic
    # even if that assumption ever changes.
    deduped.sort(key=lambda p: (p["distance_m"] is None, p["distance_m"] or 0))

    return deduped[:max_results], None


# ============================================================
# MAIN ENTRY POINT
# ============================================================

def enrich_property_nearby_facilities(
    property_id,
    property_service,
    mappls_api_key,
    categories: Optional[dict] = None,
    radius_km: Optional[float] = None,
    max_results_per_category: Optional[int] = None,
) -> dict:
    """
    Enriches ONE property with nearby-facility data and persists it via
    the existing PropertyService.update_property() - no new MongoDB
    access pattern. Reusable: this same function is meant to be called
    both right after a property is created (routes/property_routes.py)
    and, later, by a standalone backfill/refresh script/job (see
    docs/PHASE_4_0_NEARBY_FACILITY_ENRICHMENT.md) - it does not assume
    anything about WHEN or WHY it's being called.

    categories: {category_key: mappls_keyword, ...} - defaults to
      FACILITY_CATEGORIES (all of them). A caller may pass a subset for
      a partial re-enrichment.

    Never raises. Returns the same metadata dict that gets stored as
    the property's "nearby_facilities_metadata" field, so a caller can
    inspect what happened without a second read.

    Enrichment is skipped (status="skipped") - NOT attempted, NOT
    marked "failed" - when the property doesn't exist or has no valid
    coordinates yet. That distinction matters: "failed" implies an
    external system let us down; "skipped" means there was nothing
    valid to enrich from in the first place.
    """

    categories = categories or FACILITY_CATEGORIES
    radius_km = radius_km if radius_km is not None else DEFAULT_RADIUS_KM
    max_results_per_category = (
        max_results_per_category
        if max_results_per_category is not None
        else DEFAULT_MAX_RESULTS_PER_CATEGORY
    )

    radius_m = radius_km * 1000.0

    metadata = {
        "status": "failed",
        "source": "mappls",
        "radius_m": radius_m,
        "enriched_at": datetime.now(timezone.utc),
        "facility_count": 0,
        "categories_requested": sorted(categories.keys()),
        "categories_failed": {},
        "error": None,
    }

    def _persist_early_exit(current_metadata):
        # Every early return below (property couldn't be loaded, not
        # found, or has no/invalid coordinates) used to return without
        # writing anything to MongoDB - harmless for a direct
        # synchronous caller (e.g. scripts/backfill_nearby_facilities.py),
        # but start_background_enrichment() already writes a "pending"
        # claim via claim_nearby_facilities_enrichment() BEFORE this
        # function ever runs. Leaving that claim unresolved strands the
        # property at "pending" forever - the exact stuck-forever
        # symptom this module's own Stage 1 docstring exists to avoid.
        # Persisting here (best-effort - this function must never
        # raise) closes that gap for every caller uniformly, matching
        # this function's own docstring: "Returns the same metadata
        # dict that gets stored as the property's
        # 'nearby_facilities_metadata' field."
        try:
            property_service.update_property(property_id, {
                "nearby_facilities": [],
                "nearby_facilities_metadata": current_metadata,
            })
        except Exception:
            pass
        return current_metadata

    try:
        property_document = property_service.get_property(property_id)
    except Exception as exc:
        metadata["error"] = f"Could not load property: {exc}"
        return _persist_early_exit(metadata)

    if not property_document:
        metadata["status"] = "skipped"
        metadata["error"] = "Property not found."
        return _persist_early_exit(metadata)

    location = property_document.get("location") or {}
    coordinates_field = location.get("coordinates") or {}
    coordinate_values = coordinates_field.get("coordinates") or []

    if len(coordinate_values) != 2:
        metadata["status"] = "skipped"
        metadata["error"] = "Property has no coordinates to enrich from."
        return _persist_early_exit(metadata)

    longitude, latitude = coordinate_values[0], coordinate_values[1]

    if not _is_valid_coordinate(latitude, longitude):
        metadata["status"] = "skipped"
        metadata["error"] = "Property coordinates are invalid."
        return _persist_early_exit(metadata)

    ref_location = f"{latitude},{longitude}"

    all_facilities = []
    categories_failed = {}

    for category, keyword in categories.items():

        places, error = _discover_category(
            category,
            keyword,
            ref_location,
            radius_m,
            mappls_api_key,
            max_results_per_category,
        )

        all_facilities.extend(places)

        if error:
            categories_failed[category] = error

    metadata["facility_count"] = len(all_facilities)
    metadata["categories_failed"] = categories_failed

    if not categories_failed:
        metadata["status"] = "completed"
    elif len(categories_failed) < len(categories):
        metadata["status"] = "partial"
    else:
        metadata["status"] = "failed"
        metadata["error"] = "All facility categories failed to resolve."

    try:

        property_service.update_property(property_id, {
            "nearby_facilities": all_facilities,
            "nearby_facilities_metadata": metadata,
        })

    except Exception as exc:
        # The discovery work itself succeeded but persisting it failed
        # (e.g. a transient Mongo error) - report that honestly rather
        # than claiming "completed" when nothing was actually saved.
        metadata["status"] = "failed"
        metadata["error"] = f"Enrichment data could not be saved: {exc}"

    return metadata


# ============================================================
# STAGE 1: BACKGROUND EXECUTION
#
# Everything below runs the exact same enrich_property_nearby_facilities()
# above, just off of the HTTP request thread. Nothing about the
# discovery/normalize/dedupe/persist logic changes - this is purely an
# execution-model addition.
# ============================================================

def build_pending_metadata(categories: Optional[dict] = None, radius_km: Optional[float] = None) -> dict:
    """Builds the "pending" nearby_facilities_metadata dict written
    immediately after property creation, before any external API call
    is made - so a property is NEVER left with no
    nearby_facilities_metadata field at all while enrichment is in
    flight (that would be indistinguishable from "never enriched" -
    see enrich_property_nearby_facilities()'s own "skipped" vs "failed"
    distinction for the same reasoning applied to a different case).

    "queued_at" (when the worker was started) is kept separate from
    "enriched_at" (when it actually finished - left None while
    pending) specifically so a stuck/crashed pending entry can be told
    apart from a normal in-progress one later (e.g. by a future
    monitoring/retry pass)."""

    categories = categories or FACILITY_CATEGORIES
    radius_km = radius_km if radius_km is not None else DEFAULT_RADIUS_KM

    return {
        "status": STATUS_PENDING,
        "source": "mappls",
        "radius_m": radius_km * 1000.0,
        "enriched_at": None,
        "queued_at": datetime.now(timezone.utc),
        "facility_count": 0,
        "categories_requested": sorted(categories.keys()),
        "categories_failed": {},
        "error": None,
    }


def _run_enrichment_in_background(
    property_id,
    property_service,
    mappls_api_key,
    categories,
    radius_km,
    max_results_per_category,
) -> None:
    """The actual thread target. enrich_property_nearby_facilities() is
    already documented never to raise - this try/except is an
    intentional LAST-RESORT safety net for the one execution context
    where an uncaught exception truly has nowhere sane to go: by the
    time this runs, the HTTP request that triggered it has already
    returned its response, so there is no Flask request context, no
    caller waiting, and no framework-level error handler that could
    ever see it. An uncaught exception on a background thread does not
    crash the Flask process (Python just logs it and the thread dies),
    but it WOULD leave the property stuck at status="pending" forever
    with no explanation - this converts that into an honest "failed"
    with a reason instead."""

    try:

        enrich_property_nearby_facilities(
            property_id,
            property_service,
            mappls_api_key,
            categories=categories,
            radius_km=radius_km,
            max_results_per_category=max_results_per_category,
        )

    except Exception as exc:

        try:

            property_service.update_property(property_id, {
                "nearby_facilities": [],
                "nearby_facilities_metadata": {
                    "status": STATUS_FAILED,
                    "source": "mappls",
                    "radius_m": (radius_km if radius_km is not None else DEFAULT_RADIUS_KM) * 1000.0,
                    "enriched_at": datetime.now(timezone.utc),
                    "facility_count": 0,
                    "categories_requested": sorted((categories or FACILITY_CATEGORIES).keys()),
                    "categories_failed": {},
                    "error": f"Background enrichment worker crashed: {exc}",
                },
            })

        except Exception:
            # Genuinely nothing more this can safely do - even the
            # attempt to record the failure itself failed (e.g. Mongo
            # is down). Silently giving up here is correct: there is
            # no request/caller left to report to, and raising would
            # only produce the exact unhandled-background-thread
            # exception this function exists to prevent.
            pass


def start_background_enrichment(
    property_id,
    property_service,
    mappls_api_key,
    categories: Optional[dict] = None,
    radius_km: Optional[float] = None,
    max_results_per_category: Optional[int] = None,
):
    """
    Stage 1 entry point: starts nearby-facility enrichment for
    property_id on a plain daemon thread and returns IMMEDIATELY,
    without waiting for Mappls/MongoDB. The caller (typically
    routes/property_routes.py, right after create_property()) should
    call this and then proceed straight to its own response - it never
    needs to await anything here.

    WHY A BARE THREAD, NOT CELERY/RQ/A TASK QUEUE: this project has no
    message-broker/worker infrastructure today, and introducing one is
    explicitly out of scope for this stage. A single background
    thread per registration is proportionate to the actual workload
    (one property, a bounded number of external calls, finishing in
    well under a minute - see docs/PHASE_4_0_NEARBY_FACILITY_ENRICHMENT.md
    for measured timings) and needs zero new infrastructure. The
    tradeoff, disclosed rather than hidden: if the whole process
    restarts while a thread is mid-run, that one enrichment is
    abandoned (left at "pending") rather than resumed - acceptable for
    a best-effort enrichment layer, and recoverable later (a future
    pass can look for stuck "pending" entries older than some
    threshold and re-run them; not built in this stage).

    EXPLICIT DEPENDENCY INJECTION, NOT FLASK CONTEXT: property_service
    and mappls_api_key are passed in as plain arguments (matching
    enrich_property_nearby_facilities()'s own existing convention) and
    are the ONLY things the spawned thread touches - it never reads
    current_app, request, g, or any other request-scoped Flask object,
    which would not exist by the time a background thread actually
    runs its work (the request that spawned it may well have already
    finished and its context been torn down).
    property_service wraps a single shared pymongo Collection/MongoClient
    that the whole app (across concurrent requests) already relies on
    being safe to use concurrently - pymongo's MongoClient is documented
    thread-safe, so no new thread-safety assumption is introduced here.

    AT-MOST-ONE-WORKER-PER-PROPERTY: before starting the thread, this
    function atomically claims the property via
    PropertyService.claim_nearby_facilities_enrichment() - a single
    conditional MongoDB update that only succeeds if the property isn't
    ALREADY marked "pending". If the claim fails (someone/something
    else already has it pending), NO thread is started - this holds
    even across multiple app processes, not just multiple threads
    within one, since the guarantee comes from MongoDB's own atomic
    single-document update rather than an in-process lock.

    Returns the started threading.Thread, or None if the claim failed
    (enrichment was already pending for this property) or if the claim
    write itself failed (treated the same as "don't start a worker" -
    the property's metadata is left however claim_nearby_facilities_enrichment()
    left it, and the caller's registration response is completely
    unaffected either way).
    """

    pending_metadata = build_pending_metadata(categories, radius_km)

    try:
        claimed = property_service.claim_nearby_facilities_enrichment(
            property_id, pending_metadata
        )
    except Exception:
        # Marking "pending" is itself best-effort - if even this fails
        # (e.g. a transient Mongo error), do not start a worker with no
        # claim recorded (that would defeat the whole point of this
        # guard) and do not let it affect the caller's response either.
        return None

    if not claimed:
        return None

    thread = threading.Thread(
        target=_run_enrichment_in_background,
        args=(
            property_id,
            property_service,
            mappls_api_key,
            categories,
            radius_km,
            max_results_per_category,
        ),
        daemon=True,
        name=f"nearby-facility-enrichment-{property_id}",
    )
    thread.start()

    return thread


# ============================================================
# STAGE 2: AUTOMATIC RETRY SWEEP
#
# start_background_enrichment()'s own docstring already disclosed this
# gap: "if the whole process restarts while a thread is mid-run, that
# one enrichment is abandoned (left at 'pending')... recoverable later
# (a future pass can look for stuck 'pending' entries older than some
# threshold and re-run them; not built in this stage)." That manual
# recovery pass WAS built (scripts/backfill_nearby_facilities.py
# --retry-failed), but it only runs when a human remembers to invoke
# it. This section is the automatic version of the exact same idea -
# a periodic sweep, started once at app startup, that finds the same
# "never attempted / failed / stale pending" candidates
# (PropertyService.find_stale_nearby_facility_candidates() - the
# SAME query the manual script now also delegates to, so the two can
# never disagree on what counts as stale) and retries each one via
# the EXISTING start_background_enrichment() - every safety guarantee
# that function already has (atomic per-property claim, never raises,
# never blocks the caller) applies here unchanged. No new MongoDB
# access pattern, no new task-queue dependency - still plain stdlib
# threading, matching this module's existing convention.
# ============================================================

# How old a "pending" entry must be before it's treated as abandoned
# rather than a real, currently-running worker. Shared by the manual
# --retry-failed script and this automatic sweep - see
# PropertyService.find_stale_nearby_facility_candidates()'s docstring
# for why this matters (racing a genuinely-running worker would defeat
# the atomic claim guard). Real enrichment finishes in well under a
# minute even for all 17 categories (docs/PHASE_4_0_NEARBY_FACILITY_ENRICHMENT.md) -
# 10 minutes is a generous, deliberately conservative margin, not a
# tuned value.
STALE_PENDING_THRESHOLD_MINUTES = 10

# How often the periodic sweep runs, and how many stale candidates it
# will start a worker for in a single pass - bounded so a sudden burst
# of stale properties (e.g. right after a long outage) doesn't fire
# off an unbounded number of concurrent Mappls calls at once. Neither
# value is tuned against production data - both are configurable via
# app.py's NEARBY_FACILITY_SWEEP_INTERVAL_MINUTES/_BATCH_LIMIT env
# vars for exactly that reason.
DEFAULT_SWEEP_INTERVAL_MINUTES = 15
DEFAULT_SWEEP_BATCH_LIMIT = 20

# Delay before the FIRST sweep pass after the thread starts - gives
# the app's own startup (MongoDB connection, index creation) a moment
# to finish before the sweep adds its own MongoDB query on top.
SWEEP_STARTUP_GRACE_SECONDS = 30


def run_enrichment_sweep(
    property_service,
    mappls_api_key,
    radius_km: Optional[float] = None,
    stale_pending_minutes: int = STALE_PENDING_THRESHOLD_MINUTES,
    limit: int = DEFAULT_SWEEP_BATCH_LIMIT,
) -> list:
    """One pass of the automatic sweep. Returns the list of property_ids
    a worker was actually started for - a candidate that got claimed by
    someone/something else between selection and claim (e.g. a real
    registration-time worker that started in that same instant) is
    silently skipped, exactly as start_background_enrichment() already
    documents; this never raises for that case or any other.

    Never raises: a failure finding candidates (e.g. a transient Mongo
    error) is treated the same as "nothing to do this pass" - the next
    scheduled sweep will simply try again."""

    try:
        candidate_ids = property_service.find_stale_nearby_facility_candidates(
            stale_pending_minutes, limit=limit
        )
    except Exception:
        return []

    started = []

    for property_id in candidate_ids:

        thread = start_background_enrichment(
            property_id,
            property_service,
            mappls_api_key,
            radius_km=radius_km,
        )

        if thread is not None:
            started.append(property_id)

    return started


def start_periodic_enrichment_sweep(
    property_service,
    mappls_api_key,
    radius_km: Optional[float] = None,
    interval_minutes: int = DEFAULT_SWEEP_INTERVAL_MINUTES,
    stale_pending_minutes: int = STALE_PENDING_THRESHOLD_MINUTES,
    batch_limit: int = DEFAULT_SWEEP_BATCH_LIMIT,
    stop_event: Optional[threading.Event] = None,
):
    """Starts a daemon thread that runs run_enrichment_sweep() once
    (after SWEEP_STARTUP_GRACE_SECONDS) and then every interval_minutes,
    for the lifetime of the process - the automatic counterpart to
    manually re-running scripts/backfill_nearby_facilities.py
    --retry-failed. Intended to be called once, at app startup (see
    app.py's MONGODB section), never per-request.

    stop_event: a threading.Event a caller can set() to stop the loop
    cleanly - used by tests to avoid a real sleeping background thread
    outliving the test. The real app never passes one; the thread is
    daemon=True and simply dies with the process on shutdown.

    Returns (thread, stop_event) - a caller that wants to stop the
    sweep later (tests only) calls stop_event.set()."""

    stop_event = stop_event if stop_event is not None else threading.Event()

    def _loop():

        if stop_event.wait(SWEEP_STARTUP_GRACE_SECONDS):
            return

        while True:

            try:
                run_enrichment_sweep(
                    property_service,
                    mappls_api_key,
                    radius_km=radius_km,
                    stale_pending_minutes=stale_pending_minutes,
                    limit=batch_limit,
                )
            except Exception:
                # A sweep pass failing entirely must never kill the
                # periodic loop itself - the next scheduled pass will
                # simply try again.
                pass

            if stop_event.wait(interval_minutes * 60):
                return

    thread = threading.Thread(
        target=_loop,
        daemon=True,
        name="nearby-facility-enrichment-sweep",
    )
    thread.start()

    return thread, stop_event


# ============================================================
# DISPLAY (property-details "Nearby Amenities" section -
# routes/property_routes.py's property_details())
#
# Presentation-only: groups a property's ALREADY-STORED
# nearby_facilities[] (written by enrich_property_nearby_facilities()
# above) for display. Never calls Mappls/any provider, never touches
# MongoDB, never invents a facility. Reuses FACILITY_CATEGORIES as the
# ONLY taxonomy - FACILITY_CATEGORY_LABELS below is purely a display
# label for each of those same 17 keys, not a second taxonomy.
# ============================================================

FACILITY_CATEGORY_LABELS: dict = {
    "gym": "Gyms",
    "hospital": "Hospitals",
    "school": "Schools",
    "college": "Colleges",
    "supermarket": "Supermarkets",
    "pharmacy": "Pharmacies",
    "restaurant": "Restaurants",
    "bank": "Banks",
    "atm": "ATMs",
    "metro_station": "Metro Stations",
    "railway_station": "Railway Stations",
    "bus_stop": "Bus Stops",
    "shopping_mall": "Shopping Malls",
    "park": "Parks",
    "police_station": "Police Stations",
    "fire_station": "Fire Stations",
    "petrol_station": "Petrol Stations",
}


def _format_distance(distance_m) -> Optional[str]:
    """Human-friendly distance label from a stored distance_m - "134 m"
    below 1 km, "1.2 km" / "2 km" at or above (never ".0" on a whole
    number of km). Returns None for missing/invalid/negative input -
    callers must never render a fabricated or misleading distance for
    that case (this feature's own explicit requirement), not "0 m" or
    "unknown"."""

    try:
        distance_m = float(distance_m)
    except (TypeError, ValueError):
        return None

    if distance_m < 0:
        return None

    rounded_m = round(distance_m)

    if rounded_m < 1000:
        return f"{rounded_m} m"

    km = round(distance_m / 1000.0, 1)

    if km == int(km):
        return f"{int(km)} km"

    return f"{km:g} km"


def build_nearby_facilities_display(property_item: Optional[dict]) -> dict:
    """Builds the property-details page's "Nearby Amenities" view model
    from a property document's own stored nearby_facilities[] /
    nearby_facilities_metadata (never re-fetches anything). Never
    raises - a malformed/legacy document simply produces the most
    benign result it can.

    Returns {"status": ..., "groups": [...]}:

      "status" is one of:
        "unavailable" - no nearby_facilities_metadata at all (a
          property registered before this feature existed, or
          otherwise never enriched). The caller should render NOTHING
          - this is not an error state, just "no data to show".
        "pending" - enrichment is queued/in progress (STATUS_PENDING).
        "failed" - enrichment was attempted and failed for every
          category (STATUS_FAILED). Never rendered as if it were an
          empty-but-successful result.
        "skipped" - enrichment was never attempted (e.g. the property
          had no valid coordinates at the time) - STATUS_SKIPPED.
        "empty" - enrichment genuinely succeeded (completed/partial)
          but found zero facilities in any category.
        "ready" - enrichment succeeded and there is at least one
          facility to show; see "groups".

      "groups" (only non-empty when status == "ready"): a list of
        {"category": key, "label": display label, "facilities": [...]}
        - one entry per category that has at least one stored
        facility, in FACILITY_CATEGORIES' own canonical order (a
        category with zero facilities is omitted entirely, never
        rendered as an empty heading - this feature's own explicit
        requirement). Facilities within a category are sorted closest
        first (missing distance sorts last, never dropped). Each
        facility is {"name", "address" (may be None), "distance_m"
        (may be None), "distance_label" (human string, or None when
        distance_m is missing/invalid - the caller must not show a
        distance in that case)}. Never includes source/provider_id/
        provider_type/fetched_at/search_radius_m - internal fields
        this display layer has no use for."""

    if not isinstance(property_item, dict):
        return {"status": "unavailable", "groups": []}

    metadata = property_item.get("nearby_facilities_metadata")

    if not isinstance(metadata, dict) or not metadata.get("status"):
        return {"status": "unavailable", "groups": []}

    enrichment_status = metadata["status"]

    if enrichment_status == STATUS_PENDING:
        return {"status": "pending", "groups": []}

    if enrichment_status == STATUS_FAILED:
        return {"status": "failed", "groups": []}

    if enrichment_status == STATUS_SKIPPED:
        return {"status": "skipped", "groups": []}

    # STATUS_COMPLETED or STATUS_PARTIAL from here - group whatever was
    # actually stored (a "partial" run's successful categories are
    # still genuine, real data, just not every category was attempted).
    nearby_facilities = property_item.get("nearby_facilities")

    if not isinstance(nearby_facilities, list):
        nearby_facilities = []

    by_category: dict = {}

    for facility in nearby_facilities:

        if not isinstance(facility, dict):
            continue

        name = (facility.get("name") or "").strip()

        if not name:
            continue

        category = facility.get("category")

        if category not in FACILITY_CATEGORIES:
            continue

        distance_m = facility.get("distance_m")

        try:
            distance_m = float(distance_m) if distance_m is not None else None
        except (TypeError, ValueError):
            distance_m = None

        by_category.setdefault(category, []).append({
            "name": name,
            "address": facility.get("address") or None,
            "distance_m": distance_m,
            "distance_label": _format_distance(distance_m),
        })

    groups = []

    for category in FACILITY_CATEGORIES:  # canonical, stable display order

        facilities = by_category.get(category)

        if not facilities:
            continue

        facilities.sort(key=lambda f: (f["distance_m"] is None, f["distance_m"] or 0))

        groups.append({
            "category": category,
            "label": FACILITY_CATEGORY_LABELS.get(category, category),
            "facilities": facilities,
        })

    if not groups:
        return {"status": "empty", "groups": []}

    return {"status": "ready", "groups": groups}
