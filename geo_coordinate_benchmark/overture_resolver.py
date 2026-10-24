"""
overture_resolver.py

Resolves a Mappls-identified POI to Overture Places candidates.

WHY THIS LOOKS DIFFERENT FROM osm_resolver.py: Overture Places is NOT a
hosted geocoding API -- it is a versioned, cloud-hosted Parquet dataset
(current release discovered live from the public bucket listing, per this
task's instruction not to assume an old release name still works). The
officially documented access methods are the `overturemaps` CLI/Python
package or direct DuckDB `read_parquet` against S3
(https://docs.overturemaps.org/getting-data/duckdb/,
https://docs.overturemaps.org/getting-data/cloud-sources/). Both were
tested here.

MEASURED PERFORMANCE (see results/performance_notes.md): a bounding-box
query over a tiny ~16 sq km area around VIT Chennai took ~4-5 MINUTES and
returned 221 places, via BOTH the official CLI and raw DuckDB -- performance
was consistent across methods, meaning this is a property of the dataset's
access pattern (no geographic partitioning in the S3 key layout, so every
query touches a large fraction of the global file set), not a tooling bug.
A single query covering the whole Chennai metro area was extrapolated to
take multiple HOURS and was not attempted in full within this benchmark.

CONSEQUENCE FOR METHODOLOGY: unlike OSM (a live search API queried per-POI
in ~1-3 seconds each), Overture is only practical here as small, targeted
bounding-box pulls. Each pull's center point is an INDEPENDENT reference
coordinate (usually the OSM resolver's own finding for that same query, or
in one documented case a well-known broad locality center) -- NEVER a
manually chosen "answer" coordinate for the specific POI. This keeps the
Overture test honest (it still has to find and identify the right place
within that window) while keeping the download tractable. See
run_overture_benchmark.py for exactly which center was used per case and
why.

Categories in Overture use the newer `categories.primary` field (the
`taxonomy` schema is the long-term replacement per current docs, but
`categories.primary` was confirmed present and populated in this release
during testing, so we use it for entity-category plausibility, exactly as
osm_resolver.py uses OSM's `category` field for the same purpose).
"""

from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from matcher import best_of

CACHE_DIR = Path(__file__).resolve().parent / "cache" / "overture"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

PLAUSIBLE_OVERTURE_CATEGORIES = {
    # Overture's categories.primary values -- confirmed against the actual
    # distinct values observed in this release's data during testing (not
    # guessed from schema docs alone). True/False is a coarse "is this a
    # specific POI vs a generic/administrative label" judgement, same spirit
    # as OSM's PLAUSIBLE_OSM_CLASSES.
    "college_university": True, "campus_building": True, "school": True,
    "hospital": True, "diagnostic_imaging": True, "pharmacy": True,
    "shopping_mall": True, "shopping": True, "bus_station": True,
    "train_station": True, "airport": True, "park": True,
    "landmark_and_historical_building": True, "hindu_temple": True,
    "real_estate_service": False, "gas_station": False, "atms": False,
}


def download_bbox(center_lat: float, center_lon: float, radius_deg: float, cache_key: str) -> dict:
    """Downloads Overture Places within a small bbox around (center_lat,
    center_lon) using the official `overturemaps` CLI, caches the raw
    GeoJSON to disk (so re-running this benchmark never re-downloads),
    and returns the parsed GeoJSON dict. This is a slow, network-bound
    operation (see module docstring) -- callers should run several of
    these concurrently across different queries if downloading more than
    one, since Overture places no rate-limit/policy restriction on this
    public, anonymous-access dataset (unlike Nominatim)."""
    cache_file = CACHE_DIR / f"{cache_key}.geojson"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    xmin, xmax = center_lon - radius_deg, center_lon + radius_deg
    ymin, ymax = center_lat - radius_deg, center_lat + radius_deg
    bbox = f"{xmin},{ymin},{xmax},{ymax}"

    t0 = time.time()
    result = subprocess.run(
        [sys.executable, "-m", "overturemaps", "download",
         f"--bbox={bbox}", "-f", "geojson", "--type=place", "-o", str(cache_file)],
        capture_output=True, text=True, timeout=1800,
    )
    elapsed = time.time() - t0
    meta_file = CACHE_DIR / f"{cache_key}.meta.json"
    meta_file.write_text(json.dumps({
        "bbox": bbox, "elapsed_seconds": round(elapsed, 1),
        "returncode": result.returncode, "stderr_tail": result.stderr[-500:] if result.stderr else "",
    }, indent=2), encoding="utf-8")

    if result.returncode != 0 or not cache_file.exists():
        return {"type": "FeatureCollection", "features": [], "_error": result.stderr[-500:]}
    return json.loads(cache_file.read_text(encoding="utf-8"))


def _addr_full_text(addresses) -> str:
    if not addresses:
        return ""
    parts = []
    for a in addresses:
        for k in ("freeform", "locality", "region", "postcode", "country"):
            v = a.get(k)
            if v:
                parts.append(str(v))
    return ", ".join(parts)


def resolve_from_geojson(mappls: dict, geojson: dict) -> dict:
    features = geojson.get("features", [])
    normalized = []
    for f in features:
        p = f.get("properties", {})
        names = p.get("names") or {}
        name = names.get("primary")
        addresses = p.get("addresses") or []
        addr0 = addresses[0] if addresses else {}
        category = (p.get("categories") or {}).get("primary")
        coords = f.get("geometry", {}).get("coordinates")
        normalized.append({
            "name": name,
            "full_text": _addr_full_text(addresses),
            "city": addr0.get("locality"),
            "state": addr0.get("region"),
            "postcode": addr0.get("postcode"),
            "category_plausible": PLAUSIBLE_OVERTURE_CATEGORIES.get(category),
            # passthrough / display
            "overture_id": p.get("id"),
            "overture_category": category,
            "confidence": p.get("confidence"),
            "websites": p.get("websites"),
            "phones": p.get("phones"),
            "brand": (p.get("brand") or {}).get("names", {}).get("primary") if p.get("brand") else None,
            "lon": coords[0] if coords else None,
            "lat": coords[1] if coords else None,
        })

    if not normalized:
        return {"status": "NO_CANDIDATES", "raw_candidate_count": 0, "all_candidates": [], "best": None, "best_score": None}

    best_c, best_es, scored = best_of(mappls, normalized)
    return {
        "status": "OK",
        "raw_candidate_count": len(normalized),
        "all_candidates": normalized,
        "all_scored": [{"candidate": c, "score": vars(es)} for c, es in scored],
        "best": best_c,
        "best_score": vars(best_es) if best_es else None,
    }


if __name__ == "__main__":
    # Small smoke test reusing the already-cached VIT bbox from earlier
    # research, if present, to avoid a fresh 4-5 minute download here.
    test_cache = Path(__file__).resolve().parent / "test_vit.geojson"
    if test_cache.exists():
        gj = json.loads(test_cache.read_text(encoding="utf-8"))
        out = resolve_from_geojson(
            {"placeName": "VIT Chennai", "placeAddress": "Vandalur Kelambakkam Road, SH 121, Kandigai, Chennai, Tamil Nadu, 600127"},
            gj,
        )
        print(json.dumps({k: v for k, v in out.items() if k != "all_candidates" and k != "all_scored"}, indent=2, default=str))
        print("BEST:", out["best"]["name"] if out["best"] else None, out["best_score"]["verdict"] if out["best_score"] else None)
