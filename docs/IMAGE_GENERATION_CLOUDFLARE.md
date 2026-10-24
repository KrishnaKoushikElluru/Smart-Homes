<!-- Image generation provider swap: Hugging Face -> Cloudflare Workers AI -->
# Image Generation: Cloudflare Workers AI

**Status: provider replaced.** The existing `/design` page and `/generate_image` endpoint are unchanged - only the backend that actually generates the image was swapped, from Hugging Face's Inference API (`prompthero/openjourney`, unconfigured/non-functional in this environment - no `HF_API_KEY` was ever set) to **Cloudflare Workers AI**.

## Provider

- **Provider:** Cloudflare Workers AI
- **Model:** `@cf/black-forest-labs/flux-2-klein-4b` (FLUX.2 [klein] 4B - "an ultra-fast, distilled image model")
- **Endpoint:** `POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/black-forest-labs/flux-2-klein-4b`
- **Mode:** text-to-image only for this initial implementation. Reference-image editing (`input_image_0..3`) is a documented model capability but is **not implemented yet** - deliberately out of scope for this change.
- **Docs:** https://developers.cloudflare.com/workers-ai/models/flux-2-klein-4b/

## Architecture

```
Frontend (templates/design.html, unchanged)
        |
routes/design_routes.py  POST /generate_image  (unchanged)
        |
services/image_service.py: ImageGenerationService.generate(prompt)
        |                   -> PIL.Image.Image, or raises RuntimeError
        |
Cloudflare Workers AI  (multipart/form-data, Bearer token auth)
        |
FLUX.2 [klein] 4B
```

`ImageGenerationService.generate(prompt)` keeps the **exact same public interface** the previous Hugging Face-backed version had: it returns a `PIL.Image.Image` on success, or raises `RuntimeError` with a clean message on any failure. Because of that, `routes/design_routes.py` and `templates/design.html` needed **zero changes** - the route still does its own `image.save(buffered, format="PNG")` + base64-encode + `{"image_url": "data:image/png;base64,..."}` exactly as before. Swapping providers again in the future should only require editing `services/image_service.py`.

## Environment variables

```
CLOUDFLARE_ACCOUNT_ID=<your Cloudflare account ID>
CLOUDFLARE_API_TOKEN=<a Workers AI-scoped API token>
```

Read directly via `os.getenv(...)` inside `ImageGenerationService.__init__`, matching how the previous `HF_API_KEY` was read (this project's existing image-generation service has always read its own env vars directly, rather than through `config.py`'s `Config` class). Both keys are also declared on `Config` (`config.py`) purely for documentation parity with `HF_API_KEY` - nothing currently reads them from there, matching the existing (slightly redundant) precedent.

Set them in `secret.env` (already git-ignored via `.gitignore`'s `*.env`/`secret.env` patterns) - **never commit this file, never hard-code either value in source.**

## Request format

Cloudflare requires **`multipart/form-data`** for this model (not JSON). Sent via `requests.post(url, headers=..., files=...)`:

```python
files = {
    "prompt": (None, prompt),
    "width": (None, "1024"),
    "height": (None, "1024"),
}
requests.post(url, headers={"Authorization": f"Bearer {api_token}"}, files=files, timeout=60)
```

The `(None, value)` tuple form tells `requests` to encode each field as a plain multipart part with no filename. **The multipart boundary and `Content-Type` header are set entirely by `requests` itself** - nothing in this codebase sets or computes a boundary manually, per the model's own encoding requirement.

- `width` / `height`: hard-coded to **1024x1024** for this initial implementation (not exposed in the UI - the existing `/design` page has no size controls, and none were added).
- `seed` / `guidance`: not sent (optional per Cloudflare's schema; the existing UI has no controls for them, so none were added, per the same "don't change the existing workflow" constraint).
- `input_image_0..3`: not sent (reference-image editing is out of scope for this change).

## Response handling

Cloudflare's model docs confirm the output schema has exactly one documented field: `image` (string, "Generated image as Base64 string"). The full JSON envelope wasn't fully visible via automated doc fetching during this change (the live schema viewer is JS-rendered), so **`services/image_service.py` handles the response defensively rather than assuming one exact shape**:

1. Non-2xx status codes are handled explicitly and distinctly: `401`/`403` (auth), `429` (quota/rate limit), other `4xx` (validation), `5xx` (provider outage).
2. A successful (`2xx`) response is parsed as JSON; a non-JSON body is treated as a clean "unreadable response" error rather than crashing.
3. Cloudflare's standard API envelope (`{"success": false, "errors": [...]}`) is checked explicitly - if present, the error message text is inspected for "neuron"/"quota"/"limit" to distinguish a Workers AI usage-limit exhaustion from a generic rejection, without ever dumping the raw Cloudflare error payload into a user-facing message.
4. The `image` field is looked for at **both** `payload["result"]["image"]` (the documented shape) **and** a fallback bare `payload["image"]`, so an unexpected-but-plausible variation doesn't hard-fail.
5. The base64 string is decoded (`base64.b64decode(..., validate=True)`); an invalid encoding or an empty decoded result is a clean error, not a crash.
6. The decoded bytes are handed to `PIL.Image.open(...)`, which is what the existing route already expects to call `.save(..., format="PNG")` on.

Any failure at any of these steps raises `RuntimeError("<clean, non-sensitive message>")` - the existing route's `except RuntimeError` / `except Exception` handlers (already present, unchanged) turn that into the existing `{"error": "..."}` JSON response with a `503` status, exactly as before.

## Why 1024x1024

The existing `/design` UI has no size selector - it's a single prompt textarea and a "Generate" button. `1024` x `1024` was chosen as a reasonable default square size and hard-coded rather than exposed as a new control, per this change's explicit scope (don't change the existing workflow unless the API response format requires it - it doesn't).

## Error handling

| Condition | Result |
|---|---|
| `CLOUDFLARE_ACCOUNT_ID` missing | Clean `RuntimeError`, no network call made |
| `CLOUDFLARE_API_TOKEN` missing | Clean `RuntimeError`, no network call made |
| Cloudflare `401`/`403` | Clean "not authorized" `RuntimeError` |
| Cloudflare `429` | Clean "quota/usage limit reached" `RuntimeError` |
| Cloudflare other `4xx` | Clean "request was rejected (HTTP `<code>`)" `RuntimeError` |
| Cloudflare `5xx` | Clean "temporarily unavailable" `RuntimeError` |
| Request timeout / network failure | Clean `RuntimeError`, distinct messages for each |
| `success: false` envelope, Neuron/quota exhaustion detected in the message | Clean "quota/usage limit reached" `RuntimeError` |
| `success: false` envelope, other | Clean "provider rejected the request" `RuntimeError` |
| Missing/malformed `image` field | Clean "returned no image" `RuntimeError` |
| Invalid base64 / empty decoded image | Clean `RuntimeError` |
| Image bytes that PIL can't open | Clean `RuntimeError` |

None of these ever expose the API token, the account ID, or a raw Cloudflare error dump to the frontend - every path produces one short, safe sentence.

## Logging discipline

- The API token is placed **only** in the `Authorization` header; it is never logged, never included in any error message, and never returned in any response.
- The generated image (base64 or decoded bytes) is **never logged**.
- On a malformed/unexpected response, only the response's top-level dict **keys** are logged (e.g. `keys=['success', 'errors']`), never the values - so a response that happens to still contain image data is never dumped into logs.
- Cloudflare's own `errors[].message` text (validation/auth error descriptions - never the image, never the token) is logged at `logger.error` level for operator diagnosis.

## How to run / test locally

1. Set `CLOUDFLARE_ACCOUNT_ID` and `CLOUDFLARE_API_TOKEN` in `secret.env` (already done in this environment).
2. Unit tests (fully mocked, no network, no live credentials needed):
   ```
   python -m pytest -q test_image_service.py
   ```
3. Full existing suite (confirms no regression elsewhere):
   ```
   python -m pytest -q --ignore=osm_test --ignore=geo_coordinate_benchmark test_*.py
   ```
4. Manual/live check: log in, visit `/design`, enter a prompt, click Generate - the existing UI is unchanged, so this exercises the real end-to-end flow through the new provider.

## Cost / quota note

Workers AI usage is metered against the Cloudflare account's current free allocation and/or billing plan (Cloudflare's published rate for this model: **$0.000059 per input 512x512 tile, $0.000287 per output 512x512 tile**). A `429` or a `success: false` response mentioning Neuron/quota exhaustion means the account's current allocation has been used up for the relevant period - this is an account-level Cloudflare limit, not a bug in this integration, and is surfaced to the user as a clean "quota/usage limit reached" message rather than a raw error dump.
