"""
osm_resolver.py

Resolves a Mappls-identified POI (placeName + placeAddress) to OSM
coordinates using the PUBLIC Nominatim API, in strict compliance with the
official usage policy (https://operations.osmfoundation.org/policies/nominatim/):

  - Absolute max 1 request/second -> we sleep >=1.1s between requests.
  - A real, identifying User-Agent (no generic library default).
  - Every response is cached to disk keyed by the exact query, so re-running
    this benchmark while debugging never re-hits the public server for the
    same input twice.
  - Single-threaded, sequential, one machine -- no concurrency.
  - No autocomplete-style incremental queries.
  - No systematic/bulk full-dataset downloads -- only the ~31 specific
    lookups this benchmark needs.

Query strategy (progressively less specific, per task Step 4):
  1. Structured query: q=<placeName>, street=<best-guess street fragment>,
     city=Chennai/<detected city>, state=Tamil Nadu, country=India,
     postalcode=<pincode if present>.
  2. Free-form query: "<placeName>, <placeAddress>" (handles cases where
     structured fields don't parse well, e.g. Mappls addresses that pack
     locality/POI info into one string).
  3. Free-form query: "<placeAddress>" alone (name dropped) -- catches
     cases where the name causes a bad structured match but the plain
     address resolves fine.

All raw candidates from whichever strategy returns anything are pooled and
scored with matcher.score_entity so the SAME transparent multi-signal
approach used elsewhere in this research judges OSM's candidates.
"""

from __future__ import annotations
import hashlib
import json
import re
import time
from pathlib import Path

import requests

from matcher import best_of

CACHE_DIR = Path(__file__).resolve().parent / "cache" / "nominatim"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
# Identifies this research use per Nominatim's usage policy -- not a generic
# library User-Agent.
USER_AGENT = "SmartHomes-GeoCoordinateResearch/1.0 (standalone benchmark; non-commercial research; contact: project-owner)"

MIN_INTERVAL = 1.1  # seconds; policy max is 1 req/s, we pad slightly
_last_request_time = [0.0]


def _throttle():
    elapsed = time.time() - _last_request_time[0]
    if elapsed < MIN_INTERVAL:
        time.sleep(MIN_INTERVAL - elapsed)
    _last_request_time[0] = time.time()


def _cache_key(params: dict) -> str:
    raw = json.dumps(params, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def _cached_get(params: dict) -> list:
    key = _cache_key(params)
    cache_file = CACHE_DIR / f"{key}.json"
    if cache_file.exists():
        return json.loads(cache_file.read_text(encoding="utf-8"))

    _throttle()
    headers = {"User-Agent": USER_AGENT}
    r = requests.get(NOMINATIM_URL, params=params, headers=headers, timeout=20)
    try:
        data = r.json() if r.status_code == 200 else []
    except ValueError:
        data = []
    cache_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def _extract_pincode(text):
    if not text:
        return None
    m = re.findall(r"\b(\d{6})\b", text)
    return m[-1] if m else None


def _detect_city(address: str) -> str:
    # Mappls addresses in this dataset are overwhelmingly Chennai-area; fall
    # back to the last-but-2 comma fragment as a naive city guess otherwise.
    if "chennai" in (address or "").lower():
        return "Chennai"
    parts = [p.strip() for p in (address or "").split(",") if p.strip()]
    return parts[-3] if len(parts) >= 3 else ""


def _queries_for(mappls: dict) -> list:
    """
    Ordered from simplest/most-effective to most-specific. Discovered during
    development (see osm_resolver stress test, VIT Chennai): Mappls address
    strings pack in extra descriptive tokens (highway codes like "SH 121",
    house-number prefixes like "No 21", landmark references like "Near Asan
    Memorial School") that DON'T match how OSM addresses are conventionally
    tagged -- so a long, fully-detailed free-form query frequently returns
    ZERO results even when a simple bare-name query succeeds well. We
    therefore try simple queries FIRST and only fall back to more detailed
    ones when the simple form is ambiguous or returns nothing, rather than
    starting from maximum detail.
    """
    name = mappls.get("placeName") or ""
    addr = mappls.get("placeAddress") or ""
    pincode = _extract_pincode(addr)
    city = _detect_city(addr) or "Chennai"

    common = {"format": "jsonv2", "addressdetails": 1, "extratags": 1, "namedetails": 1, "limit": 5, "countrycodes": "in"}

    qlist = []
    # 1. Bare place name (proven most effective for well-known POIs)
    if name:
        qlist.append(("bare_name", {**common, "q": name}))

    # 2. Name + city (cheap disambiguation without introducing noisy tokens)
    if name:
        qlist.append(("name_plus_city", {**common, "q": f"{name}, {city}"}))

    # 3. Nominatim's proper STRUCTURED query mode (distinct param set, must
    #    NOT be mixed with a free-form q= -- Nominatim ignores/ANDs oddly
    #    when both are present, which is what broke our first attempt).
    structured = {**common, "amenity": name, "city": city, "state": "Tamil Nadu", "country": "India"}
    if pincode:
        structured["postalcode"] = pincode
    qlist.append(("structured", structured))

    # 4. Full free-form name+address (fallback for sparse-name cases where
    #    address detail is genuinely needed to disambiguate)
    if name and addr:
        qlist.append(("freeform_name_address", {**common, "q": f"{name}, {addr}"}))

    # 5. Free-form address only
    if addr:
        qlist.append(("freeform_address_only", {**common, "q": addr}))

    return qlist


PLAUSIBLE_OSM_CLASSES = {
    # class -> whether it's generally a "specific POI" vs administrative/coarse
    "amenity": True, "shop": True, "tourism": True, "leisure": True,
    "railway": True, "aeroway": True, "healthcare": True, "office": True,
    "building": True,
    "highway": False, "place": False, "boundary": False, "landuse": False,
}


def resolve(mappls: dict) -> dict:
    """Returns a dict with: query_strategies_tried, raw_candidate_count,
    all_candidates (normalized), best, best_score, status."""
    all_raw = []
    strategies_used = []
    # Always try the two cheap/simple strategies (bare name, name+city) --
    # they're the ones that actually work well (see module docstring), and
    # pooling both gives the matcher real alternatives to rank. Only escalate
    # to the more specific (and less reliable) strategies if neither of the
    # cheap ones found anything, to keep total request volume low per
    # Nominatim's "don't send more requests than necessary" policy.
    strategies = _queries_for(mappls)
    cheap = [s for s in strategies if s[0] in ("bare_name", "name_plus_city")]
    escalate = [s for s in strategies if s[0] not in ("bare_name", "name_plus_city")]

    for strategy_name, params in cheap:
        results = _cached_get(params)
        strategies_used.append({"strategy": strategy_name, "query": params.get("q"), "result_count": len(results)})
        for r in results:
            r["_strategy"] = strategy_name
            all_raw.append(r)

    if not all_raw:
        for strategy_name, params in escalate:
            results = _cached_get(params)
            display_q = params.get("q") or f"amenity={params.get('amenity')}, city={params.get('city')}"
            strategies_used.append({"strategy": strategy_name, "query": display_q, "result_count": len(results)})
            for r in results:
                r["_strategy"] = strategy_name
                all_raw.append(r)
            if results:
                break

    if not all_raw:
        return {
            "status": "NO_CANDIDATES",
            "strategies": strategies_used,
            "raw_candidate_count": 0,
            "all_candidates": [],
            "best": None,
            "best_score": None,
        }

    # De-duplicate by osm_id
    seen = set()
    deduped = []
    for r in all_raw:
        oid = r.get("osm_id")
        if oid in seen:
            continue
        seen.add(oid)
        deduped.append(r)

    normalized = []
    for r in deduped:
        addr = r.get("address", {}) or {}
        # Nominatim's jsonv2 format calls this field "category" (not "class").
        osm_class = r.get("category")
        category_plausible = PLAUSIBLE_OSM_CLASSES.get(osm_class)
        normalized.append({
            "name": r.get("namedetails", {}).get("name") or r.get("name") or r.get("display_name", "").split(",")[0],
            "full_text": r.get("display_name"),
            "city": addr.get("city") or addr.get("town") or addr.get("suburb"),
            "state": addr.get("state"),
            "postcode": addr.get("postcode"),
            "category_plausible": category_plausible,
            # passthrough / display fields
            "osm_id": r.get("osm_id"),
            "osm_type": r.get("osm_type"),
            "osm_class": osm_class,
            "osm_type_tag": r.get("type"),
            "lat": float(r["lat"]) if r.get("lat") else None,
            "lon": float(r["lon"]) if r.get("lon") else None,
            "display_name": r.get("display_name"),
            "importance": r.get("importance"),
            "extratags": r.get("extratags"),
            "strategy": r.get("_strategy"),
        })

    best_c, best_es, scored = best_of(mappls, normalized)

    return {
        "status": "OK",
        "strategies": strategies_used,
        "raw_candidate_count": len(deduped),
        "all_candidates": normalized,
        "all_scored": [
            {"candidate": c, "score": vars(es)} for c, es in scored
        ],
        "best": best_c,
        "best_score": vars(best_es) if best_es else None,
    }


if __name__ == "__main__":
    test = {"placeName": "VIT Chennai", "placeAddress": "Vandalur Kelambakkam Road, SH 121, Kandigai, Chennai, Tamil Nadu, 600127"}
    out = resolve(test)
    print(json.dumps({k: v for k, v in out.items() if k != "all_candidates"}, indent=2, default=str)[:3000])
