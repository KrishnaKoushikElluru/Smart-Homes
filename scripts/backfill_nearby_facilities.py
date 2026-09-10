"""
Phase 4.0 - controlled backfill for existing properties that predate
nearby-facility enrichment (services/nearby_facility_service.py).

This script is NEVER run automatically - it is a standalone, manually
invoked command. It is intentionally NOT imported by app.py or called
from anywhere in the request-handling path.

Safe / restartable by design:
  - Only processes properties with no nearby_facilities_metadata at all
    (i.e. genuinely never enriched) unless --retry-failed is passed, in
    which case properties whose last attempt ended in "failed", AND
    "pending" properties stuck for more than --stale-pending-minutes
    (default 10 - a Stage 1 background worker that started but never
    finished, e.g. the process restarted mid-run), are included too.
    A "pending" entry younger than that is deliberately left alone -
    it might be a real, currently-running registration-time worker,
    and touching it here would race that worker and defeat the whole
    point of the atomic per-property claim (see
    services/property_services.py's claim_nearby_facilities_enrichment()).
    "completed"/"partial" properties are always skipped - re-enriching
    those is a deliberate, separate re-run (see --force), not something
    a routine backfill should silently repeat.
  - Processes properties ONE AT A TIME, committing each property's
    result to MongoDB immediately (via the same
    enrich_property_nearby_facilities() the live registration flow
    uses) - if the script is interrupted (Ctrl+C, crash, rate limit),
    everything already processed stays enriched, and re-running the
    script picks up exactly where it left off (already-completed
    properties are skipped, as above).
  - --limit bounds how many properties a single run will touch, so a
    large backfill can be run in controlled batches rather than one
    long unattended pass against live external APIs.
  - --dry-run lists what WOULD be processed without calling Mappls/OSM
    or writing anything.

Usage:
    python scripts/backfill_nearby_facilities.py --dry-run
    python scripts/backfill_nearby_facilities.py --limit 20
    python scripts/backfill_nearby_facilities.py --retry-failed --limit 20
    python scripts/backfill_nearby_facilities.py --force --limit 5

Run from the project root (imports the real app.py for its already-
configured MongoDB/Mappls/OSM services - same connection/config the
live app uses, nothing reimplemented here).
"""

import argparse
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402
from services import nearby_facility_service  # noqa: E402


# A property whose background worker (Stage 1 -
# services/nearby_facility_service.start_background_enrichment())
# started less than this long ago might still be legitimately running
# right now - re-running it here too would race the live worker and
# defeat the whole point of the atomic claim guard. Only a "pending"
# entry OLDER than this is treated as abandoned/stuck (e.g. the process
# restarted mid-run) and eligible for --retry-failed. Real enrichment
# has been observed to finish in well under a minute even for all 17
# categories (see docs/PHASE_4_0_NEARBY_FACILITY_ENRICHMENT.md) - 10
# minutes is a generous, deliberately conservative margin, not a tuned
# value.
STALE_PENDING_THRESHOLD_MINUTES = 10


def _select_properties(collection, retry_failed: bool, force: bool, limit, stale_pending_minutes: int) -> list:

    if force:
        query = {}

    elif retry_failed:
        # Also picks up "pending" entries (Stage 1) - but ONLY ones
        # older than stale_pending_minutes, so this can never collide
        # with a background worker that is genuinely still running
        # right now (that would recreate exactly the duplicate-worker
        # race the atomic claim in
        # PropertyService.claim_nearby_facilities_enrichment() exists
        # to prevent). A "pending" property with no queued_at at all
        # (shouldn't happen via the real registration flow, but
        # defensively handled) is treated as stale too - there's no
        # way to tell how old it is, so it's safer to assume abandoned
        # than to leave it stuck forever.
        stale_cutoff = datetime.now(timezone.utc) - timedelta(minutes=stale_pending_minutes)

        query = {
            "$or": [
                {"nearby_facilities_metadata": {"$exists": False}},
                {"nearby_facilities_metadata.status": "failed"},
                {
                    "nearby_facilities_metadata.status": "pending",
                    "$or": [
                        {"nearby_facilities_metadata.queued_at": {"$lt": stale_cutoff}},
                        {"nearby_facilities_metadata.queued_at": {"$exists": False}},
                    ],
                },
            ]
        }

    else:
        query = {"nearby_facilities_metadata": {"$exists": False}}

    cursor = collection.find(query, {"_id": 1})

    if limit:
        cursor = cursor.limit(limit)

    return [str(doc["_id"]) for doc in cursor]


def main():

    parser = argparse.ArgumentParser(
        description="Backfill nearby-facility enrichment for existing properties."
    )
    parser.add_argument(
        "--limit", type=int, default=None,
        help="Maximum number of properties to process in this run.",
    )
    parser.add_argument(
        "--retry-failed", action="store_true",
        help=(
            "Also include properties whose last enrichment attempt failed, "
            "plus any 'pending' properties stuck for more than "
            "--stale-pending-minutes (a background worker that never finished)."
        ),
    )
    parser.add_argument(
        "--stale-pending-minutes", type=int, default=STALE_PENDING_THRESHOLD_MINUTES,
        help=f"How old a 'pending' entry must be before --retry-failed treats it as abandoned (default: {STALE_PENDING_THRESHOLD_MINUTES}).",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Re-enrich EVERY property, including already completed/partial ones. Use deliberately.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="List what would be processed without calling any external API or writing anything.",
    )
    args = parser.parse_args()

    flask_app = app_module.app
    property_service = flask_app.extensions["property_service"]
    osm_service = flask_app.extensions["osm_location_service"]
    mappls_api_key = flask_app.config.get("MAPPLS_API_KEY")
    radius_km = flask_app.config.get("NEARBY_FACILITY_RADIUS_KM")

    property_ids = _select_properties(
        property_service.collection, args.retry_failed, args.force,
        args.limit, args.stale_pending_minutes,
    )

    print(f"Found {len(property_ids)} propert{'y' if len(property_ids) == 1 else 'ies'} to process.")

    if args.dry_run:
        for property_id in property_ids:
            print(f"  [dry-run] would enrich {property_id}")
        return

    if not property_ids:
        return

    summary = {"completed": 0, "partial": 0, "failed": 0, "skipped": 0}

    for index, property_id in enumerate(property_ids, start=1):

        print(f"[{index}/{len(property_ids)}] enriching {property_id} ...", end=" ", flush=True)

        result = nearby_facility_service.enrich_property_nearby_facilities(
            property_id,
            property_service,
            mappls_api_key,
            osm_service,
            radius_km=radius_km,
        )

        status = result.get("status", "failed")
        summary[status] = summary.get(status, 0) + 1

        print(f"{status} ({result.get('facility_count', 0)} facilities)")

        if result.get("categories_failed"):
            print(f"    categories failed: {list(result['categories_failed'].keys())}")

    print("\n--- Summary ---")
    for status, count in summary.items():
        print(f"  {status}: {count}")


if __name__ == "__main__":
    main()
