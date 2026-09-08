"""
run_overture_benchmark.py

Runs the Overture resolver against a REPRESENTATIVE SUBSET of the 31 test
cases (not all 31 -- see overture_resolver.py module docstring for the
measured performance reason: ~4-5 minutes per small bounding-box download,
making a full-31 run or a metro-wide single pull impractical here).

The subset was chosen to cover every "difficult case" the task explicitly
named (Step 9) plus a spread of categories (college, hospital, mall,
transit, landmark), while staying small enough to run within this session.

Each bbox's CENTER POINT is documented below with its source. In every case
except one, the center is the OSM resolver's own top result for that same
query (an independently-obtained coordinate, used only as a search-window
center -- never fed into the entity-matching score). This is analogous to
Mappls' own "location" bias parameter: it narrows WHERE to look, it does
not tell the matcher WHAT the answer is. The one exception (Fortis Malar
Hospital) is documented inline.

Downloads run in parallel via a thread pool since Overture's public bucket
has no rate-limit/attribution policy like Nominatim's (this is a bulk open
dataset, not a live geocoding service).
"""
import json
import sys
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset import load_cases
from overture_resolver import download_bbox, resolve_from_geojson

RESULTS_DIR = Path(__file__).resolve().parent / "results"

# (query, center_lat, center_lon, radius_deg, center_source)
SUBSET = [
    ("VIT Chennai", 12.8410462, 80.1540384, 0.025, "OSM top result for this query"),
    ("VIT", 12.9752028, 77.5964268, 0.025, "OSM top result for this query (Bengaluru -- tests whether Overture also gets misled by the same ambiguous bare name Mappls itself got wrong)"),
    ("SRM Kattankulathur", 12.8210402, 80.0479585, 0.025, "OSM top result for this query"),
    ("SRM", 13.0515961, 80.2114304, 0.025, "OSM top result for this query"),
    ("IIT Madras", 12.9941561, 80.2366826, 0.03, "OSM top result for this query"),
    ("Anna University", 13.0083174, 80.2334438, 0.025, "OSM top result for this query"),
    ("Apollo Hospital Chennai", 13.0632248, 80.2515817, 0.025, "OSM top result for this query"),
    ("MIOT Hospital", 13.0013494, 80.258796, 0.025, "OSM top result for this query (also matched 'Mint Hospitals' -- tests if Overture repeats the same confusion)"),
    ("Fortis Malar Hospital", 13.0002, 80.2565, 0.03, "NOT OSM's own result (which was a cross-state Bangalore mismatch, useless as a search center) -- instead the broad, well-known 'Adyar, Chennai' locality center, taken from Mappls' own address text ('...Adyar, Chennai, 600020'), to give Overture a fair chance at the right neighbourhood"),
    ("Guindy National Park", 13.000005, 80.2280448, 0.03, "OSM top result for this query"),
    ("Chennai Central", 13.0865507, 80.274858, 0.025, "OSM top result for this query"),
    ("Marina Beach", 13.0532752, 80.2833106, 0.025, "OSM top result for this query"),
]


def _cache_key(query):
    return "".join(c if c.isalnum() else "_" for c in query.lower())


def run():
    cases = load_cases()
    results = {}

    def task(item):
        query, lat, lon, radius, source = item
        key = _cache_key(query)
        t0 = time.time()
        gj = download_bbox(lat, lon, radius, key)
        elapsed = time.time() - t0
        return query, gj, elapsed, {"center_lat": lat, "center_lon": lon, "radius_deg": radius, "center_source": source}

    print(f"Launching {len(SUBSET)} parallel Overture bbox downloads (this can take several minutes each)...")
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = [ex.submit(task, item) for item in SUBSET]
        for fut in as_completed(futures):
            query, gj, elapsed, meta = fut.result()
            mappls = cases[query]["mappls_selected"]
            out = resolve_from_geojson(mappls, gj)
            best = out.get("best")
            best_score = out.get("best_score")
            print(f"[{elapsed:.0f}s] {query!r}: {out['raw_candidate_count']} candidates -> "
                  f"{(best.get('name') if best else None)!r} "
                  f"verdict={(best_score.get('verdict') if best_score else 'N/A')}")
            results[query] = {
                "mappls_selected": mappls,
                "download_meta": meta,
                "download_elapsed_seconds": round(elapsed, 1),
                "overture_result": out,
            }

    RESULTS_DIR.mkdir(exist_ok=True)
    out_path = RESULTS_DIR / "overture_results.json"
    out_path.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"\nSaved to {out_path}")


if __name__ == "__main__":
    run()
