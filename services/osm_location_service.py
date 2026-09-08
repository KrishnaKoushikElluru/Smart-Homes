"""
Mappls POI -> OSM coordinate resolver (production).

    Mappls-resolved entity (placeName + placeAddress + eLoc)
                    |
                    v
        normalize + generate query variants
                    |
                    v
        Nominatim candidate search (cached, rate-limited)
                    |
                    v
        transparent multi-signal entity matching
                    |
                    v
        confidence + margin decision
                    |
                    v
        MATCHED | AMBIGUOUS | NO_MATCH | REJECTED | ERROR

DESIGN LINEAGE
--------------
This reuses the validated ideas from geo_coordinate_benchmark/ (matcher.py,
osm_resolver.py) - the query-ordering fix (simple queries first; a long,
detail-packed free-form query silently returns zero results even when the
bare place name matches well, per that benchmark's VIT Chennai case), the
neutral-scoring fix for sparse addresses, the exact-pincode-only rule
(partial "same first 3 digits" credit is meaningless within one Indian
city - see the Apollo Hospital Chennai / Perungudi case), and the hard
gates for state/pincode+locality+street mismatches. It does NOT import
that benchmark code directly (per task instructions) - this is a clean
reimplementation for production use, with two additions the benchmark
didn't need: a best-vs-second-best MARGIN check (see MIN_MARGIN below)
and MongoDB-backed caching in place of the benchmark's disk cache.

Mappls remains the sole authority for WHICH entity a query means. This
module only ever asks "where is the entity Mappls already selected" - it
never second-guesses or re-ranks Mappls' own choice (see
services/mappls_service.py).

CONFIDENCE THRESHOLDS (why 0.40 / 0.05, not invented blindly)
---------------------------------------------------------------
Calibrated directly against geo_coordinate_benchmark/results/osm_results.json
(31 real Chennai queries, manually verified). Confirmed-wrong top scores in
that data (Chennai Egmore 0.237, Fortis Malar Hospital 0.288, Hindustan
Institute of Technology 0.335 - the latter two additionally caught by hard
gates regardless of score) sit clearly below confirmed-correct top scores
(Guindy National Park 0.406 up through IIT Madras 0.701). 0.40 sits in the
gap between those two clusters. For margin: well-separated correct matches
in that data had margins of 0.11-0.23; tight margins (VIT Chennai 0.022,
Tidel Park 0.0) turned out to be BENIGN - multiple candidates for the same
real campus, not competing different places - while the one genuinely
wrong tight-margin case (Chennai Egmore, 0.014) was also caught by the
score floor anyway. 0.05 admits every well-separated correct case while
conservatively downgrading tight-margin cases (including some benign ones)
to AMBIGUOUS rather than auto-matching. That's an intentional, documented
bias: a false "needs confirmation" is far cheaper than a false silent
accept, per this task's explicit requirement never to guess.

Every design choice here is inspectable in code, not implicit - see the
scoring weights and gates below.
"""

from __future__ import annotations

import hashlib
import re
import time
import unicodedata
import difflib
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from typing import Optional

import requests


# ============================================================
# CONFIGURATION DEFAULTS
#
# Real values are read from environment variables in app.py and passed
# in explicitly at construction time (see OSMLocationService.__init__)
# - this module never reads os.environ or current_app itself, matching
# services/geospatial_service.py's convention of pure, explicitly
# -configured functions/classes.
# ============================================================

DEFAULT_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
DEFAULT_USER_AGENT = "SmartHomes-LocationResolver/1.0 (contact: apisupport@smarthomes.local)"
DEFAULT_TIMEOUT_SECONDS = 8
DEFAULT_CACHE_ENABLED = True
DEFAULT_CACHE_TTL_SECONDS = 30 * 24 * 60 * 60  # 30 days: POI coordinates rarely change

# See module docstring for how these were derived.
DEFAULT_MIN_SCORE = 0.40
DEFAULT_MIN_MARGIN = 0.05

# Nominatim usage policy: absolute max 1 request/second.
MIN_REQUEST_INTERVAL_SECONDS = 1.1

CACHE_COLLECTION_NAME = "osm_geocode_cache"


# ============================================================
# NORMALIZATION
#
# Deterministic, algorithmic, generic. Deliberately does NOT contain any
# POI-name aliasing ("VIT" -> "Vellore Institute of Technology" is
# explicitly prohibited by this task) - only universally-applicable
# address-token normalization that would be correct for ANY Indian
# address, not just the ones in our test set.
# ============================================================

_GENERIC_ADDRESS_EXPANSIONS = {
    # Left side must be a whole token (matched with word boundaries) -
    # these are generic abbreviations used across virtually all Indian
    # addresses, not brand/POI names.
    "rd": "road",
    "st": "street",
    "marg": "marg",
    "nr": "near",
    "opp": "opposite",
    "dt": "district",
    "distt": "district",
    "twp": "township",
}

_PUNCTUATION_RE = re.compile(r"[^\w\s,]", re.UNICODE)
_WHITESPACE_RE = re.compile(r"\s+")
_PINCODE_RE = re.compile(r"\b(\d{6})\b")


def normalize_text(text: Optional[str]) -> str:
    """Lowercase, Unicode-normalize, strip punctuation (keeping commas as
    structural separators), collapse whitespace, expand a small set of
    generic address abbreviations. No POI-specific knowledge."""

    if not text:
        return ""

    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = text.lower()
    text = _PUNCTUATION_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text).strip()

    tokens = []
    for token in text.split(" "):
        tokens.append(_GENERIC_ADDRESS_EXPANSIONS.get(token, token))

    return " ".join(tokens)


def extract_pincode(text: Optional[str]) -> Optional[str]:
    if not text:
        return None
    matches = _PINCODE_RE.findall(text)
    return matches[-1] if matches else None


def extract_city_guess(address: Optional[str]) -> str:
    """Best-effort city guess from a Mappls address string: the token
    "chennai" if present anywhere (overwhelmingly common for this
    deployment's addresses), else the third-from-last comma fragment
    (typically city, in "..., city, state, pincode" style addresses)."""

    if not address:
        return ""

    if "chennai" in address.lower():
        return "Chennai"

    parts = [p.strip() for p in address.split(",") if p.strip()]
    return parts[-3] if len(parts) >= 3 else ""


def extract_locality_tokens(address: Optional[str]) -> set:
    """Locality-ish tokens: the comma-separated fragments of an address
    excluding the trailing city/state/pincode/country and excluding any
    fragment that looks like a street name."""

    if not address:
        return set()

    parts = [p.strip() for p in address.split(",") if p.strip()]
    middle = parts[1:-3] if len(parts) > 3 else parts[:-1]
    middle = [p for p in middle if not _looks_like_street(p)]
    return _tokenize(" ".join(middle))


_STREET_HINTS = ("road", "street", "salai", "marg", "highway", "sh ", "nh ")


def _looks_like_street(fragment: str) -> bool:
    fragment = fragment.lower()
    return any(hint in fragment for hint in _STREET_HINTS)


def extract_street_tokens(address: Optional[str]) -> set:
    if not address:
        return set()
    parts = [p.strip() for p in address.split(",")]
    hits = [p for p in parts if _looks_like_street(p)]
    return _tokenize(" ".join(hits)) if hits else set()


_STOPWORDS = {
    "road", "street", "st", "rd", "near", "no", "off", "opp", "opposite",
    "above", "po", "main", "chennai", "tamil", "nadu", "tamilnadu", "india",
    "tn", "the", "and", "of", "at", "in", "to", "1st", "2nd", "3rd", "west",
    "east", "north", "south",
}


def _tokenize(text: Optional[str]) -> set:
    if not text:
        return set()
    text = text.lower()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    return {t for t in text.split() if t and t not in _STOPWORDS}


def _raw_words(text: Optional[str]) -> set:
    """Like _tokenize but WITHOUT stopword removal - needed for the
    city-match check, since "chennai" is exactly the word that check
    needs to see (it's a stopword for the general overlap signals so
    "both mention Chennai" doesn't trivially inflate those)."""
    return set(re.sub(r"[^a-z0-9\s]", " ", (text or "").lower()).split())


# ============================================================
# QUERY VARIANT GENERATION
#
# Ordered simplest-and-most-effective first, per the benchmark's core
# finding: Mappls addresses pack in tokens (highway codes, house-number
# prefixes, landmark references) that don't match how OSM tags
# addresses, so a long, fully-detailed free-form query frequently
# returns ZERO results even when the bare place name matches well.
# ============================================================

def generate_query_variants(place_name: str, address: str) -> list:
    """Returns [(strategy_name, query_string_or_structured_dict), ...]."""

    name = normalize_text(place_name)
    city = extract_city_guess(address) or "Chennai"
    pincode = extract_pincode(address)

    variants = []

    if name:
        variants.append(("bare_name", {"q": place_name}))
        variants.append(("name_plus_city", {"q": f"{place_name}, {city}"}))
        structured = {
            "amenity": place_name,
            "city": city,
            "state": "Tamil Nadu",
            "country": "India",
        }
        if pincode:
            structured["postalcode"] = pincode
        variants.append(("structured", structured))

    if name and address:
        variants.append(("freeform_name_address", {"q": f"{place_name}, {address}"}))

    if address:
        variants.append(("freeform_address_only", {"q": address}))

    return variants


# ============================================================
# CANDIDATE MATCHING (entity match only - never geometry judgement)
# ============================================================

_PLAUSIBLE_OSM_CATEGORIES = {
    "amenity": True, "shop": True, "tourism": True, "leisure": True,
    "railway": True, "aeroway": True, "healthcare": True, "office": True,
    "building": True,
    "highway": False, "place": False, "boundary": False, "landuse": False,
}

_WEIGHTS = {
    "name_similarity": 0.22,
    "address_token_overlap": 0.15,
    "street_similarity": 0.13,
    "locality_similarity": 0.20,
    "city_match": 0.05,
    "state_match": 0.05,
    "pincode_score": 0.15,
    "category_plausible": 0.05,
}


@dataclass
class MatchScore:
    name_similarity: float = 0.0
    address_token_overlap: float = 0.0
    street_similarity: float = 0.0
    locality_similarity: float = 0.0
    city_match: bool = False
    state_match: bool = False
    pincode_status: str = "unknown"
    pincode_score: float = 0.5
    category_plausible: Optional[bool] = None
    raw_score: float = 0.0
    gate_triggered: Optional[str] = None


def _jaccard_neutral(a: set, b: set) -> float:
    """Both-empty -> neutral (nothing to compare, don't punish a sparse
    -but-correct Mappls address). One-empty -> mildly cautious neutral.
    Both non-empty -> real overlap."""
    if not a and not b:
        return 0.5
    if not a or not b:
        return 0.4
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.5


def score_candidate(mappls: dict, candidate: dict) -> MatchScore:
    """mappls: {place_name, address}. candidate: {name, full_text, city,
    state, postcode, category_plausible}."""

    ms = MatchScore()
    m_name = mappls.get("place_name") or ""
    m_addr = mappls.get("address") or ""

    c_name = candidate.get("name")
    c_full = candidate.get("full_text")

    ms.name_similarity = (
        difflib.SequenceMatcher(None, m_name.lower(), c_name.lower()).ratio()
        if m_name and c_name else 0.0
    )
    ms.address_token_overlap = _jaccard_neutral(_tokenize(m_addr), _tokenize(c_full))
    ms.street_similarity = _jaccard_neutral(extract_street_tokens(m_addr), _tokenize(c_full))
    ms.locality_similarity = _jaccard_neutral(extract_locality_tokens(m_addr), _tokenize(c_full))

    city_words = _raw_words(candidate.get("city"))
    ms.city_match = bool(city_words) and bool(city_words & _raw_words(m_addr))

    candidate_state = candidate.get("state")
    ms.state_match = bool(candidate_state) and bool(
        _raw_words(candidate_state) & _raw_words(m_addr)
    )

    m_pincode = extract_pincode(m_addr)
    c_pincode = (candidate.get("postcode") or "").strip() or None
    if not m_pincode or not c_pincode:
        ms.pincode_status, ms.pincode_score = "unknown", 0.5
    elif m_pincode == c_pincode:
        ms.pincode_status, ms.pincode_score = "exact", 1.0
    else:
        # Exact match only - "same first 3 digits" is meaningless within
        # one Indian city (every Chennai pincode starts with "600").
        ms.pincode_status, ms.pincode_score = "different", 0.0

    ms.category_plausible = candidate.get("category_plausible")
    cat_score = {True: 1.0, False: 0.0, None: 0.5}[ms.category_plausible]

    if candidate_state and not ms.state_match:
        ms.gate_triggered = "STATE_MISMATCH"
    elif (
        ms.pincode_status == "different"
        and ms.locality_similarity < 0.2
        # NOTE: street_similarity's "no informative data" value is 0.4-0.5
        # (see _jaccard_neutral), not 0.0 - a fragment like "1st Street" or
        # "Main Road" tokenizes to nothing once generic stopwords are
        # stripped, so treating "neutral" the same as "confirmed match"
        # here would make this gate nearly impossible to trigger whenever
        # the street text is generic (very common), silently weakening the
        # exact protection the Apollo Hospital Chennai / Perungudi case
        # requires. Only a POSITIVE street match (>=0.5, real overlapping
        # tokens) is allowed to save a candidate from rejection despite a
        # pincode+locality mismatch; a neutral "no data" street reading
        # must not.
        and ms.street_similarity < 0.5
    ):
        ms.gate_triggered = "PINCODE_LOCALITY_STREET_MISMATCH"

    raw = (
        _WEIGHTS["name_similarity"] * ms.name_similarity
        + _WEIGHTS["address_token_overlap"] * ms.address_token_overlap
        + _WEIGHTS["street_similarity"] * ms.street_similarity
        + _WEIGHTS["locality_similarity"] * ms.locality_similarity
        + _WEIGHTS["city_match"] * (1.0 if ms.city_match else 0.0)
        + _WEIGHTS["state_match"] * (1.0 if ms.state_match else 0.0)
        + _WEIGHTS["pincode_score"] * ms.pincode_score
        + _WEIGHTS["category_plausible"] * cat_score
    )
    ms.raw_score = round(raw, 4)

    return ms


# ============================================================
# NOMINATIM ACCESS (rate-limited, cached, policy-compliant)
# ============================================================

class _RateLimiter:
    """Process-local throttle. Note: only coordinates requests made by
    THIS process - if the app runs multiple worker processes, each
    enforces the 1 req/s limit independently. Combined with caching
    (which eliminates repeat lookups for the same POI across the whole
    app, not just within one process) this keeps aggregate load on the
    public Nominatim instance low for our expected query volume, but a
    high-traffic deployment should move to a self-hosted geocoder (see
    OSM_NOMINATIM_URL) rather than rely on this alone."""

    def __init__(self):
        self._last_request_time = 0.0

    def wait(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < MIN_REQUEST_INTERVAL_SECONDS:
            time.sleep(MIN_REQUEST_INTERVAL_SECONDS - elapsed)
        self._last_request_time = time.time()


def _cache_key(nominatim_url: str, params: dict) -> str:
    raw = f"{nominatim_url}|" + "|".join(f"{k}={v}" for k, v in sorted(params.items()))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ============================================================
# SERVICE
# ============================================================

class OSMLocationService:

    def __init__(
        self,
        mongo_service=None,
        nominatim_url: str = DEFAULT_NOMINATIM_URL,
        user_agent: str = DEFAULT_USER_AGENT,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        cache_enabled: bool = DEFAULT_CACHE_ENABLED,
        cache_ttl_seconds: int = DEFAULT_CACHE_TTL_SECONDS,
        min_score: float = DEFAULT_MIN_SCORE,
        min_margin: float = DEFAULT_MIN_MARGIN,
        logger=None,
    ):
        self.nominatim_url = nominatim_url
        self.user_agent = user_agent
        self.timeout_seconds = timeout_seconds
        self.cache_enabled = cache_enabled and mongo_service is not None
        self.cache_ttl_seconds = cache_ttl_seconds
        self.min_score = min_score
        self.min_margin = min_margin
        self.logger = logger

        self._rate_limiter = _RateLimiter()
        self._cache_collection = None

        if self.cache_enabled:
            self._cache_collection = mongo_service.get_collection(CACHE_COLLECTION_NAME)

    # --------------------------------------------------------
    # INDEXES
    # --------------------------------------------------------

    def ensure_indexes(self):
        if self._cache_collection is not None:
            self._cache_collection.create_index(
                "created_at",
                expireAfterSeconds=self.cache_ttl_seconds,
            )
            self._cache_collection.create_index("cache_key", unique=True)

    # --------------------------------------------------------
    # LOGGING (never logs the raw Nominatim response body or any
    # secret - just the observability fields Step 21 asked for)
    # --------------------------------------------------------

    def _log(self, **fields):
        if self.logger:
            self.logger.info("osm_location_resolve", extra=fields)

    # --------------------------------------------------------
    # CACHED HTTP FETCH
    # --------------------------------------------------------

    def _fetch(self, params: dict) -> list:
        base_params = {
            "format": "jsonv2",
            "addressdetails": 1,
            "extratags": 1,
            "namedetails": 1,
            "limit": 5,
            "countrycodes": "in",
        }
        full_params = {**base_params, **params}

        cache_key = _cache_key(self.nominatim_url, full_params)

        if self._cache_collection is not None:
            cached = self._cache_collection.find_one({"cache_key": cache_key})
            if cached is not None:
                return cached.get("results", [])

        self._rate_limiter.wait()

        try:
            response = requests.get(
                self.nominatim_url,
                params=full_params,
                headers={"User-Agent": self.user_agent},
                timeout=self.timeout_seconds,
            )
            results = response.json() if response.status_code == 200 else []
            if not isinstance(results, list):
                results = []

        except (requests.RequestException, ValueError):
            results = None  # network/parse failure, distinct from "no results"

        if self._cache_collection is not None and results is not None:
            self._cache_collection.update_one(
                {"cache_key": cache_key},
                {"$set": {
                    "cache_key": cache_key,
                    "query": full_params.get("q") or full_params.get("amenity"),
                    "results": results,
                    "created_at": datetime.utcnow(),
                }},
                upsert=True,
            )

        return results if results is not None else []

    # --------------------------------------------------------
    # CANDIDATE NORMALIZATION
    # --------------------------------------------------------

    @staticmethod
    def _normalize_osm_result(raw: dict) -> dict:
        address = raw.get("address") or {}
        category = raw.get("category")  # Nominatim jsonv2 field name
        try:
            lat = float(raw["lat"])
            lon = float(raw["lon"])
        except (KeyError, TypeError, ValueError):
            lat = lon = None

        return {
            "name": (
                (raw.get("namedetails") or {}).get("name")
                or raw.get("name")
                or (raw.get("display_name") or "").split(",")[0]
            ),
            "full_text": raw.get("display_name"),
            "city": address.get("city") or address.get("town") or address.get("suburb"),
            "state": address.get("state"),
            "postcode": address.get("postcode"),
            "category_plausible": _PLAUSIBLE_OSM_CATEGORIES.get(category),
            "osm_id": raw.get("osm_id"),
            "osm_type": raw.get("osm_type"),
            "osm_category": category,
            "osm_type_tag": raw.get("type"),
            "latitude": lat,
            "longitude": lon,
            "display_name": raw.get("display_name"),
            "importance": raw.get("importance"),
        }

    # --------------------------------------------------------
    # PUBLIC API
    # --------------------------------------------------------

    def resolve_coordinates(self, mappls_poi: dict) -> dict:
        """
        mappls_poi: {place_name, address, eloc, city, state, pincode, type}
          (city/state/pincode/type are optional extra context; only
          place_name and address are required for matching).

        Returns a dict - see module docstring for the status meanings.
        Never raises.
        """

        t0 = time.time()

        place_name = (mappls_poi.get("place_name") or "").strip()
        address = (mappls_poi.get("address") or "").strip()

        base_result = {
            "status": "error",
            "latitude": None,
            "longitude": None,
            "source": "osm",
            "osm_id": None,
            "osm_type": None,
            "osm_category": None,
            "display_name": None,
            "confidence": None,
            "match_method": None,
            "matched_name": None,
            "matched_address": None,
            "candidate_count": 0,
            "alternates": [],
            "error": None,
        }

        if not place_name and not address:
            base_result["error"] = "No place name or address to resolve."
            base_result["status"] = "error"
            return base_result

        mappls_for_matching = {"place_name": place_name, "address": address}

        variants = generate_query_variants(place_name, address)
        cheap_variants = [v for v in variants if v[0] in ("bare_name", "name_plus_city")]
        escalation_variants = [v for v in variants if v[0] not in ("bare_name", "name_plus_city")]

        all_candidates = []
        candidates_by_source = {}
        network_error = False

        def _run(strategy_name, query):
            nonlocal network_error
            raw_results = self._fetch(query)
            if raw_results is None:
                network_error = True
                return []
            normalized = [self._normalize_osm_result(r) for r in raw_results]
            for c in normalized:
                c["_strategy"] = strategy_name
            candidates_by_source[strategy_name] = len(normalized)
            return normalized

        # Always try both cheap strategies (bare name, name+city) - they're
        # the ones that actually work well (see module docstring), and
        # pooling both gives the matcher real alternatives to rank.
        for strategy_name, query in cheap_variants:
            all_candidates.extend(_run(strategy_name, query))

        # Only escalate to the pricier/less-reliable strategies if the
        # cheap ones found nothing at all, to keep request volume low
        # per Nominatim's policy - stop at the first one that succeeds.
        if not all_candidates:
            for strategy_name, query in escalation_variants:
                all_candidates.extend(_run(strategy_name, query))
                if all_candidates:
                    break

        # De-duplicate by osm_id, keep first occurrence
        seen_ids = set()
        deduped = []
        for c in all_candidates:
            oid = c.get("osm_id")
            if oid in seen_ids:
                continue
            seen_ids.add(oid)
            deduped.append(c)

        elapsed_ms = round((time.time() - t0) * 1000)

        if not deduped:
            status = "error" if network_error else "no_match"
            base_result["status"] = status
            base_result["error"] = "OSM request failed." if network_error else "No OSM candidates found."
            self._log(
                query=place_name, mappls_entity=place_name, candidate_count=0,
                status=status, elapsed_ms=elapsed_ms,
            )
            return base_result

        scored = [(c, score_candidate(mappls_for_matching, c)) for c in deduped]
        scored.sort(key=lambda pair: (pair[1].gate_triggered is not None, -pair[1].raw_score))

        best_c, best_s = scored[0]
        second_s = scored[1][1] if len(scored) > 1 else None
        margin = (best_s.raw_score - second_s.raw_score) if second_s else None

        base_result["candidate_count"] = len(deduped)
        base_result["alternates"] = [
            {
                "matched_name": c.get("name"),
                "matched_address": c.get("display_name"),
                "latitude": c.get("latitude"),
                "longitude": c.get("longitude"),
                "score": s.raw_score,
            }
            for c, s in scored[1:4]
        ]

        if best_s.gate_triggered:
            base_result["status"] = "rejected"
            base_result["error"] = f"Best candidate rejected: {best_s.gate_triggered}."
            base_result["confidence"] = best_s.raw_score
            base_result["match_method"] = best_c.get("_strategy")

        elif best_s.raw_score < self.min_score:
            base_result["status"] = "no_match"
            base_result["error"] = "No candidate met the minimum confidence score."
            base_result["confidence"] = best_s.raw_score

        elif margin is not None and margin < self.min_margin:
            base_result["status"] = "ambiguous"
            base_result["confidence"] = best_s.raw_score
            base_result["match_method"] = best_c.get("_strategy")
            base_result["error"] = (
                f"Top candidates are too close to distinguish confidently "
                f"(margin={round(margin, 3)})."
            )

        else:
            base_result["status"] = "matched"
            base_result["latitude"] = best_c.get("latitude")
            base_result["longitude"] = best_c.get("longitude")
            base_result["osm_id"] = best_c.get("osm_id")
            base_result["osm_type"] = best_c.get("osm_type")
            base_result["osm_category"] = best_c.get("osm_category")
            base_result["display_name"] = best_c.get("display_name")
            base_result["confidence"] = best_s.raw_score
            base_result["match_method"] = best_c.get("_strategy")
            base_result["matched_name"] = best_c.get("name")
            base_result["matched_address"] = best_c.get("display_name")

        self._log(
            query=place_name,
            mappls_entity=place_name,
            osm_query_variant=best_c.get("_strategy"),
            candidate_count=len(deduped),
            selected_candidate=best_c.get("name"),
            score=best_s.raw_score,
            second_best_score=second_s.raw_score if second_s else None,
            status=base_result["status"],
            elapsed_ms=elapsed_ms,
        )

        return base_result
