"""
Manual, live verification of services/nearby_facility_service.py against
the REAL Mappls Nearby API, the REAL OSM/Nominatim resolver, and the
REAL MongoDB - not part of the automated test suite (that suite mocks
every external call; see test_nearby_facility_service.py and
test_mappls_service.py's FindNearbyPlacesTests).

Matches this project's existing convention for manual live-API checks
(geo_coordinate_benchmark/manual_endpoint_test.py, mappls_geo_test/).

By default this only enriches ONE existing property with a SMALL subset
of categories (fast, bounded, safe to re-run) rather than the full
17-category taxonomy - pass --full for a complete real run against one
property, or --property-id to target a specific one.

Usage:
    python scripts/manual_verify_nearby_enrichment.py
    python scripts/manual_verify_nearby_enrichment.py --full
    python scripts/manual_verify_nearby_enrichment.py --property-id <id>
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402
from services import nearby_facility_service  # noqa: E402


def _json_default(value):
    return str(value)


def main():

    parser = argparse.ArgumentParser()
    parser.add_argument("--property-id", default=None)
    parser.add_argument("--full", action="store_true", help="Query all 17 facility categories instead of a small subset.")
    args = parser.parse_args()

    flask_app = app_module.app
    property_service = flask_app.extensions["property_service"]
    osm_service = flask_app.extensions["osm_location_service"]
    mappls_api_key = flask_app.config.get("MAPPLS_API_KEY")
    radius_km = flask_app.config.get("NEARBY_FACILITY_RADIUS_KM")

    property_id = args.property_id

    if not property_id:
        first = property_service.collection.find_one({}, {"_id": 1})
        if not first:
            print("No properties exist in this database to verify against.")
            return
        property_id = str(first["_id"])

    categories = None if args.full else {"gym": "gym", "hospital": "hospital", "school": "school"}

    print(f"Enriching property {property_id} (categories={'all 17' if args.full else list(categories.keys())}, radius_km={radius_km}) ...")

    result = nearby_facility_service.enrich_property_nearby_facilities(
        property_id,
        property_service,
        mappls_api_key,
        osm_service,
        categories=categories,
        radius_km=radius_km,
    )

    print("\n--- Enrichment metadata ---")
    print(json.dumps(result, indent=2, default=_json_default))

    stored = property_service.get_property(property_id)
    facilities = stored.get("nearby_facilities", [])

    print(f"\n--- Stored nearby_facilities ({len(facilities)}) ---")
    for facility in facilities:
        print(json.dumps(facility, indent=2, default=_json_default))


if __name__ == "__main__":
    main()
