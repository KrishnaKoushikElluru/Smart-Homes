"""
Image-generation service - Cloudflare Workers AI backend.

Provider: Cloudflare Workers AI, model @cf/black-forest-labs/flux-2-klein-4b
(FLUX.2 [klein] 4B), text-to-image only. See docs/IMAGE_GENERATION_CLOUDFLARE.md
for the full request/response contract and setup notes.

Architecture (see that doc for the diagram too):
    routes/design_routes.py -> ImageGenerationService.generate(prompt)
        -> image_prompt_optimizer.optimize_prompt() -> Gemini 3.5 Flash-Lite
              (semantic understanding only - extracts structured
              requirements; a deterministic Python builder, not Gemini's
              own free-form wording, constructs the FLUX-facing prompt.
              Never generates an image, never blocks generation if it
              fails - see services/image_prompt_optimizer.py)
        -> _call_cloudflare(optimized_prompt) -> Cloudflare Workers AI
              -> FLUX.2 [klein] 4B (UNCHANGED - this is still the sole
              image-generation provider)

ImageGenerationService.generate(prompt) keeps the EXACT SAME public
interface the previous Hugging Face-backed version had (returns a
PIL.Image.Image, raises RuntimeError with a clean message on any
failure) - routes/design_routes.py and templates/design.html are
UNCHANGED by this swap. Replacing the provider again later should only
require editing this file.

_call_cloudflare() itself never raises (matching services/mappls_service.py
and services/ola_maps_service.py's convention: a uniform result dict,
not exceptions, for every expected failure) - generate() is the one
place that translates that dict into the raise-based interface routes/
design_routes.py already expects.

Logging discipline (never violated below): the API token is only ever
placed in the Authorization header, never logged. The generated image's
base64/bytes are never logged. On a malformed Cloudflare response, only
the response's dict KEYS are logged (not values), so a malformed-but-
still-image-bearing payload is never dumped into logs.
"""

import base64
import io
import logging
import os

import requests
from PIL import Image

from services import image_prompt_optimizer


logger = logging.getLogger(__name__)

CLOUDFLARE_RUN_URL_TEMPLATE = (
    "https://api.cloudflare.com/client/v4/accounts/{account_id}"
    "/ai/run/@cf/black-forest-labs/flux-2-klein-4b"
)

# Image generation is far slower than the geocoding-style lookups the
# rest of this project's services make (Mappls/Ola use 8s) - a FLUX
# diffusion run can legitimately take tens of seconds.
REQUEST_TIMEOUT_SECONDS = 60

DEFAULT_WIDTH = 1024
DEFAULT_HEIGHT = 1024


def _call_cloudflare(prompt, account_id, api_token, width=DEFAULT_WIDTH, height=DEFAULT_HEIGHT):
    """Never raises. Returns:
        {"status": "ok", "image_bytes": bytes, "error": None}
      or
        {"status": "error", "image_bytes": None, "error": "<clean message>"}
    """

    result = {"status": "error", "image_bytes": None, "error": None}

    if not account_id:
        result["error"] = "Image generation is not configured (missing Cloudflare account ID)."
        return result

    if not api_token:
        result["error"] = "Image generation is not configured (missing Cloudflare API token)."
        return result

    if not prompt or not prompt.strip():
        result["error"] = "Prompt cannot be empty."
        return result

    url = CLOUDFLARE_RUN_URL_TEMPLATE.format(account_id=account_id)
    headers = {"Authorization": f"Bearer {api_token}"}

    # This model requires multipart/form-data (per Cloudflare's own
    # flux-2-klein-4b docs), not JSON. The (None, value) tuple form
    # tells `requests` to encode each field as a plain multipart part
    # with no filename - `requests` builds the multipart body and sets
    # the Content-Type header (including the boundary) itself; nothing
    # here sets or computes a boundary manually.
    files = {
        "prompt": (None, prompt),
        "width": (None, str(width)),
        "height": (None, str(height)),
    }

    try:
        response = requests.post(url, headers=headers, files=files, timeout=REQUEST_TIMEOUT_SECONDS)

    except requests.Timeout:
        result["error"] = "Image generation request timed out. Please try again."
        return result

    except requests.RequestException:
        result["error"] = "Image generation request failed (network error)."
        return result

    if response.status_code in (401, 403):
        logger.error("Cloudflare Workers AI authentication failed (HTTP %s).", response.status_code)
        result["error"] = "Image generation is not authorized. Check the Cloudflare API credentials."
        return result

    if response.status_code == 429:
        logger.error("Cloudflare Workers AI rate-limited the request (HTTP 429).")
        result["error"] = "Image generation quota/usage limit reached. Please try again later."
        return result

    if 400 <= response.status_code < 500:
        logger.error("Cloudflare Workers AI rejected the request (HTTP %s).", response.status_code)
        result["error"] = f"Image generation request was rejected (HTTP {response.status_code})."
        return result

    if response.status_code >= 500:
        logger.error("Cloudflare Workers AI server error (HTTP %s).", response.status_code)
        result["error"] = "Image generation provider is temporarily unavailable. Please try again later."
        return result

    try:
        payload = response.json()

    except ValueError:
        result["error"] = "Image generation returned an unreadable response."
        return result

    if isinstance(payload, dict) and payload.get("success") is False:
        errors = payload.get("errors") or []
        messages = " ".join(
            str(e.get("message", "")) for e in errors if isinstance(e, dict)
        )
        logger.error("Cloudflare Workers AI reported failure: %s", messages or "(no message provided)")

        lowered = messages.lower()
        if "neuron" in lowered or "quota" in lowered or "limit" in lowered:
            result["error"] = "Image generation quota/usage limit reached for this account."
        else:
            result["error"] = "Image generation provider rejected the request."
        return result

    # Expected shape (Cloudflare's standard API envelope, confirmed
    # against the flux-2-klein-4b model docs' documented output field):
    #   {"success": true, "result": {"image": "<base64 string>"}, ...}
    # Handled defensively for an unwrapped {"image": "..."} shape too,
    # in case that ever changes, rather than assuming one exact layout.
    image_b64 = None
    if isinstance(payload, dict):
        result_obj = payload.get("result")
        if isinstance(result_obj, dict):
            image_b64 = result_obj.get("image")
        if image_b64 is None:
            image_b64 = payload.get("image")

    if not image_b64 or not isinstance(image_b64, str):
        response_keys = sorted(payload.keys()) if isinstance(payload, dict) else type(payload).__name__
        logger.error("Cloudflare Workers AI response had no usable 'image' field (top-level keys=%s).", response_keys)
        result["error"] = "Image generation returned no image."
        return result

    try:
        image_bytes = base64.b64decode(image_b64, validate=True)

    except (ValueError, TypeError):
        result["error"] = "Image generation returned an invalid image encoding."
        return result

    if not image_bytes:
        result["error"] = "Image generation returned an empty image."
        return result

    result["status"] = "ok"
    result["image_bytes"] = image_bytes
    return result


class ImageGenerationService:
    """Cloudflare Workers AI (FLUX.2 [klein] 4B) image-generation backend.

    Public interface preserved from the previous Hugging Face-backed
    version: generate(prompt) -> PIL.Image.Image, raising RuntimeError
    with a clean, non-sensitive message on any failure. Callers
    (routes/design_routes.py) require no changes."""

    def __init__(self):
        self.account_id = os.getenv("CLOUDFLARE_ACCOUNT_ID")
        self.api_token = os.getenv("CLOUDFLARE_API_TOKEN")
        self.gemini_api_key = os.getenv("GEMINI_API_KEY")
        # Set by generate() on every call - not part of the public
        # interface routes/design_routes.py relies on (that interface
        # is unchanged: generate(prompt) -> PIL.Image.Image), but kept
        # here so a future UI change ("View optimized prompt") or a
        # test can inspect the last optimizer result without changing
        # generate()'s return type today.
        self.last_optimizer_result = None

    def generate(self, prompt):
        optimizer_result = image_prompt_optimizer.optimize_prompt(
            prompt, self.gemini_api_key
        )
        self.last_optimizer_result = optimizer_result

        # The optimizer NEVER blocks generation - optimize_prompt() always
        # returns a usable optimized_prompt (falling back to a
        # deterministic, non-LLM transformation on any failure), so this
        # is a plain dict lookup, never a try/except.
        result = _call_cloudflare(optimizer_result["optimized_prompt"], self.account_id, self.api_token)

        if result["status"] != "ok":
            raise RuntimeError(result["error"])

        try:
            return Image.open(io.BytesIO(result["image_bytes"]))

        except Exception:
            raise RuntimeError("Image generation returned a file that could not be read as an image.")
