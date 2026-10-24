"""
Square Yards external rental-listing search provider, via the Square
Yards MCP connector (https://sy-mcp.squareyards.com/mcp/external).

ARCHITECTURE (explicitly chosen, do not change without discussion -
see Phase 7's isolated smoke test and its written report for the
evidence this is built on): Square Yards is an EXTERNAL, LIVE SEARCH
SOURCE, never a permanent data source.

    StructuredQuery (from the EXISTING, unmodified services/nlp/
    parser, already merged with any explicit overrides by
    services/search_orchestration.py's merge_structured_fields())
        |
        v
    search_rental_properties()  <- THIS MODULE, only entry point
        |                           other code should call
        v
    Square Yards MCP search_properties (remote call, every time -
    no local cache, no MongoDB collection, nothing persisted)
        |
        v
    normalized listing dicts, already safety-filtered against the
    SAME structured requirements the caller gave us
        |
        v
    (caller's job, not this module's: optionally call
    fetch_listing_image_bytes() per surviving candidate, run them
    through the EXISTING SiglipEncoder, discard the bytes)

What this module NEVER does:
  - insert anything into MongoDB (no collection, no document, ever)
  - persist an image or an embedding beyond the current request
  - invent a field Square Yards didn't actually provide (created_at/
    updated_at/coordinates above all - see the Phase 7 report's field-
    availability table; Square Yards simply does not have these)
  - raise an exception to its caller for an expected failure (MCP
    down, timeout, malformed response, zero results) - every public
    function here returns a safe, documented value instead, mirroring
    services/mappls_service.py's established "never raises" contract
    so routes/search_routes.py and routes/design_routes.py never need
    a provider-specific try/except of their own beyond what they
    already have for their own internal calls

The `mcp` package (official Python MCP SDK) is imported LAZILY, inside
is_enabled()/the functions that need it - never at module import time.
If it is not installed, or SQUARE_YARDS_ENABLED is falsy, every public
function here degrades to "provider unavailable" (empty results / None)
rather than raising ImportError into a route. This mirrors
routes/design_routes.py's existing "import torch lazily, only on the
route that needs it" convention for services.image_similarity.
"""

from __future__ import annotations

import asyncio
import os
import re
from typing import Optional
from urllib.parse import urlsplit

import requests


DEFAULT_MCP_URL = "https://sy-mcp.squareyards.com/mcp/external"
SOURCE_NAME = "squareyards"

# ============================================================
# LIMITS (Phase 14 - keep the external search bounded and fast)
# ============================================================

MAX_LISTINGS_PER_SEARCH = 8          # how many Square Yards listings we ever fetch per query
MAX_LISTINGS_SCORED_FOR_IMAGES = 5   # how many of those we ever download+embed images for
MAX_IMAGES_PER_LISTING = 1           # images downloaded per listing (keeps latency bounded)
MCP_CALL_TIMEOUT_SECONDS = 12
IMAGE_DOWNLOAD_TIMEOUT_SECONDS = 8
MAX_IMAGE_DOWNLOAD_BYTES = 10 * 1024 * 1024  # 10MB safety cap per image


# ============================================================
# FIELD MAPPING TABLES (explicit - see this module's docstring: never
# guess a mapping that isn't a genuine 1:1 correspondence)
# ============================================================

# services/property_fields.py's PROPERTY_TYPES -> Square Yards
# search_properties' propertyTypeName enum. Only types with a clean,
# unambiguous match are listed - "farm_house"/"pg_hostel"/"commercial"/
# "other" have no safe Square Yards equivalent and are deliberately
# left unmapped (the search then omits propertyTypeName entirely,
# which Square Yards' own tool description says defaults to
# "residential types" - a reasonable, disclosed fallback, not a guess).
SMARTHOMES_TO_SY_PROPERTY_TYPE = {
    "apartment": "Apartment",
    "independent_house": "Independent House",
    "villa": "Villa",
    "builder_floor": "Builder Floor",
    "plot": "Plot",
}

# services/property_fields.py's FURNISHING_OPTIONS <-> Square Yards'
# "Furnishing Status" attribute values. Square Yards' plain "Furnished"
# means fully furnished (there is no separate "Fully Furnished" string
# observed in the Phase 7 live data) - this is the one non-obvious
# mapping in this table, called out explicitly rather than left to a
# naive case-fold.
SMARTHOMES_TO_SY_FURNISHING = {
    "unfurnished": "Unfurnished",
    "semi_furnished": "Semi-Furnished",
    "fully_furnished": "Furnished",
}
SY_TO_SMARTHOMES_FURNISHING = {
    "unfurnished": "unfurnished",
    "semi-furnished": "semi_furnished",
    "semi furnished": "semi_furnished",
    "furnished": "fully_furnished",
    "fully furnished": "fully_furnished",
    "fully-furnished": "fully_furnished",
}

SMARTHOMES_TO_SY_LISTING_TYPE = {"rent": "Rent", "sell": "Sale"}

# The reverse direction - Square Yards' OWN transactionType/listingType
# values (as actually observed in its live responses) -> SmartHomes'
# internal listing_type vocabulary (services/nlp/schema.py's
# LISTING_TYPES = {"rent", "sell"}). The one non-obvious mapping,
# mirroring SY_TO_SMARTHOMES_FURNISHING just above: Square Yards says
# "sale", SmartHomes says "sell" - a bare .lower() of Square Yards'
# own string is NOT SmartHomes' vocabulary and was silently causing
# every Sale listing to fail _matches_safety_filter()'s listing_type
# comparison. Centralized here rather than a "sale" -> "sell" string
# comparison scattered through _normalize_search_card()/
# normalize_listing_detail().
SY_TO_SMARTHOMES_LISTING_TYPE = {
    "rent": "rent",
    "sale": "sell",
}


# ============================================================
# CONFIGURATION
# ============================================================

def _mcp_url(config: Optional[dict] = None) -> str:
    if config and config.get("SQUARE_YARDS_MCP_URL"):
        return config["SQUARE_YARDS_MCP_URL"]
    return os.getenv("SQUARE_YARDS_MCP_URL", DEFAULT_MCP_URL)


def is_enabled(config: Optional[dict] = None) -> bool:
    """False disables Square Yards EVERYWHERE this module is called
    from, with zero other code changes needed - the documented escape
    hatch for Phase 5's "external provider failure must never break
    the existing search experience" when the operator wants to turn
    this off entirely (e.g. during an incident), not just when a
    single call happens to fail.

    Also returns False if the `mcp` SDK is not importable - a missing
    optional dependency degrades the feature, it never crashes the
    app (see this module's docstring)."""

    if config and "SQUARE_YARDS_ENABLED" in config:
        enabled_flag = config["SQUARE_YARDS_ENABLED"]
    else:
        enabled_flag = os.getenv("SQUARE_YARDS_ENABLED", "true")

    if isinstance(enabled_flag, str):
        enabled_flag = enabled_flag.strip().lower() not in ("false", "0", "no", "")

    if not enabled_flag:
        return False

    try:
        import mcp  # noqa: F401
    except ImportError:
        return False

    return True


# ============================================================
# URL CONSTRUCTION (Phase 2 - the ONE place this happens)
# ============================================================

SQUARE_YARDS_DOMAIN = "https://www.squareyards.com"


def build_listing_url(raw_url_field: Optional[str]) -> Optional[str]:
    """Turns whatever Square Yards' `listingData.url` field actually
    contains into a safe, absolute, openable URL - or None if it
    can't.

    Proven (Phase 7 isolated test, 8/8 listings, 2/8 additionally
    visually confirmed in a real browser) behavior for this field:
    Square Yards ALWAYS returns a RELATIVE slug of the shape
    "<descriptive-slug>/<numeric-id>", never a complete URL - but this
    function still handles an already-complete URL defensively (option
    A from that test's investigation), in case that ever changes.

    Rules (Phase 2's explicit requirements):
      - an already-complete https:// (or http://) URL is returned as-is
        ONLY if it points at squareyards.com (never silently open-
        redirects through an unrelated domain some other field might
        contain)
      - a relative path is prefixed with SQUARE_YARDS_DOMAIN
      - never produces a double slash at the join point
      - rejects empty/None/whitespace-only input
      - rejects a value that is obviously not a URL path at all (e.g.
        contains whitespace, or has no segments) - this function never
        fabricates a URL from an unrelated field; the caller is
        responsible for only ever passing the actual url-shaped field
    """

    if not raw_url_field or not isinstance(raw_url_field, str):
        return None

    candidate = raw_url_field.strip()
    if not candidate:
        return None

    if " " in candidate or "\t" in candidate or "\n" in candidate:
        return None

    if candidate.startswith("http://") or candidate.startswith("https://"):
        parsed = urlsplit(candidate)
        host = (parsed.netloc or "").lower()
        if host == "squareyards.com" or host.endswith(".squareyards.com"):
            return candidate
        return None

    # Relative path case (the one Square Yards actually uses).
    relative = candidate.lstrip("/")
    if not relative:
        return None

    return f"{SQUARE_YARDS_DOMAIN}/{relative}"


# ============================================================
# STRUCTURED-QUERY -> SQUARE YARDS SEARCH ARGS (Phase 4)
#
# Consumes the SAME `applied_filters` dict
# services/search_orchestration.py's orchestrate_search() already
# returns (StructuredQuery already merged with any explicit overrides,
# override-wins-over-parsed) - no second NLP pass, no fork of the
# parser.
# ============================================================

def _bhk_to_sy_bedrooms(bhk) -> Optional[str]:
    if bhk is None:
        return None
    try:
        bhk_float = float(bhk)
    except (TypeError, ValueError):
        return None
    if bhk_float == int(bhk_float):
        return f"{int(bhk_float)} BHK"
    return f"{bhk_float:g} BHK"


def build_search_args(applied_filters: dict, max_listings: int = MAX_LISTINGS_PER_SEARCH) -> Optional[dict]:
    """Returns Square Yards search_properties() arguments, or None if
    there isn't enough structured information to make a Square Yards
    search meaningful.

    EXPLICIT SCOPE DECISION: a search is only attempted when
    `applied_filters` has both a listing_type AND a city/locality text
    - Square Yards' own tool requires listingType, and there is no
    honest city-less default to search against (SmartHomes has no
    "search everywhere" concept for an external, nationwide provider).
    A pure image-only query (no text, see routes/design_routes.py's
    find_similar()) naturally has neither field and therefore produces
    no Square Yards candidates at all - a deliberate, disclosed
    behavior, not a bug (see the Phase 8 report's "image-only search"
    test for the explicit statement of this)."""

    listing_type = applied_filters.get("listing_type")
    city_or_locality = applied_filters.get("area_or_city_text")

    sy_listing_type = SMARTHOMES_TO_SY_LISTING_TYPE.get(listing_type)
    if not sy_listing_type or not city_or_locality:
        return None

    args = {
        "listingType": sy_listing_type,
        "location": city_or_locality,
        "size": max_listings,
    }

    property_type = applied_filters.get("property_type")
    sy_property_type = SMARTHOMES_TO_SY_PROPERTY_TYPE.get(property_type)
    if sy_property_type:
        args["propertyTypeName"] = sy_property_type

    bhk = applied_filters.get("bhk")
    sy_bedrooms = _bhk_to_sy_bedrooms(bhk)
    if sy_bedrooms:
        args["bedrooms"] = sy_bedrooms

    furnishing = applied_filters.get("furnishing")
    sy_furnishing = SMARTHOMES_TO_SY_FURNISHING.get(furnishing)
    if sy_furnishing:
        args["furnishing"] = sy_furnishing

    price = applied_filters.get("price") or {}
    mongo_price = price.get("mongo") or {}
    if "$lte" in mongo_price:
        args["maxPrice"] = int(mongo_price["$lte"])
    if "$gte" in mongo_price:
        args["minPrice"] = int(mongo_price["$gte"])

    return args


# ============================================================
# NORMALIZATION (Phase 1's "normalized object")
# ============================================================

def _normalize_search_card(card: dict) -> dict:
    """Normalizes ONE search_properties() result card. Only fields
    Square Yards actually returned are populated - never invents a
    missing one (see this module's docstring)."""

    furnishing_raw = None  # search cards don't carry furnishing; detail calls do
    slug = card.get("url")

    return {
        "source": SOURCE_NAME,
        "external_id": card.get("id"),
        "title": card.get("title"),
        "listing_type": SY_TO_SMARTHOMES_LISTING_TYPE.get(
            (card.get("transactionType") or "").strip().lower()
        ),
        "price": card.get("price"),
        "price_on_request": bool(card.get("priceOnRequest")),
        "bhk": card.get("bhk"),
        "area_sqft": card.get("areaSqft"),
        "property_type": card.get("propertyType"),
        "furnishing": furnishing_raw,
        "amenities": card.get("amenities") or [],
        "locality": card.get("locality"),
        "city": card.get("city"),
        "images": [card["image"]] if card.get("image") else [],
        "source_url": build_listing_url(slug),
    }


def _bhk_from_unit_type(unit_type: Optional[str]) -> Optional[float]:
    """listingData has no direct numeric BHK field - only a display
    string like "2 BHK" (unitType). Extracts the leading number if the
    string actually looks like a BHK label; returns None for anything
    else ("Studio", "1 RK", missing) rather than guessing."""

    if not unit_type or not isinstance(unit_type, str):
        return None
    match = re.match(r"^\s*(\d+(?:\.\d+)?)\s*BHK\b", unit_type, re.IGNORECASE)
    if not match:
        return None
    return float(match.group(1))


def normalize_listing_detail(detail_structured_content: dict) -> Optional[dict]:
    """Normalizes ONE get_entity_details(entity="listing") response's
    structured_content into the Phase 1 shape. Returns None if the
    response doesn't look like a listing detail at all (defensive -
    Phase 13's "MCP returns malformed response" case)."""

    if not isinstance(detail_structured_content, dict):
        return None

    detail = (detail_structured_content.get("detail") or {})
    listing_data = detail.get("listingData")
    if not isinstance(listing_data, dict):
        return None

    attrs = listing_data.get("attributes") or {}
    furnishing_raw = attrs.get("Furnishing Status")
    furnishing = None
    if furnishing_raw:
        furnishing = SY_TO_SMARTHOMES_FURNISHING.get(furnishing_raw.strip().lower())

    price = listing_data.get("totalPrice")
    if price is not None:
        try:
            price = float(price)
        except (TypeError, ValueError):
            price = None

    return {
        "source": SOURCE_NAME,
        "external_id": str(listing_data.get("propertyId")) if listing_data.get("propertyId") is not None else None,
        "title": listing_data.get("propertyTitle"),
        "listing_type": SY_TO_SMARTHOMES_LISTING_TYPE.get(
            (listing_data.get("listingType") or "").strip().lower()
        ),
        "price": price,
        "price_on_request": price is None,
        "bhk": _bhk_from_unit_type(listing_data.get("unitType")),
        "area_sqft": listing_data.get("atreaInSqFt"),
        "property_type": listing_data.get("propertyType"),
        "furnishing": furnishing,
        "amenities": listing_data.get("amenities") or [],
        "locality": listing_data.get("subLocalityName"),
        "city": listing_data.get("cityName"),
        "images": listing_data.get("images") or [],
        "source_url": build_listing_url(listing_data.get("url")),
    }


def _matches_safety_filter(normalized: dict, applied_filters: dict) -> bool:
    """Second safety layer (Phase 4's explicit requirement): Square
    Yards' OWN search filters are a first pass we don't fully trust to
    be exact (e.g. "furnishing" sparse-data caveat seen in its own tool
    description during the Phase 7 test) - this re-checks every hard
    requirement SmartHomes' NLP actually parsed, using the SAME
    normalized fields a SmartHomes MongoDB candidate would be checked
    against. A listing missing a given field is never auto-rejected
    for that one field (Square Yards doesn't always provide it) -
    only an OUTRIGHT MISMATCH on a field both sides have rejects it."""

    listing_type = applied_filters.get("listing_type")
    if listing_type and normalized.get("listing_type"):
        if normalized["listing_type"] != listing_type:
            return False

    bhk = applied_filters.get("bhk")
    if bhk is not None and normalized.get("bhk") is not None:
        try:
            if float(normalized["bhk"]) != float(bhk):
                return False
        except (TypeError, ValueError):
            pass

    furnishing = applied_filters.get("furnishing")
    if furnishing and normalized.get("furnishing"):
        if normalized["furnishing"] != furnishing:
            return False

    price = applied_filters.get("price") or {}
    mongo_price = price.get("mongo") or {}
    if normalized.get("price") is not None:
        if "$lte" in mongo_price and normalized["price"] > mongo_price["$lte"]:
            return False
        if "$gte" in mongo_price and normalized["price"] < mongo_price["$gte"]:
            return False

    return True


# ============================================================
# MCP TRANSPORT (sync wrapper around the async MCP client - the
# approach proven working in the Phase 7 isolated smoke test)
# ============================================================

async def _mcp_call_tool_async(mcp_url: str, tool_name: str, arguments: dict, timeout_seconds: float):
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    async with streamable_http_client(mcp_url) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout=timeout_seconds)
            result = await asyncio.wait_for(
                session.call_tool(tool_name, arguments), timeout=timeout_seconds
            )
            structured = getattr(result, "structuredContent", None) or getattr(
                result, "structured_content", None
            )
            return structured


def _call_tool(tool_name: str, arguments: dict, config: Optional[dict] = None) -> Optional[dict]:
    """Synchronous entry point used by every function below. NEVER
    raises - any failure (connection, timeout, malformed response,
    missing SDK) logs a short internal message (no secrets - this
    endpoint needs none, see this module's docstring) and returns
    None, which every caller already treats as "no result"."""

    if not is_enabled(config):
        return None

    mcp_url = _mcp_url(config)

    try:
        return asyncio.run(
            _mcp_call_tool_async(mcp_url, tool_name, arguments, MCP_CALL_TIMEOUT_SECONDS)
        )
    except Exception as exc:  # noqa: BLE001 - every external-call failure mode lands here
        print(f"Square Yards MCP call failed (tool={tool_name}): {exc!r}")
        return None


# ============================================================
# PUBLIC INTERFACE
# ============================================================

def search_rental_properties(
    applied_filters: dict,
    max_listings: int = MAX_LISTINGS_PER_SEARCH,
    config: Optional[dict] = None,
) -> list:
    """THE main entry point. Returns a list of normalized, ALREADY
    safety-filtered listing dicts (Phase 1's shape) - [] whenever
    Square Yards is disabled, unreachable, times out, returns a
    malformed response, or genuinely has zero matches. Callers never
    need to distinguish these cases to stay safe (Phase 5/13) - an
    empty list is always a valid "no external results this time"."""

    if not is_enabled(config):
        return []

    search_args = build_search_args(applied_filters, max_listings=max_listings)
    if search_args is None:
        return []

    structured = _call_tool("search_properties", search_args, config=config)
    if not isinstance(structured, dict):
        return []

    cards = structured.get("listings")
    if not isinstance(cards, list):
        return []

    normalized_candidates = []
    for card in cards:
        if not isinstance(card, dict) or not card.get("id"):
            continue
        normalized_candidates.append(_normalize_search_card(card))

    survivors = [n for n in normalized_candidates if _matches_safety_filter(n, applied_filters)]
    survivors = survivors[:max_listings]

    if applied_filters.get("furnishing"):
        # An EXPLICIT furnishing requirement needs a stronger guarantee
        # than _matches_safety_filter()'s normal "don't reject on a
        # field the listing just doesn't have" rule (search_properties
        # cards never carry furnishing at all - see
        # _normalize_search_card()). A candidate whose furnishing is
        # still unknown at this point must not be surfaced as a
        # confirmed match for an explicit requirement - see
        # _resolve_unknown_furnishing()'s own docstring for exactly
        # how that's resolved (and when it's dropped instead).
        survivors = _resolve_unknown_furnishing(survivors, applied_filters, config=config)

    return survivors


def _resolve_unknown_furnishing(candidates: list, applied_filters: dict, config: Optional[dict] = None) -> list:
    """Only called when applied_filters has an EXPLICIT furnishing
    requirement (see search_rental_properties() above). For each
    candidate whose furnishing is ALREADY known (truthy), does nothing
    - it already passed (or would have failed) the furnishing check
    inside _matches_safety_filter() before this function ever runs, so
    re-checking it here would be a redundant get_entity_details() call
    for a field already available (explicitly disallowed).

    For each candidate whose furnishing is UNKNOWN (search cards never
    carry it), fetches get_entity_details() - bounded by the SAME
    `candidates` list this receives, which search_rental_properties()
    already capped to `max_listings` before calling this, so no new
    limit is introduced - and re-normalizes with that one field filled
    in (plus a fuller image array, if the search card's was thin;
    bhk/price/listing_type are NOT overwritten from the detail call -
    the search card's own values for those are kept, since they are
    already reliable there and detail's bhk is itself only an inferred
    parse of a display string - see normalize_listing_detail()'s
    _bhk_from_unit_type()).

    A details call failure, OR a details response that STILL has no
    furnishing value, means the requirement cannot be confirmed - the
    candidate is DROPPED, never kept "just in case" (the explicit
    instruction this exists to satisfy: an unknown furnishing must
    never be treated as a confirmed match for an explicit
    requirement). This is a different policy from get_listing_images()
    /get_listing_details()'s own callers, which keep a candidate on a
    details failure (there, the search card's own data is still a
    perfectly valid partial result - here, specifically the ONE field
    the user explicitly asked for would otherwise be silently
    unverified)."""

    resolved = []

    for candidate in candidates:

        if candidate.get("furnishing"):
            resolved.append(candidate)
            continue

        detail = get_listing_details(candidate.get("external_id"), config=config)

        if detail is None or not detail.get("furnishing"):
            continue

        merged = dict(candidate)
        merged["furnishing"] = detail["furnishing"]
        if not merged.get("images") and detail.get("images"):
            merged["images"] = detail["images"]

        if _matches_safety_filter(merged, applied_filters):
            resolved.append(merged)

    return resolved


def get_listing_details(external_id: str, config: Optional[dict] = None) -> Optional[dict]:
    """Fetches the richer get_entity_details() view for one listing
    (fuller image array, furnishing). Returns None on any failure -
    callers that already have a search-card-normalized dict should
    treat that as "use what the search card already had", never as a
    reason to drop the listing (Phase 13: a details failure must not
    lose an otherwise-valid candidate)."""

    if not external_id or not is_enabled(config):
        return None

    structured = _call_tool(
        "get_entity_details", {"entity": "listing", "id": str(external_id)}, config=config
    )
    return normalize_listing_detail(structured) if structured else None


def get_listing_images(normalized_listing: dict, max_images: int = MAX_IMAGES_PER_LISTING, config: Optional[dict] = None) -> list:
    """Returns up to `max_images` direct CDN image URLs for a
    normalized listing. Tries a get_entity_details() call first (fuller
    image array - search cards carry only one thumbnail), falling back
    to whatever the search card already had if the details call fails
    for any reason. Never raises; [] means "no images available",
    which callers must already treat as a valid, non-fatal case
    (Phase 6: "If no valid images are available: return the listing
    without an image similarity score rather than failing")."""

    images = normalized_listing.get("images") or []

    if len(images) < max_images:
        detail = get_listing_details(normalized_listing.get("external_id"), config=config)
        if detail and detail.get("images"):
            images = detail["images"]

    return [url for url in images[:max_images] if isinstance(url, str) and url]


def fetch_listing_image_bytes(image_url: str, timeout_seconds: float = IMAGE_DOWNLOAD_TIMEOUT_SECONDS) -> Optional[bytes]:
    """Downloads ONE image's bytes for TRANSIENT use only (the caller
    is responsible for discarding them after SigLIP2 encoding - this
    function itself never writes to disk or to any cache). Returns
    None for any failure: network error, timeout, non-2xx status, a
    response that isn't actually image content, or one over the size
    cap (Phase 13's "image URL fails" / "image is invalid" cases)."""

    if not image_url or not isinstance(image_url, str):
        return None

    try:
        response = requests.get(
            image_url,
            timeout=timeout_seconds,
            headers={"User-Agent": "Mozilla/5.0 (SmartHomes external-search image fetch)"},
            stream=True,
        )
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "")
        if content_type and not content_type.startswith("image/"):
            return None

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=65536):
            total += len(chunk)
            if total > MAX_IMAGE_DOWNLOAD_BYTES:
                return None
            chunks.append(chunk)

        return b"".join(chunks)

    except requests.RequestException as exc:
        print(f"Square Yards image download failed ({image_url}): {exc!r}")
        return None
