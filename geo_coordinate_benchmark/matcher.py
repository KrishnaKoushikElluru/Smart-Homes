"""
matcher.py

Shared, transparent multi-signal candidate matcher used by BOTH the OSM
resolver and the Overture resolver, so the two sources are judged by the
exact same yardstick.

CRITICAL DESIGN REQUIREMENT (per task Step 8): entity matching and geometry
quality are scored and reported SEPARATELY, never merged into one number.

- entity_score: does this candidate even claim to be the same real-world
  place Mappls identified? (name/address/locality/pincode/category
  agreement). This can be computed for ANY candidate, even one with no
  useful coordinates.
- geometry_note: informational only — we usually have no independent
  ground-truth coordinate to grade geometry against. Where a reference
  coordinate exists (see ground_truth.py) we report distance in meters;
  otherwise we say so honestly rather than inventing a quality judgment.

This intentionally reuses the token-similarity approach validated in
geo_reconciliation_test/reconciliation.py (name similarity, address token
overlap, street/locality similarity, city/state/pincode agreement) rather
than inventing a new scheme, adapted to the fact that OSM/Overture use
different field names than Geoapify did.
"""

from __future__ import annotations
import re
import difflib
from dataclasses import dataclass
from typing import Optional

STOPWORDS = {
    "road", "street", "st", "rd", "near", "no", "off", "opp", "opposite",
    "above", "po", "main", "chennai", "tamil", "nadu", "tamilnadu", "india",
    "tn", "the", "and", "of", "at", "in", "to", "1st", "2nd", "3rd", "west",
    "east", "north", "south",
}
STREET_HINTS = ("road", "street", "salai", "marg", "highway", "sh ", "nh ")


def _tokenize(text: Optional[str]) -> set:
    if not text:
        return set()
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return {t for t in text.split() if t and t not in STOPWORDS}


def _jaccard_neutral(a: set, b: set) -> float:
    """Both-empty -> neutral (can't compare). One-empty -> mildly cautious
    neutral. Both non-empty -> real overlap. (Same "don't punish missing
    data" fix validated in the prior Geoapify benchmark.)"""
    if not a and not b:
        return 0.5
    if not a or not b:
        return 0.4
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.5


def _name_similarity(a: Optional[str], b: Optional[str]) -> float:
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _extract_pincode(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    m = re.findall(r"\b(\d{6})\b", text)
    return m[-1] if m else None


def _extract_locality_tokens(mappls_addr: Optional[str]) -> set:
    if not mappls_addr:
        return set()
    parts = [p.strip() for p in mappls_addr.split(",") if p.strip()]
    middle = parts[1:-3] if len(parts) > 3 else parts[:-1]
    middle = [p for p in middle if not any(h in p.lower() for h in STREET_HINTS)]
    return _tokenize(" ".join(middle))


def _extract_street_tokens(text: Optional[str]) -> set:
    if not text:
        return set()
    parts = [p.strip() for p in text.split(",")]
    hits = [p for p in parts if any(h in p.lower() for h in STREET_HINTS)]
    return _tokenize(" ".join(hits)) if hits else set()


@dataclass
class EntityScore:
    name_similarity: float = 0.0
    address_token_overlap: float = 0.0
    street_similarity: float = 0.0
    locality_similarity: float = 0.0
    city_match: bool = False
    state_match: bool = False
    pincode_status: str = "unknown"  # exact | different | unknown
    pincode_score: float = 0.5
    category_plausible: Optional[bool] = None  # None = couldn't evaluate
    raw_score: float = 0.0
    gate_triggered: Optional[str] = None
    verdict: str = "REJECTED"


WEIGHTS = {
    "name_similarity": 0.22,
    "address_token_overlap": 0.15,
    "street_similarity": 0.13,
    "locality_similarity": 0.20,
    "city_match": 0.05,
    "state_match": 0.05,
    "pincode_score": 0.15,
    "category_plausible": 0.05,
}


def score_entity(mappls: dict, candidate_name: Optional[str], candidate_full_text: Optional[str],
                  candidate_city: Optional[str], candidate_state: Optional[str],
                  candidate_postcode: Optional[str], category_plausible: Optional[bool] = None) -> EntityScore:
    """
    mappls: {placeName, placeAddress}
    candidate_full_text: the fullest available text representation of the
      candidate's address (display_name for OSM, joined addresses struct
      for Overture) used for token-overlap/street/locality comparison.
    """
    es = EntityScore()
    m_name = mappls.get("placeName") or ""
    m_addr = mappls.get("placeAddress") or ""

    es.name_similarity = _name_similarity(m_name, candidate_name)
    es.address_token_overlap = _jaccard_neutral(_tokenize(m_addr), _tokenize(candidate_full_text))
    es.street_similarity = _jaccard_neutral(_extract_street_tokens(m_addr), _tokenize(candidate_full_text))
    es.locality_similarity = _jaccard_neutral(_extract_locality_tokens(m_addr), _tokenize(candidate_full_text))

    # Word-level overlap rather than whole-string containment: OSM often
    # labels Indian cities by civic-body name ("Chennai Corporation") rather
    # than the plain city name, so requiring the full candidate_city string
    # to appear verbatim in the Mappls address unfairly failed almost every
    # correct Chennai match. NOTE: deliberately NOT using _tokenize's
    # stopword-stripped set here -- "chennai" is a stopword for the general
    # overlap signals (so "both mention Chennai" doesn't trivially inflate
    # those), but it is exactly the word this specific check needs to see.
    def _raw_words(t):
        return set(re.sub(r"[^a-z0-9\s]", " ", (t or "").lower()).split())
    city_words = _raw_words(candidate_city)
    m_addr_words = _raw_words(m_addr)
    es.city_match = bool(city_words) and bool(city_words & m_addr_words)
    es.state_match = bool(candidate_state) and (
        candidate_state.lower() in m_addr.lower()
        or m_addr.lower().find("tamil nadu") >= 0 and "tamil" in (candidate_state or "").lower()
    )

    mp = _extract_pincode(m_addr)
    cp = (candidate_postcode or "").strip() or None
    if not mp or not cp:
        es.pincode_status, es.pincode_score = "unknown", 0.5
    elif mp == cp:
        es.pincode_status, es.pincode_score = "exact", 1.0
    else:
        es.pincode_status, es.pincode_score = "different", 0.0

    es.category_plausible = category_plausible
    cat_score = {True: 1.0, False: 0.0, None: 0.5}[category_plausible]

    # Hard gates -- same philosophy validated in the Geoapify benchmark:
    # a single strong signal (e.g. name match) must never override a real
    # geographic contradiction.
    if candidate_state and not es.state_match:
        es.gate_triggered = "STATE_MISMATCH"
    elif es.pincode_status == "different" and es.locality_similarity < 0.2 and es.street_similarity < 0.2:
        es.gate_triggered = "PINCODE_LOCALITY_STREET_MISMATCH"

    raw = (
        WEIGHTS["name_similarity"] * es.name_similarity
        + WEIGHTS["address_token_overlap"] * es.address_token_overlap
        + WEIGHTS["street_similarity"] * es.street_similarity
        + WEIGHTS["locality_similarity"] * es.locality_similarity
        + WEIGHTS["city_match"] * (1.0 if es.city_match else 0.0)
        + WEIGHTS["state_match"] * (1.0 if es.state_match else 0.0)
        + WEIGHTS["pincode_score"] * es.pincode_score
        + WEIGHTS["category_plausible"] * cat_score
    )
    es.raw_score = round(raw, 4)

    if es.gate_triggered:
        es.verdict = "REJECTED"
    elif es.raw_score >= 0.68:
        es.verdict = "ENTITY_MATCH"
    elif es.raw_score >= 0.50:
        es.verdict = "PROBABLE_ENTITY_MATCH"
    elif es.raw_score >= 0.32:
        es.verdict = "UNCERTAIN"
    else:
        es.verdict = "ENTITY_MISMATCH"

    return es


def best_of(mappls: dict, candidates: list) -> tuple:
    """candidates: list of dicts each with keys name, full_text, city, state,
    postcode, category_plausible, plus source-specific passthrough fields.
    Returns (best_candidate, best_score, all_scored) sorted non-rejected
    first, then by raw_score desc."""
    scored = []
    for c in candidates:
        es = score_entity(
            mappls,
            c.get("name"),
            c.get("full_text"),
            c.get("city"),
            c.get("state"),
            c.get("postcode"),
            c.get("category_plausible"),
        )
        scored.append((c, es))
    scored.sort(key=lambda pair: (pair[1].verdict == "REJECTED", -pair[1].raw_score))
    best_c, best_es = scored[0] if scored else (None, None)
    return best_c, best_es, scored
