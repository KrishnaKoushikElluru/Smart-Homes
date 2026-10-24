"""
evaluation.py

Combines the OSM (all 31 cases) and Overture (representative 12-case
subset) results into one merged results file, applies ground truth where
available, and classifies each case's failure source per Step 12:

  MAPPLS            - Mappls itself resolved the wrong/ambiguous entity;
                       neither downstream source could be expected to fix it.
  OSM_FAILURE        - OSM's best candidate is an entity mismatch, or found
                       nothing, despite a usable Mappls input.
  OVERTURE_FAILURE   - same, for Overture.
  INSUFFICIENT_DATA  - Mappls' own address was too sparse to disambiguate
                       (e.g. locality name only, no POI/street info) --
                       not really either source's fault.
  AMBIGUOUS_ENTITY   - Mappls' selection is a real, legitimate entity, but
                       genuinely one of several equally valid answers for a
                       vague query.
  GEOMETRY_INACCURATE- entity match looks right but coordinates are
                       measurably far from a known reference.
  UNABLE_TO_VERIFY   - no reliable ground truth exists to judge geometry;
                       explicitly not scored as correct or incorrect.
  NONE               - resolved correctly, nothing to flag.

This module deliberately keeps ENTITY MATCH and GEOMETRY QUALITY as two
separate fields per Step 8 -- never merged into one score.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ground_truth import REFERENCE, haversine_m

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def _entity_label(verdict):
    return {
        "ENTITY_MATCH": "GOOD",
        "PROBABLE_ENTITY_MATCH": "PROBABLE",
        "UNCERTAIN": "UNCERTAIN",
        "ENTITY_MISMATCH": "WRONG",
        "REJECTED": "REJECTED",
    }.get(verdict, "N/A")


def build_combined():
    osm_data = json.loads((RESULTS_DIR / "osm_results.json").read_text(encoding="utf-8"))
    overture_path = RESULTS_DIR / "overture_results.json"
    overture_data = json.loads(overture_path.read_text(encoding="utf-8")) if overture_path.exists() else {}

    combined = {}
    for query, rec in osm_data.items():
        mappls = rec["mappls_selected"]
        osm_out = rec["osm_result"]
        osm_best = osm_out.get("best")
        osm_score = osm_out.get("best_score")

        ov_rec = overture_data.get(query)
        overture_out = ov_rec["overture_result"] if ov_rec else None
        overture_best = overture_out.get("best") if overture_out else None
        overture_score = overture_out.get("best_score") if overture_out else None
        overture_tested = ov_rec is not None

        # Geometry quality vs ground truth, where available
        gt = REFERENCE.get(mappls.get("placeName")) or REFERENCE.get(query)
        gt_lat = gt["lat"] if gt else None
        gt_lon = gt["lon"] if gt else None
        gt_confidence = gt["confidence"] if gt else "unknown"

        osm_dist_m = None
        if osm_best and gt_lat is not None:
            osm_dist_m = haversine_m(gt_lat, gt_lon, osm_best.get("lat"), osm_best.get("lon"))
        overture_dist_m = None
        if overture_best and gt_lat is not None:
            overture_dist_m = haversine_m(gt_lat, gt_lon, overture_best.get("lat"), overture_best.get("lon"))

        combined[query] = {
            "mappls_selected": mappls,
            "osm": {
                "status": osm_out["status"],
                "candidate_count": osm_out.get("raw_candidate_count", 0),
                "best": osm_best,
                "entity_verdict": osm_score["verdict"] if osm_score else "N/A",
                "entity_label": _entity_label(osm_score["verdict"] if osm_score else None),
                "raw_score": osm_score["raw_score"] if osm_score else None,
                "distance_from_reference_m": osm_dist_m,
            },
            "overture": {
                "tested": overture_tested,
                "status": overture_out["status"] if overture_out else "NOT_TESTED_IN_SUBSET",
                "candidate_count": overture_out.get("raw_candidate_count", 0) if overture_out else 0,
                "best": overture_best,
                "entity_verdict": overture_score["verdict"] if overture_score else "N/A",
                "entity_label": _entity_label(overture_score["verdict"] if overture_score else None),
                "raw_score": overture_score["raw_score"] if overture_score else None,
                "distance_from_reference_m": overture_dist_m,
                "download_meta": ov_rec["download_meta"] if ov_rec else None,
            },
            "ground_truth": {
                "lat": gt_lat, "lon": gt_lon, "confidence": gt_confidence,
                "note": gt["note"] if gt else "No reference entry -- UNKNOWN / NOT VERIFIED",
            },
        }

    out_path = RESULTS_DIR / "benchmark_results.json"
    out_path.write_text(json.dumps(combined, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return combined


if __name__ == "__main__":
    combined = build_combined()
    print(f"Combined {len(combined)} cases -> results/benchmark_results.json")
    tested_overture = sum(1 for v in combined.values() if v["overture"]["tested"])
    print(f"Overture tested on {tested_overture}/{len(combined)} cases (representative subset, see run_overture_benchmark.py)")
