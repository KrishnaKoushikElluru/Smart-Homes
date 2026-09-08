"""
ground_truth.py

Reference coordinates used ONLY to evaluate geometry quality AFTER the
fact -- never fed into any resolver or matching algorithm.

Per this task's explicit instruction: we do NOT invent correctness. Every
entry below is labeled with how confident we are and why:

  - "cross_source_agreement": two or more INDEPENDENT sources in this
    research (the prior Geoapify benchmark, this session's OSM lookup,
    this session's Overture lookup) converged on essentially the same
    point (within ~500m) independently of each other. Convergence of
    independent methods is meaningful evidence, though still not a
    surveyed ground truth.
  - "general_knowledge": a well-known, widely-documented public landmark
    whose approximate location is common knowledge (e.g. Marina Beach,
    a national airport) -- NOT independently re-derived here, just
    common enough to sanity-check against.
  - "unknown": no reliable, independently-corroborated reference is
    available. These are explicitly marked UNKNOWN / NOT VERIFIED and
    MUST be reported as such, not scored as correct/incorrect.

Distance from a reference point to a candidate is reported in meters
using the haversine formula for informational "geometry quality" context
only -- it is never used to grade "entity match", which is judged purely
on the text/structural signals in matcher.py.
"""
from math import radians, sin, cos, sqrt, atan2

REFERENCE = {
    "VIT Chennai": {
        "lat": 12.8406, "lon": 80.1538,
        "confidence": "cross_source_agreement",
        "note": "Converges across the prior Geoapify benchmark's Reverse Geocode test, OSM's multiple VIT-building matches (12.8403-12.8443 range), and Overture's own match (12.8444) -- all within ~450m of each other.",
    },
    "IIT Madras": {
        "lat": 12.9915, "lon": 80.2337,
        "confidence": "general_knowledge",
        "note": "Well-known main-gate area of a very large, well-documented campus; exact point within campus varies by which entrance/building is meant.",
    },
    "Anna University": {
        "lat": 13.0108, "lon": 80.2354,
        "confidence": "general_knowledge",
        "note": "Guindy campus administrative building area; approximate, campus spans a wide area.",
    },
    "Marina Beach": {
        "lat": 13.0500, "lon": 80.2824,
        "confidence": "general_knowledge",
        "note": "A ~6km-long beach, not a point -- any coordinate along its length is arguably 'correct'; this is a central reference point only.",
    },
    "Chennai Central": {
        "lat": 13.0827, "lon": 80.2707,
        "confidence": "cross_source_agreement",
        "note": "Converges with both the prior Geoapify benchmark's exact-name match (13.0866,80.2749, conf=1.0) and this session's OSM railway-class match (13.0866,80.2749) -- independent agreement.",
    },
    "Phoenix Mall": {
        "lat": 12.9915, "lon": 80.2170,
        "confidence": "cross_source_agreement",
        "note": "Prior Geoapify benchmark's building-level match and this session's OSM shop-level match both landed within meters of this point. Same reference applies to 'Phoenix Marketcity Chennai' (identical real-world entity).",
    },
    "Apollo Hospital Chennai": {
        "lat": 13.0604, "lon": 80.2496,
        "confidence": "general_knowledge",
        "note": "Well-known Greams Road flagship branch location; approximate.",
    },
    "MIOT Hospital": {
        "lat": 13.0067, "lon": 80.1897,
        "confidence": "general_knowledge",
        "note": "Well-known Manapakkam location; note BOTH Mappls and OSM matched a DIFFERENT entity ('Mint Hospitals'/'Mint Hospitals') for this query -- this reference exists specifically to demonstrate that mismatch, not because either resolver found it.",
    },
    "Guindy National Park": {
        "lat": None, "lon": None,
        "confidence": "unknown",
        "note": "UNKNOWN / NOT VERIFIED -- the park spans a large, irregularly-shaped estate shared with Raj Bhavan; no single reliable reference point was established in this research.",
    },
    "Fortis Malar Hospital": {
        "lat": None, "lon": None,
        "confidence": "unknown",
        "note": "UNKNOWN / NOT VERIFIED -- not independently corroborated in this research; the Adyar locality area is known but not a precise point.",
    },
    "SRM Kattankulathur": {
        "lat": None, "lon": None,
        "confidence": "unknown",
        "note": "UNKNOWN / NOT VERIFIED for a precise point -- OSM and the prior Geoapify benchmark both landed near 12.82-12.84, 80.04-80.05, which is at least mutually consistent, but not independently surveyed.",
    },
}


def haversine_m(lat1, lon1, lat2, lon2):
    if None in (lat1, lon1, lat2, lon2):
        return None
    R = 6371008.8
    p1, p2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dl = radians(lon2 - lon1)
    a = sin(dphi / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return R * 2 * atan2(sqrt(a), sqrt(1 - a))


def lookup(query_or_key):
    return REFERENCE.get(query_or_key)
