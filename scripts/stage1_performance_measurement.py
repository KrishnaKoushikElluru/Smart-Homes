"""
Stage 1 performance measurement - NOT a permanent script, run once for
the Stage 1 report. Measures the exact call routes/property_routes.py's
submit_listing() now makes (start_background_enrichment) against the
real app (real MongoDB, real Mappls, real OSM), and compares it to what
the OLD (Phase 4.0, pre-Stage-1) blocking call would have cost by
calling enrich_property_nearby_facilities() directly for comparison.

Creates one throwaway test property, measures, then leaves it (small,
harmless, clearly named) rather than risking a delete-related bug in a
measurement script.
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402
from services import nearby_facility_service as nfs  # noqa: E402


def make_test_property(property_service, suffix):
    property_data = {
        "seller": {"user_id": 1, "username": "stage1_perf_test"},
        "listing": {"type": "rent", "status": "active", "price": 20000, "currency": "INR"},
        "property": {"type": "apartment", "bhk": 2},
        "location": {
            "address": "Stage 1 performance test property",
            "city": "Chennai",
            "coordinates": {"type": "Point", "coordinates": [80.1538, 12.8406]},
        },
        "contact": {"name": "test", "phone": "9999999999"},
        "description": {"text": f"Stage 1 performance measurement property {suffix}"},
        "media": {"images": []},
        "source": {"type": "owner", "url": None},
        "search": {"keywords": [], "embedding": None},
    }
    return property_service.create_property(property_data)


def main():
    flask_app = app_module.app
    property_service = flask_app.extensions["property_service"]
    osm_service = flask_app.extensions["osm_location_service"]
    mappls_api_key = flask_app.config.get("MAPPLS_API_KEY")
    radius_km = flask_app.config.get("NEARBY_FACILITY_RADIUS_KM")

    print("=" * 70)
    print("A/B. HTTP-registration-equivalent latency: BEFORE vs AFTER")
    print("=" * 70)

    # ---- AFTER (Stage 1): what submit_listing() calls today ----
    property_id_after = make_test_property(property_service, "AFTER")

    t0 = time.perf_counter()
    thread = nfs.start_background_enrichment(
        property_id_after, property_service, mappls_api_key, osm_service,
        radius_km=radius_km,
    )
    after_latency = time.perf_counter() - t0

    print(f"\nAFTER (Stage 1, start_background_enrichment): {after_latency:.4f} seconds")
    print("  -> this is what the HTTP request now waits for before returning.")

    # ---- Wait for the background worker, measuring total completion time ----
    t1 = time.perf_counter()
    thread.join(timeout=180)
    enrichment_duration = time.perf_counter() - t1

    final = property_service.get_property(property_id_after)
    metadata = final.get("nearby_facilities_metadata", {})
    facility_count = len(final.get("nearby_facilities", []))

    print(f"\nC. Total background enrichment duration: {enrichment_duration:.2f} seconds")
    print(f"D. Enrichment status after completion: {metadata.get('status')}")
    print(f"E. Facilities successfully stored: {facility_count}")

    # ---- BEFORE (Phase 4.0, pre-Stage-1): the OLD blocking call, same
    # inputs, called directly (this is EXACTLY the call
    # routes/property_routes.py made before Stage 1 - see git history) ----
    property_id_before = make_test_property(property_service, "BEFORE")

    t2 = time.perf_counter()
    before_result = nfs.enrich_property_nearby_facilities(
        property_id_before, property_service, mappls_api_key, osm_service,
        radius_km=radius_km,
    )
    before_latency = time.perf_counter() - t2

    print(f"\nBEFORE (Phase 4.0, direct enrich_property_nearby_facilities call "
          f"- what the HTTP request used to wait for): {before_latency:.2f} seconds")
    print(f"  status={before_result['status']}, facility_count={before_result['facility_count']}")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"  BEFORE (blocking):     {before_latency:.2f}s registration latency")
    print(f"  AFTER  (background):   {after_latency:.4f}s registration latency")
    print(f"  Speedup: {before_latency / after_latency:.0f}x faster registration response")
    print(f"  Background enrichment still completes in {enrichment_duration:.2f}s, unattended.")


if __name__ == "__main__":
    main()
