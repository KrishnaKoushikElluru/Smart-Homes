"""
run_osm_benchmark.py

Runs the OSM (Nominatim) resolver against all 31 Mappls-resolved test cases
(30 reused from geo_reconciliation_test + 1 new). Sequential, throttled,
cached -- see osm_resolver.py module docstring for the exact policy
compliance details.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dataset import load_cases
from osm_resolver import resolve

OUT = Path(__file__).resolve().parent / "results" / "osm_results.json"
OUT.parent.mkdir(exist_ok=True)


def run():
    cases = load_cases()
    results = {}
    t0 = time.time()
    for i, (query, case) in enumerate(cases.items(), 1):
        mappls = case["mappls_selected"]
        print(f"[{i}/{len(cases)}] {query!r} -> Mappls: {mappls.get('placeName')!r}")
        out = resolve(mappls)
        best = out.get("best")
        best_score = out.get("best_score")
        if best:
            print(f"    OSM best: {best.get('name')!r} @ ({best.get('lat')},{best.get('lon')}) "
                  f"class={best.get('osm_class')} verdict={best_score.get('verdict')} score={best_score.get('raw_score')}")
        else:
            print(f"    OSM: {out['status']}")
        results[query] = {
            "mappls_selected": mappls,
            "osm_result": out,
        }
    elapsed = time.time() - t0
    print(f"\nTotal elapsed: {elapsed:.1f}s for {len(cases)} queries")
    OUT.write_text(json.dumps(results, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    print(f"Saved to {OUT}")


if __name__ == "__main__":
    run()
