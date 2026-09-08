import csv
import json
from pathlib import Path

RESULTS_DIR = Path(__file__).resolve().parent / "results"


def run():
    data = json.loads((RESULTS_DIR / "benchmark_results.json").read_text(encoding="utf-8"))
    rows = []
    for query, rec in data.items():
        m = rec["mappls_selected"]
        osm = rec["osm"]
        ov = rec["overture"]
        gt = rec["ground_truth"]
        rows.append({
            "query": query,
            "mappls_entity": m.get("placeName"),
            "mappls_eloc": m.get("eLoc"),
            "osm_status": osm["status"],
            "osm_candidate_count": osm["candidate_count"],
            "osm_best_name": (osm["best"] or {}).get("name") if osm["best"] else None,
            "osm_lat": (osm["best"] or {}).get("lat") if osm["best"] else None,
            "osm_lon": (osm["best"] or {}).get("lon") if osm["best"] else None,
            "osm_entity_verdict": osm["entity_label"],
            "osm_score": osm["raw_score"],
            "osm_dist_from_ref_m": osm["distance_from_reference_m"],
            "overture_tested": ov["tested"],
            "overture_status": ov["status"],
            "overture_candidate_count": ov["candidate_count"],
            "overture_best_name": (ov["best"] or {}).get("name") if ov["best"] else None,
            "overture_lat": (ov["best"] or {}).get("lat") if ov["best"] else None,
            "overture_lon": (ov["best"] or {}).get("lon") if ov["best"] else None,
            "overture_entity_verdict": ov["entity_label"],
            "overture_score": ov["raw_score"],
            "overture_dist_from_ref_m": ov["distance_from_reference_m"],
            "ground_truth_confidence": gt["confidence"],
        })

    out_path = RESULTS_DIR / "summary.csv"
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {out_path}")


if __name__ == "__main__":
    run()
