import base64
import io
import os

from flask import (
    Blueprint,
    render_template,
    request,
    jsonify,
    current_app,
    url_for
)

from flask_login import login_required

from services.image_service import (
    ImageGenerationService
)

from services import media_service
from services.media_service import MediaValidationError


design_bp = Blueprint(
    "design",
    __name__
)

image_service = ImageGenerationService()



@design_bp.route("/design")
@login_required
def design():

    return render_template(
        "design.html"
    )


@design_bp.route(
    "/generate_image",
    methods=["POST"]
)
@login_required
def generate_image():

    data = request.get_json()

    if not data or "prompt" not in data:

        return jsonify({
            "error": "No prompt provided."
        }), 400

    prompt = data["prompt"].strip()

    if not prompt:

        return jsonify({
            "error": "Prompt cannot be empty."
        }), 400

    try:

        image = image_service.generate(
            prompt
        )

        buffered = io.BytesIO()

        image.save(
            buffered,
            format="PNG"
        )

        image_base64 = base64.b64encode(
            buffered.getvalue()
        ).decode("utf-8")

        return jsonify({
            "image_url": (
                "data:image/png;base64,"
                + image_base64
            )
        })

    except RuntimeError as error:

        return jsonify({
            "error": str(error)
        }), 503

    except Exception as error:

        print(
            f"Image generation error: {error}"
        )

        return jsonify({
            "error": (
                "Image generation service "
                "is currently unavailable."
            )
        }), 503


@design_bp.route(
    "/design/upload_reference",
    methods=["POST"]
)
@login_required
def upload_reference_image():
    """Accept a user-uploaded reference image and retain it as-is.

    This is a separate path from /generate_image: the uploaded file is
    never sent to Gemini or FLUX, it just becomes a reference image the
    same way a generated image does (both will feed the same
    downstream reference_image abstraction in a later phase). Only a
    static URL is ever returned - never a filesystem path."""

    reference_file = request.files.get("reference_image")

    try:
        media_service.validate_reference_image(reference_file)

    except MediaValidationError as error:

        return jsonify({
            "error": str(error)
        }), 400

    try:

        saved_filename = media_service.save_reference_image(
            reference_file,
            current_app.static_folder
        )

    except OSError:

        return jsonify({
            "error": "Reference image could not be saved. Please try again."
        }), 503

    return jsonify({
        "reference_image_url": url_for(
            "static",
            filename=f"{media_service.DESIGN_REFERENCE_DIRECTORY}/{saved_filename}"
        )
    })


def _load_reference_image_from_request(reference_image_url):
    """Resolves the frontend's `reference_image_url` (either a
    data:image/... URI for a generated image, or a /static/... URL for
    an uploaded one - see static/design_reference_state.js) into a PIL
    Image, RGB. No network fetch - both cases are already local to
    this server. Raises ValueError with a user-safe message for
    anything invalid or unsafe.

    Path-traversal guard: this string arrives in a POST body and
    cannot be trusted to have actually come from this app's own
    upload/generate flow just because it LOOKS like one of our own
    static URLs - the resolved filesystem path is always verified to
    stay inside the static folder before anything is opened."""

    from PIL import Image, UnidentifiedImageError

    if not reference_image_url or not isinstance(reference_image_url, str):
        raise ValueError("No reference image provided.")

    if reference_image_url.startswith("data:image"):
        try:
            _header, encoded = reference_image_url.split(",", 1)
            image_bytes = base64.b64decode(encoded)
            return Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except (ValueError, UnidentifiedImageError, OSError) as exc:
            raise ValueError("Reference image data could not be decoded.") from exc

    static_url_path = current_app.static_url_path or "/static"
    prefix = static_url_path.rstrip("/") + "/"
    if not reference_image_url.startswith(prefix):
        raise ValueError("Reference image location is not recognized.")

    relative_path = reference_image_url[len(prefix):]
    static_folder = os.path.abspath(current_app.static_folder)
    resolved_path = os.path.abspath(os.path.join(static_folder, relative_path))

    if os.path.commonpath([static_folder, resolved_path]) != static_folder:
        raise ValueError("Reference image location is not recognized.")

    if not os.path.isfile(resolved_path):
        raise ValueError("Reference image could not be found.")

    try:
        return Image.open(resolved_path).convert("RGB")
    except (UnidentifiedImageError, OSError) as exc:
        raise ValueError("Reference image could not be read.") from exc


def _enrich_similarity_results(raw_results, property_service):
    """Turns the retrieval layer's minimal, unchanged result contract
    ({"property_id", "score", "best_image"} - see
    services/image_similarity/retrieval.py, NOT modified by this) into
    user-facing property-card data.

    MongoDB (via the existing PropertyService) stays the single source
    of truth for property details - the similarity index is NEVER
    extended to carry this data itself (see
    services/image_similarity/production_indexer.py's docstring: "Do
    not duplicate the entire MongoDB property document into the
    similarity index"). Reuses routes/search_routes.py's EXISTING
    _serialize_property() - the same flattening already used for
    ordinary property-search results (templates/rentals.html) - rather
    than writing a second, parallel property-summary implementation.

    A property that no longer exists (deleted since it was indexed) or
    is not currently active (unlisted via routes/property_routes.py's
    delete_listing()) is silently dropped from the results - stale
    index data self-healing, not an error, and consistent with how
    routes/search_routes.py/search_orchestration.py's ordinary search
    already excludes non-"active" listings. The embedding itself is
    intentionally left in the production cache untouched (not deleted)
    - status is re-checked on every request, so a relisted property
    becomes eligible again immediately, with no re-embedding needed.
    Similarity ORDER and SCORES of the remaining results are untouched
    (no re-ranking here - that stays retrieval.py's job). A property
    whose best-matching image filename is no longer present still gets
    a card, with image_url left None - the frontend renders its
    existing "no image" placeholder instead of a broken <img>."""

    from routes.search_routes import _serialize_property

    enriched = []

    for result in raw_results:

        property_id = result["property_id"]
        property_document = property_service.get_property(property_id)

        if property_document is None:
            continue

        if (property_document.get("listing") or {}).get("status") != "active":
            continue

        summary = _serialize_property(property_document)

        best_image = result.get("best_image") or ""
        prefix = f"{property_id}/"
        filename = best_image[len(prefix):] if best_image.startswith(prefix) else None

        image_url = None
        current_images = (property_document.get("media") or {}).get("images") or []
        if filename and filename in current_images:
            image_url = url_for("static", filename=f"{media_service.IMAGE_DIRECTORY}/{filename}")

        building = property_document.get("building") or {}

        enriched.append({
            "property_id": property_id,
            "score": result["score"],
            "best_image": result.get("best_image"),
            "image_url": image_url,
            "detail_url": url_for("property.property_details", property_id=property_id),
            "property_type": summary.get("property_type"),
            "listing_type": summary.get("listing_type"),
            "price": summary.get("price"),
            "bhk": summary.get("bhk"),
            "area": summary.get("area"),
            "city": summary.get("city"),
            "locality": summary.get("locality"),
            "furnishing": building.get("furnishing"),
        })

    return enriched


def _candidate_property_ids_from_query(query):
    """Runs the EXISTING NLP + MongoDB hard-filtering pipeline
    (services/search_orchestration.py's orchestrate_search() -
    completely unmodified, the same function routes/search_routes.py's
    /search_rentals uses for text-only search) and returns
    (candidate_property_ids, orchestration_result).

    This is Version A's "StructuredQuery -> MongoDB hard filtering ->
    candidate property IDs" stage. Hard requirements (listing type,
    property type, BHK, furnishing, price, area, amenities, location,
    nearby-facility constraints) are never turned into similarity
    weights - a property that fails any of them is simply never a
    candidate, so visual similarity can never let it outrank a
    property that actually satisfies the user's stated requirements.
    orchestrate_search() already restricts to "listing.status": "active"
    (see build_mongo_filter()), so an unlisted property can never be a
    text+image candidate either - no separate status check is needed
    for this path (Step 9)."""

    from services import search_orchestration

    osm_service = current_app.extensions.get("osm_location_service")
    mappls_key = current_app.config.get("MAPPLS_API_KEY")
    ola_key = current_app.config.get("OLA_MAPS_API_KEY")
    poi_radius_km = current_app.config.get(
        "SEARCH_POI_RADIUS_KM", search_orchestration.DEFAULT_POI_RADIUS_KM
    )

    # No separate structured-filter UI on the Design page (Step 11) -
    # every hard requirement comes from the free-text query itself,
    # exactly like /search_rentals's own "query, no structured
    # overrides" case.
    overrides = {
        "listing_type": "", "property_type": "", "bhk": None,
        "budget": 0, "city": "", "locality": "",
    }

    orchestration_result = search_orchestration.orchestrate_search(
        query, overrides, mappls_key, osm_service, current_app.extensions["property_service"],
        poi_radius_km=poi_radius_km, ola_api_key=ola_key,
    )

    candidate_ids = [str(p["_id"]) for p in orchestration_result["properties"]]
    return candidate_ids, orchestration_result


@design_bp.route(
    "/design/find_similar",
    methods=["POST"]
)
@login_required
def find_similar():
    """Reference image (generated OR uploaded) -> SigLIP2 embedding ->
    similarity search against the PRODUCTION embedding index only
    (source="mongodb_production" - see
    services/image_similarity/production_indexer.py, populated in the
    background as real properties are registered with images via
    routes/property_routes.py's submit_listing()) -> ranked property
    IDs enriched into real property-card data (_enrich_similarity_results()
    above) for the frontend.

    COMBINED NLP + IMAGE SEARCH (Version A - candidate-first, no
    arbitrary weights): an OPTIONAL "query" field in the request body
    adds a hard-filtering stage BEFORE similarity ranking -
    _candidate_property_ids_from_query() reuses the existing NLP ->
    MongoDB pipeline unchanged to produce the candidate set, then
    EmbeddingCache.filter_by_property_ids() restricts the SAME
    production embedding cache to just those candidates before the
    UNCHANGED search_similar_properties() ranking runs - so SigLIP2
    only ever scores properties that already satisfy the user's
    explicit hard requirements; visual similarity can never let a
    disqualified property outrank a qualifying one. When "query" is
    absent/empty, this is 100% the original image-only behavior - no
    new code path is exercised at all, and SigLIP2 is never skipped
    for existing callers.

    The MongoDB SMOKE-TEST index (source="mongodb_smoke_test",
    services/image_similarity/mongo_smoke_index.py) is a completely
    SEPARATE cache file and is never read by this route - it remains
    available as a standalone manual pipeline-verification tool, but
    is no longer wired into "Find Similar Homes". Even so, the loaded
    cache is defensively filtered to source="mongodb_production" only
    (EmbeddingCache.filter_by_source()) so a smoke-test record could
    never leak into a real result even if the two caches were ever
    accidentally pointed at the same file.

    services.image_similarity is imported lazily (inside this
    function, not at module load time) so torch/transformers are only
    ever loaded into the Flask process the first time this specific
    endpoint is actually called - never at app startup, and never on
    any other request path."""

    data = request.get_json(silent=True) or {}
    reference_image_url = data.get("reference_image_url")
    query = (data.get("query") or "").strip()[:500]

    try:
        reference_image = _load_reference_image_from_request(reference_image_url)
    except ValueError as error:
        return jsonify({"success": False, "error": str(error)}), 400

    from services.image_similarity.production_indexer import (
        PRODUCTION_NPZ_PATH,
        PRODUCTION_META_PATH,
        PRODUCTION_SOURCE,
    )

    if not (os.path.isfile(PRODUCTION_NPZ_PATH) and os.path.isfile(PRODUCTION_META_PATH)):
        return jsonify({
            "success": False,
            "error": "Similarity index is not ready yet. Register at least one property with images.",
        }), 503

    # ========================================================
    # OPTIONAL HARD-FILTERING STAGE (Version A) - runs BEFORE any
    # SigLIP2 model load/encode, so a query that matches zero
    # properties never pays for model loading at all (Step 13), and
    # never falls back to ranking unrelated properties (Step 12.A).
    # ========================================================

    candidate_ids = None
    applied_filters = None
    location_resolution = None
    candidate_count = None

    if query:
        try:
            candidate_ids, orchestration_result = _candidate_property_ids_from_query(query)
        except Exception as error:
            print(f"Combined search candidate filtering error: {error}")
            return jsonify({
                "success": False,
                "error": "Search is currently unavailable.",
            }), 503

        applied_filters = orchestration_result["applied_filters"]
        location_resolution = orchestration_result["location_resolution"]
        candidate_count = len(candidate_ids)

        if candidate_count == 0:
            # Step 12.A: zero NLP candidates - never run SigLIP2 against
            # unrelated properties as a fallback.
            return jsonify({
                "success": True,
                "source": PRODUCTION_SOURCE,
                "results": [],
                "query_used": query,
                "candidate_count": 0,
                "applied_filters": applied_filters,
                "location_resolution": location_resolution,
                "message": "No properties matched your search requirements.",
            })

    try:
        from services.image_similarity.embedding_cache import EmbeddingCache
        from services.image_similarity.retrieval import search_similar_properties
        from services.image_similarity.siglip2_encoder import get_default_encoder, InvalidImageError

        cache = EmbeddingCache.load(PRODUCTION_NPZ_PATH, PRODUCTION_META_PATH)
        cache = cache.filter_by_source(PRODUCTION_SOURCE)

        if candidate_ids is not None:
            # Candidate-restricted ranking (Step 3): the similarity
            # matrix multiply inside search_similar_properties() below
            # only ever runs over these rows - candidates are produced
            # FIRST, never filtered out after an unrestricted rank.
            cache = cache.filter_by_property_ids(candidate_ids)

        encoder = get_default_encoder()
        results = search_similar_properties(reference_image, cache, top_k=10, encoder=encoder)

    except InvalidImageError:
        return jsonify({"success": False, "error": "Reference image could not be processed."}), 400

    except Exception as error:

        print(f"Similarity search error: {error}")

        return jsonify({
            "success": False,
            "error": "Similarity search is currently unavailable.",
        }), 503

    property_service = current_app.extensions["property_service"]
    enriched_results = _enrich_similarity_results(results, property_service)

    message = None
    if candidate_count is not None and candidate_count > 0 and not enriched_results:
        # Step 12.B: candidates exist but none have usable similarity
        # images yet (e.g. registered without photos, or embedding
        # still queued in the background).
        message = (
            f"{candidate_count} propert{'y' if candidate_count == 1 else 'ies'} matched your "
            "search requirements, but none currently have indexed photos for similarity ranking."
        )

    return jsonify({
        "success": True,
        "source": PRODUCTION_SOURCE,
        "results": enriched_results,
        "query_used": query or None,
        "candidate_count": candidate_count,
        "applied_filters": applied_filters,
        "location_resolution": location_resolution,
        "message": message,
    })