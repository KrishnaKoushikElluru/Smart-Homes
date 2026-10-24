"""
dataset.py

Loads the 30 Mappls-resolved test cases from the EXISTING
geo_reconciliation_test/results/benchmark_results.json (built in the prior
Geoapify benchmark session) rather than re-deriving the query list or
re-calling Mappls from memory, per this task's explicit instruction to reuse
existing research.

Adds exactly one new case the user explicitly named that was NOT part of
that 30-query set: "Vellore Institute of Technology Chennai" (this phrasing
appears in the very first Mappls test script, osm_test/mappls_geo_test.py,
but was never run through the later 30-query benchmark). That one case is
fetched fresh from Mappls Text Search, using the same Chennai location bias
(12.9716,80.2217) the existing benchmark used, and cached to disk so re-runs
of this benchmark don't re-hit the Mappls API.
"""

import json
import time
from pathlib import Path

import requests
from dotenv import dotenv_values

HERE = Path(__file__).resolve().parent
EXISTING_BENCHMARK = HERE.parent / "geo_reconciliation_test" / "results" / "benchmark_results.json"
CACHE_DIR = HERE / "cache"
CACHE_DIR.mkdir(exist_ok=True)
NEW_CASE_CACHE = CACHE_DIR / "vit_full_name_mappls.json"

SECRET_FILE = "C:/Users/koush/OneDrive/Documents/sw3/secret.env"
BIAS_LAT, BIAS_LON = "12.9716", "80.2217"  # same Chennai bias the existing benchmark used

NEW_QUERY = "Vellore Institute of Technology Chennai"


def _mask(s):
    if not s or len(s) < 8:
        return "***"
    return s[:3] + "..." + s[-3:]


def _fetch_new_case():
    if NEW_CASE_CACHE.exists():
        return json.loads(NEW_CASE_CACHE.read_text(encoding="utf-8"))

    vals = dotenv_values(SECRET_FILE)
    key = (vals.get("MAPPLS_API_KEY") or "").strip()
    r = requests.get(
        "https://search.mappls.com/search/places/textsearch/json",
        params={"query": NEW_QUERY, "location": f"{BIAS_LAT},{BIAS_LON}", "access_token": key},
        timeout=20,
    )
    data = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    cands = data.get("suggestedLocations", []) or []
    selected = cands[0] if cands else {}
    record = {
        "mappls_top3": [
            {"placeName": c.get("placeName"), "eLoc": c.get("eLoc"), "type": c.get("type"), "placeAddress": c.get("placeAddress")}
            for c in cands[:3]
        ],
        "mappls_selected": {
            "placeName": selected.get("placeName"),
            "placeAddress": selected.get("placeAddress"),
            "eLoc": selected.get("eLoc"),
            "type": selected.get("type"),
        },
    }
    NEW_CASE_CACHE.write_text(json.dumps(record, indent=2, ensure_ascii=False), encoding="utf-8")
    return record


def load_cases():
    """Returns dict: query -> {mappls_selected: {placeName, placeAddress, eLoc, type}, mappls_top3: [...]}"""
    existing = json.loads(EXISTING_BENCHMARK.read_text(encoding="utf-8"))
    cases = {}
    for q, rec in existing.items():
        cases[q] = {
            "mappls_selected": rec.get("mappls_selected", {}),
            "mappls_top3": rec.get("mappls_top3", []),
            "source": "geo_reconciliation_test (reused)",
        }

    new_case = _fetch_new_case()
    cases[NEW_QUERY] = {
        "mappls_selected": new_case["mappls_selected"],
        "mappls_top3": new_case["mappls_top3"],
        "source": "fetched fresh for this benchmark (not in prior 30-query set)",
    }
    return cases


if __name__ == "__main__":
    cases = load_cases()
    print(f"Loaded {len(cases)} test cases.")
    for q, c in cases.items():
        ms = c["mappls_selected"]
        print(f"- {q!r} -> {ms.get('placeName')!r} (eLoc={ms.get('eLoc')}) [{c['source']}]")
