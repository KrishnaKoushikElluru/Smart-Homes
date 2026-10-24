"""
Ola-primary location resolution, built on top of services/ola_maps_service.py
(HTTP client) and REUSING services/osm_location_service.py's existing
candidate-confidence machinery (score_candidate/MatchScore/normalize_text)
rather than inventing a second, parallel matching system - see this
module's docstring section below for exactly how that reuse works.

    query
        |
        v
    ola_maps_service.autocomplete()        <- multiple raw candidates
        |
        v
    classify_ola_candidates()              <- confidence scoring (reused
        |                                     from osm_location_service)
        v
    MATCHED (best candidate)  |  AMBIGUOUS (alternates)  |  NO_MATCH
        |
        v
    ola_maps_service.get_place_details()   <- authoritative coordinates
        |                                     for the WINNING candidate
        v
    resolve_location_via_ola() result

This module deliberately does NOT know about Mappls or OSM - the
Mappls+OSM fallback chain already lives in
services/search_orchestration.py's resolve_poi_location() (Phase 1,
unchanged) and routes/property_routes.py's resolve_poi() endpoint,
which each call THIS module for the Ola-first attempt and fall back to
their own existing Mappls/OSM code on anything other than "matched".
Composing the two here instead would require this module to import
search_orchestration, which already imports this module for the Ola
step - a circular import. Keeping the fallback composition at the
caller level (where it already existed) avoids that entirely and keeps
every existing Mappls/OSM test's patch targets (e.g.
"services.search_orchestration.mappls_service.resolve_place") valid,
unchanged.

WHAT IS REUSED FROM osm_location_service.py, AND WHAT ISN'T
--------------------------------------------------------------
An earlier version of this module called score_candidate(mappls,
candidate) directly, passing {place_name: query, address: query} as
the reference - reusing that function verbatim. Live testing (see
test_location_provider_service.py) caught a real calibration mismatch:
score_candidate()'s weights were tuned for comparing two ADDRESS-shaped
strings of similar richness (a Mappls address vs an OSM address) - its
address_token_overlap/street_similarity/locality_similarity terms
default to a generous ~0.4-0.5 "neutral" score whenever one side is
sparse (see that function's _jaccard_neutral()). A short user query
("Police Quarters") is ALWAYS sparse compared to a candidate's full
formatted address, so those neutral defaults dominated the score
regardless of whether the candidate was actually the right entity -
the opposite of the intended safety behavior.

So this module reuses what IS genuinely provider-agnostic from
osm_location_service.py - normalize_text() and the tokenizer it uses
internally - but computes its OWN combination (_score_against_query()
below) shaped for THIS comparison (a short query vs a candidate's
name+address), with its OWN disclosed calibration
(_MIN_SCORE/_MIN_MARGIN), rather than silently misapplying weights
calibrated for a different comparison. The METHODOLOGY is the same as
Phase 1's (a normalized text-similarity score, a required minimum
score, AND a required margin over the runner-up before anything is
auto-accepted, otherwise AMBIGUOUS) - that safety principle is what's
preserved, not the specific numbers, which were never claimed to
transfer across a different input shape.

The one piece of REAL cross-provider reuse is the distance gate below,
which is the actual reason "Police Quarters near VIT Chennai" is
correctly rejected in this phase's tests - not text scoring (a generic
name like "Police Quarters" is, honestly, textually similar to itself
everywhere in India; only geography can tell those apart).

DISTANCE GATE
-------------
Autocomplete candidates often already carry coordinates (see
ola_maps_service.autocomplete()'s docstring). When a location_bias is
given AND a candidate has coordinates, a candidate implausibly far from
that bias (see _MAX_BIAS_DISTANCE_KM) is gated out - the same kind of
hard safety gate osm_location_service.py's score_candidate() already
uses for STATE_MISMATCH, applied here because Ola's own text-similarity
score alone cannot always tell "the right entity, described briefly"
from "a same-named entity somewhere else in India" (both look similar
purely as text - see this phase's live investigation:
"Police Quarters near VIT Chennai" returned real, well-formed "Police
Quarters" entities that were still 18-28 km from the actual area).
"""

from __future__ import annotations

import difflib
import math
from typing import Optional

from services import ola_maps_service
from services.osm_location_service import normalize_text, _tokenize


# SmartHomes' current listings are Chennai-only (same documented
# rationale already used for DEFAULT_LOCATION_BIAS in
# services/search_orchestration.py) - a candidate this far from the
# search's own location bias is not a plausible match regardless of how
# similar its name/address text looks. Generous enough to cover the
# whole Chennai metro area with margin, not a tight geofence.
_MAX_BIAS_DISTANCE_KM = 50.0

# Calibrated against this phase's own live investigation worked
# examples (see test_location_provider_service.py's
# ScoreAgainstQueryTests for the exact numbers): correct matches
# ("Tata Value Homes, Mambakkam" -> "TaTa Value Homes Mambakkam",
# "VIT Chennai" -> "VIT Chennai", "SRM University, Chennai" ->
# "SRM University Campus") score 0.86-1.00; a genuinely generic,
# under-specified query ("Police Quarters", "Gym") against a real but
# unrelated same-named entity scores 0.70-0.73 - below this threshold,
# so it is NOT auto-accepted from text alone (the distance gate above
# is what actually resolves genuinely local generic queries like
# "Police Quarters near VIT Chennai" when a bias is available).
_MIN_SCORE = 0.75
_MIN_MARGIN = 0.08

_NAME_SIMILARITY_WEIGHT = 0.6
_TOKEN_OVERLAP_WEIGHT = 0.4


def _score_against_query(query: str, candidate: dict) -> float:
    """How well `candidate` (an Ola autocomplete candidate) matches the
    raw `query` text - see this module's docstring for why this is a
    purpose-built formula rather than a reuse of
    osm_location_service.score_candidate()."""

    query_norm = normalize_text(query)
    name_norm = normalize_text(candidate.get("name") or "")
    address_norm = normalize_text(candidate.get("address") or "")

    name_similarity = (
        difflib.SequenceMatcher(None, query_norm, name_norm).ratio()
        if query_norm and name_norm else 0.0
    )

    query_tokens = _tokenize(query_norm)
    candidate_tokens = _tokenize(name_norm) | _tokenize(address_norm)
    # Recall against the QUERY's own words, not a symmetric Jaccard -
    # a long candidate address naturally contains many words the short
    # query never mentioned, and that must not be held against it.
    token_overlap = (
        len(query_tokens & candidate_tokens) / len(query_tokens)
        if query_tokens else 0.0
    )

    return _NAME_SIMILARITY_WEIGHT * name_similarity + _TOKEN_OVERLAP_WEIGHT * token_overlap


def _haversine_km(lat1, lon1, lat2, lon2) -> Optional[float]:
    if None in (lat1, lon1, lat2, lon2):
        return None
    radius = 6371.0088
    lat1r, lat2r = math.radians(lat1), math.radians(lat2)
    dlat = lat2r - lat1r
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(lat1r) * math.cos(lat2r) * math.sin(dlon / 2) ** 2
    )
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _parse_bias(location_bias: Optional[str]):
    if not location_bias:
        return None, None
    try:
        lat_str, lon_str = location_bias.split(",")
        return float(lat_str), float(lon_str)
    except (ValueError, AttributeError):
        return None, None


def classify_ola_candidates(query: str, candidates: list, location_bias: Optional[str] = None) -> dict:
    """
    Scores Ola's own autocomplete candidates against the raw query text
    (see _score_against_query() and this module's docstring for why
    that is a purpose-built formula, not score_candidate() reused
    as-is) plus a hard distance gate against location_bias when both
    are available. Never trusts Ola's own result ordering blindly (Ola
    is a discovery/ranking provider, not a confidence oracle).

    Returns:
        {
            "status": "matched" | "ambiguous" | "no_match",
            "best": candidate dict | None,
            "confidence": float | None,
            "alternates": [candidate dict, ...],  # populated for
                "ambiguous" (includes the top candidate too, matching
                osm_location_service.py's own convention), empty
                otherwise.
        }
    """

    if not candidates:
        return {"status": "no_match", "best": None, "confidence": None, "alternates": []}

    bias_lat, bias_lon = _parse_bias(location_bias)

    scored = []

    for candidate in candidates:

        if bias_lat is not None and candidate.get("latitude") is not None:
            distance_km = _haversine_km(
                bias_lat, bias_lon, candidate["latitude"], candidate["longitude"]
            )
            if distance_km is not None and distance_km > _MAX_BIAS_DISTANCE_KM:
                # Hard gate - too far from the search area to be a
                # plausible match regardless of text score (see this
                # module's docstring for why this, not text scoring, is
                # what actually protects generic local queries).
                continue

        score = _score_against_query(query, candidate)
        scored.append((candidate, score))

    if not scored:
        return {"status": "no_match", "best": None, "confidence": None, "alternates": []}

    scored.sort(key=lambda pair: -pair[1])

    best_candidate, best_score = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else None
    margin = (best_score - second_score) if second_score is not None else None

    if best_score < _MIN_SCORE:
        return {"status": "no_match", "best": None, "confidence": best_score, "alternates": []}

    if margin is not None and margin < _MIN_MARGIN:
        return {
            "status": "ambiguous",
            "best": None,
            "confidence": best_score,
            "alternates": [c for c, _ in scored[:4]],
        }

    return {
        "status": "matched",
        "best": best_candidate,
        "confidence": best_score,
        "alternates": [],
    }


def resolve_location_via_ola(query: str, ola_api_key: Optional[str], location_bias: Optional[str] = None) -> dict:
    """
    The Ola-only half of this phase's resolution pipeline: Autocomplete
    -> classify_ola_candidates() -> Place Details for the winning
    candidate. Never falls back to Mappls/OSM itself - see this
    module's docstring for why that composition lives at the caller.

    Returns a dict shaped compatibly with
    services/search_orchestration.py's resolve_poi_location():
        {
            "status": "matched" | "ambiguous" | "no_match" | "error",
            "latitude": float | None,
            "longitude": float | None,
            "place_name": str | None,
            "formatted_address": str | None,
            "confidence": float | None,
            "error": str | None,
            "alternates": [{matched_name, matched_address, latitude,
                             longitude, score}, ...],
            "provider": "ola",
        }
    """

    result = {
        "status": "error",
        "latitude": None,
        "longitude": None,
        "place_name": None,
        "formatted_address": None,
        "confidence": None,
        "error": None,
        "alternates": [],
        "provider": "ola",
    }

    autocomplete_result = ola_maps_service.autocomplete(
        query, ola_api_key, location_bias=location_bias
    )

    if autocomplete_result["status"] == "error":
        result["status"] = "error"
        result["error"] = autocomplete_result["error"]
        return result

    if autocomplete_result["status"] == "no_match":
        result["status"] = "no_match"
        result["error"] = "Ola Maps found no candidates."
        return result

    classification = classify_ola_candidates(
        query, autocomplete_result["candidates"], location_bias=location_bias
    )

    if classification["status"] == "no_match":
        result["status"] = "no_match"
        result["error"] = "No Ola candidate was a confident enough match."
        return result

    if classification["status"] == "ambiguous":
        result["status"] = "ambiguous"
        result["confidence"] = classification["confidence"]
        result["error"] = "Top Ola candidates were too close to distinguish confidently."
        result["alternates"] = [
            {
                "matched_name": c.get("name"),
                "matched_address": c.get("address"),
                "latitude": c.get("latitude"),
                "longitude": c.get("longitude"),
                "score": None,
                # Additive vs. the OSM-ambiguous alternate shape this
                # mirrors (services/osm_location_service.py never has a
                # place_id/provider concept - it has no refinement step
                # of its own). A caller that already only reads
                # matched_name/matched_address/latitude/longitude/score
                # (e.g. templates/rentals.html's EXISTING picker, before
                # this phase) is unaffected - these are new keys, not
                # changed ones. What a caller NEEDS these two new keys
                # for: once the user picks ONE of these alternates, the
                # existing routes/property_routes.py
                # /api/location/resolve-candidate endpoint (already
                # used by the property-registration flow for exactly
                # this) can re-resolve it via Ola Place Details for
                # authoritative coordinates - see that endpoint's own
                # resolve_selected_candidate() docstring for why a raw
                # autocomplete coordinate should not be trusted as
                # final on its own.
                "place_id": c.get("place_id"),
                "provider": "ola",
            }
            for c in classification["alternates"]
        ]
        return result

    # MATCHED at the discovery/confidence-scoring stage - now resolve
    # the WINNING candidate's authoritative coordinates via Place
    # Details, exactly per this phase's required flow (never trust
    # Autocomplete's own coordinates as final).
    best = classification["best"]

    details = ola_maps_service.get_place_details(best["place_id"], ola_api_key)

    if details["status"] == "error":
        result["status"] = "error"
        result["error"] = details["error"]
        return result

    if details["status"] == "no_match":
        result["status"] = "no_match"
        result["error"] = "Ola Place Details returned no usable coordinates for the matched candidate."
        return result

    result["status"] = "matched"
    result["latitude"] = details["latitude"]
    result["longitude"] = details["longitude"]
    result["place_name"] = details["name"] or best.get("name")
    result["formatted_address"] = details["formatted_address"] or best.get("address")
    result["confidence"] = classification["confidence"]

    return result


def resolve_selected_candidate(candidate: dict, ola_api_key: Optional[str] = None, osm_service=None) -> dict:
    """
    Resolves ONE user-selected autocomplete candidate (from either
    provider - see routes/property_routes.py's location_autocomplete())
    to final coordinates + a structured address breakdown, for the
    property-registration flow specifically ("user selects candidate ->
    Place Details -> lat/lng -> map marker").

    candidate: {"provider": "ola"|"mappls", "place_id": str|None,
                "name": str, "address": str}

    Returns:
        {
            "status": "matched" | "no_match" | "error",
            "latitude": float | None,
            "longitude": float | None,
            "formatted_address": str | None,
            "city": str | None,
            "state": str | None,
            "locality": str | None,
            "sub_locality": str | None,
            "postcode": str | None,
            "error": str | None,
            "provider": str,
        }
    """

    provider = candidate.get("provider")

    if provider == "ola":

        details = ola_maps_service.get_place_details(candidate.get("place_id"), ola_api_key)

        return {
            "status": details["status"],
            "latitude": details["latitude"],
            "longitude": details["longitude"],
            "formatted_address": details["formatted_address"],
            "city": details["city"],
            "state": details["state"],
            "locality": details["locality"],
            "sub_locality": details["sub_locality"],
            "postcode": details["postcode"],
            "error": details["error"],
            "provider": "ola",
        }

    if provider == "mappls" and osm_service is not None:

        # The Mappls entity (place_name/address) was already resolved
        # when this candidate was created (see
        # routes/property_routes.py's Mappls-fallback autocomplete
        # branch) - only OSM coordinate resolution is needed here,
        # reusing the existing, unmodified osm_location_service.py.
        osm_result = osm_service.resolve_coordinates({
            "place_name": candidate.get("name"),
            "address": candidate.get("address"),
        })

        matched = osm_result["status"] == "matched"

        return {
            "status": osm_result["status"],
            "latitude": osm_result["latitude"] if matched else None,
            "longitude": osm_result["longitude"] if matched else None,
            "formatted_address": osm_result["display_name"] if matched else None,
            "city": None,
            "state": None,
            "locality": None,
            "sub_locality": None,
            "postcode": None,
            "error": osm_result["error"],
            "provider": "osm",
        }

    return {
        "status": "error",
        "latitude": None,
        "longitude": None,
        "formatted_address": None,
        "city": None,
        "state": None,
        "locality": None,
        "sub_locality": None,
        "postcode": None,
        "error": "Unknown candidate provider.",
        "provider": provider,
    }
