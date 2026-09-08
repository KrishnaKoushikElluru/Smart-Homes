"""
run_production_resolver_benchmark.py

Runs the 31-case Mappls-resolved dataset through the ACTUAL PRODUCTION
resolver (services/osm_location_service.py + services/mappls_service.py),
not the old benchmark-only osm_resolver.py/matcher.py. This is what Step
15 of the implementation task requires: verifying the new production code
performs at least as well as the research benchmark before anything is
wired into search.

Uses the real MongoDB cache collection (osm_geocode_cache) via the same
MongoService/secret.env the Flask app uses, so this also exercises the
real caching code path end-to-end - not a mock.

Saves to results/production_resolver_results.json (a SEPARATE file from
the research benchmark's results/osm_results.json).
"""
import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from dotenv import dotenv_values

from services.mongo_service import MongoService
from services.osm_location_service import OSMLocationService
from dataset import load_cases  # noqa: E402 (geo_coordinate_benchmark's own dataset loader)

SECRET_FILE = str(PROJECT_ROOT / "secret.env")
RESULTS_PATH = Path(__file__).resolve().parent / "results" / "production_resolver_results.json"


def run():
    vals = dotenv_values(SECRET_FILE)
    mongo_uri = vals.get("MONGO_URI")

    mongo_service = MongoService(mongo_uri) if mongo_uri else None
    service = OSMLocationService(mongo_service=mongo_service)
    service.ensure_indexes()

    cases = load_cases()
    results = {}

    t0 = time.time()
    for i, (query, case) in enumerate(cases.items(), 1):
        mappls = case["mappls_selected"]
        mappls_input = {
            "place_name": mappls.get("placeName"),
            "address": mappls.get("placeAddress"),
            "eloc": mappls.get("eLoc"),
            "type": mappls.get("type"),
        }
        result = service.resolve_coordinates(mappls_input)
        print(
            f"[{i}/{len(cases)}] {query!r} -> Mappls: {mappls.get('placeName')!r} | "
            f"OSM status={result['status']} conf={result['confidence']} "
            f"method={result['match_method']} candidates={result['candidate_count']}"
        )
        results[query] = {
            "mappls_selected": mappls,
            "production_osm_result": result,
        }

    elapsed = time.time() - t0
    print(f"\nTotal elapsed: {elapsed:.1f}s for {len(cases)} queries")

    RESULTS_PATH.parent.mkdir(exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"Saved to {RESULTS_PATH}")

    if mongo_service:
        mongo_service.close()


if __name__ == "__main__":
    run()
