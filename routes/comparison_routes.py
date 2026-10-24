"""
Property Comparison routes.

Two routes, read-only (no @require_csrf - matches the existing
convention that only the 4 property-MUTATION routes in
routes/property_routes.py carry CSRF protection; search_rentals()
in routes/search_routes.py is the same kind of GET/POST-but-read-only
endpoint and is likewise unprotected by CSRF, only by @login_required):

    GET /compare        - renders the comparison page shell
    GET /api/compare     - returns comparison data + ratings as JSON

This module does NOT talk to MongoDB or the Square Yards MCP itself -
it uses the EXISTING services.property_services.PropertyService (via
get_property_service(), the same accessor routes/property_routes.py
already uses) and the EXISTING
services.external_property_sources.square_yards_service.get_listing_details()
(the same function routes/design_routes.py and routes/search_routes.py
rely on for "never raises, returns None on any failure"). All rating
math happens in services/comparison_service.py, which this module
calls but never duplicates.
"""

from flask import Blueprint, current_app, jsonify, render_template, request
from flask_login import login_required

from services.external_property_sources import square_yards_service
from services.comparison_service import (
    compare_properties,
    smarthomes_property_to_row,
    square_yards_listing_to_row,
)


comparison_bp = Blueprint(
    "comparison",
    __name__
)


MIN_COMPARE_ITEMS = 2
MAX_COMPARE_ITEMS = 4
VALID_PROVIDERS = {"smarthomes", "squareyards"}


def get_property_service():
    return current_app.extensions["property_service"]


# ============================================================
# REQUEST PARSING / VALIDATION
# ============================================================

def _parse_items_param(raw_value):
    """Parses `items=provider:id,provider:id,...` into a list of
    (provider, id) tuples, or raises ValueError with a user-facing
    message for any malformed input. Never raises an unhandled
    exception - every failure mode here is translated to a clear 400."""

    if not raw_value or not raw_value.strip():
        raise ValueError("No properties selected for comparison.")

    parts = [p.strip() for p in raw_value.split(",") if p.strip()]

    if not parts:
        raise ValueError("No properties selected for comparison.")

    if len(parts) < MIN_COMPARE_ITEMS:
        raise ValueError(f"Select at least {MIN_COMPARE_ITEMS} properties to compare.")

    if len(parts) > MAX_COMPARE_ITEMS:
        raise ValueError(f"Compare at most {MAX_COMPARE_ITEMS} properties at a time.")

    parsed = []
    seen = set()

    for part in parts:
        if ":" not in part:
            raise ValueError(f"Malformed selection: '{part}'.")

        provider, _, item_id = part.partition(":")
        provider = provider.strip().lower()
        item_id = item_id.strip()

        if provider not in VALID_PROVIDERS:
            raise ValueError(f"Unknown provider: '{provider}'.")

        if not item_id:
            raise ValueError(f"Missing id for provider '{provider}'.")

        key = (provider, item_id)
        if key in seen:
            raise ValueError(f"Duplicate selection: {provider}:{item_id}.")
        seen.add(key)

        parsed.append(key)

    return parsed


# ============================================================
# FETCH (reuses EXISTING services only)
# ============================================================

def _fetch_entry(provider, item_id):
    """Returns (entry_dict_or_None, error_reason_or_None). An entry is
    {"provider", "id", "row": ComparisonRow, "raw": <source payload>}.
    Never raises - a not-found SmartHomes id or a failed Square Yards
    lookup both become a clear per-item reason string instead, so one
    bad selection never breaks the whole comparison (Phase 3's
    explicit requirement, matching the same "never raises" contract
    services/external_property_sources/square_yards_service.py
    already documents for every other caller)."""

    if provider == "smarthomes":
        document = get_property_service().get_property(item_id)
        if not document:
            return None, "Property not found."
        row = smarthomes_property_to_row(item_id, document)
        return {"provider": provider, "id": item_id, "row": row, "raw": document}, None

    # provider == "squareyards" (the only other value _parse_items_param allows)
    try:
        normalized = square_yards_service.get_listing_details(
            item_id, config=current_app.config
        )
    except Exception as error:  # noqa: BLE001 - external provider must never break this route
        print(f"Square Yards comparison lookup failed: {error!r}")
        normalized = None

    if not normalized:
        return None, "Square Yards listing could not be retrieved."

    row = square_yards_listing_to_row(normalized)
    return {"provider": provider, "id": item_id, "row": row, "raw": normalized}, None


# ============================================================
# ROUTES
# ============================================================

@comparison_bp.route(
    "/compare",
    methods=["GET"]
)
@login_required
def compare_page():
    return render_template("compare.html")


@comparison_bp.route(
    "/api/compare",
    methods=["GET"]
)
@login_required
def compare_api():

    try:
        selections = _parse_items_param(request.args.get("items"))
    except ValueError as error:
        return jsonify({"error": str(error)}), 400

    properties = []
    failed = []

    for provider, item_id in selections:
        entry, reason = _fetch_entry(provider, item_id)
        if entry is None:
            failed.append({"provider": provider, "id": item_id, "reason": reason})
        else:
            properties.append(entry)

    results = compare_properties(properties)

    response_properties = [
        {**result["row"], "ratings": result["ratings"]}
        for result in results
    ]

    return jsonify({
        "properties": response_properties,
        "failed": failed,
    })
