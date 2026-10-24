<!-- Prompt optimizer for the FLUX.2 [klein] 4B image-generation flow -->
# Image Prompt Optimizer

**Status: implemented and live-verified once.** This adds a text-only prompt-rewriting step in front of the existing Cloudflare FLUX.2 [klein] 4B image generation - it never generates an image itself, and image generation still works with zero changes if this step is entirely unavailable.

## Why the optimizer exists

Users type natural, conversational descriptions - "20 people come to my house for tuition, I'm middle class, budget is low" - not image-generation prompt syntax. Sent directly to FLUX, a description like that risks being rendered literally (e.g. as a classroom, because "20 people" and "tuition" are salient words), rather than as what the user actually means: an ordinary home with an unusually spacious, well-ventilated hall. The optimizer's job is to bridge that gap - understanding **intent**, not rewriting words - before the prompt ever reaches the image model.

## Architecture

```
Frontend (templates/design.html, unchanged)
        |
routes/design_routes.py  POST /generate_image  (unchanged)
        |
services/image_service.py: ImageGenerationService.generate(prompt)
        |
        |-- 1. services/image_prompt_optimizer.py: optimize_prompt(prompt, ...)
        |        -> Cloudflare Workers AI, @cf/meta/llama-3.2-1b-instruct
        |        -> {"optimized_prompt": ..., "detected_requirements": [...],
        |            "avoid_misinterpretations": [...], "source": "llm"|"fallback"}
        |
        `-- 2. _call_cloudflare(optimized_prompt, ...)
                 -> Cloudflare Workers AI, @cf/black-forest-labs/flux-2-klein-4b
                 -> PIL.Image.Image
```

`ImageGenerationService.generate(prompt)` keeps its existing public interface (`-> PIL.Image.Image`, raises `RuntimeError` only for an actual FLUX-level failure) - `routes/design_routes.py` and `templates/design.html` are **unchanged**. The optimizer step is entirely internal to `image_service.py`; swapping the optimizer model, or removing it, only requires editing `services/image_prompt_optimizer.py` and the one call site in `image_service.py`.

`ImageGenerationService.last_optimizer_result` stores the most recent optimizer output (for tests and for a possible future "View optimized prompt" UI control) - it is not part of the current route/frontend contract.

## Chosen optimizer model

**Cloudflare Workers AI, `@cf/meta/llama-3.2-1b-instruct`** - deliberately a small, fast instruction-following model. It is used **only** to rewrite the prompt text; it never answers the user, and its output is never shown to the user or returned by any route.

- **Endpoint:** `POST https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/meta/llama-3.2-1b-instruct`
- **Request:** JSON (not multipart - this is a chat/text model, unlike the FLUX image model): `{"messages": [{"role": "system", "content": "<see below>"}, {"role": "user", "content": "<raw user prompt>"}], "max_tokens": 512, "temperature": 0.4}`
- **Response:** Cloudflare's standard envelope, `{"success": true, "result": {"response": "<generated text>"}, ...}` (confirmed against Cloudflare's own docs for this model's output schema).
- **Timeout:** 15s (much shorter than FLUX's 60s - this model is small and fast, and a stuck optimizer call should not meaningfully delay image generation).

## Optimization rules (system prompt)

The full system prompt lives in `services/image_prompt_optimizer.py`'s `SYSTEM_PROMPT` constant. It instructs the model to:

1. **Preserve every explicit requirement** (room counts, named features, materials, style words) - never remove something the user asked for.
2. **Interpret context as design requirements, not new subjects.** "20 people come for tuition" → a spacious hall sized for ~20 people, never a classroom/school; "family has six members" → a practical six-person house, never six people posing in the image.
3. **Establish a realistic Indian residential baseline** for generic requests, but let the user's own explicit style (e.g. "modern luxury villa") always take priority over that baseline.
4. **Respect stated economic level visually, never as a price** - "low budget"/"middle class" → affordable, practical, modest, simple finishes; never a cost estimate.
5. **Never invent major features** (pool, garden, balcony, luxury furniture, marble, smart-home systems, extra floors) unless the user asked for them or a luxury style was explicitly requested.
6. **Weave avoidances directly into the prompt text itself** - not just into the separate `avoid_misinterpretations` list - since only `optimized_prompt` is ever sent to FLUX (see "Known limitations" below for why this instruction was strengthened after the live test).
7. **Keep the requested property as the primary subject** - no added people unless explicitly requested.
8. **Target roughly 80-180 words**, restrained realism language only (`photorealistic`, `natural daylight`, `realistic materials`, `realistic proportions`, `authentic residential setting`).
9. **Respond with ONLY a single JSON object** in the shape `{"optimized_prompt": "...", "detected_requirements": [...], "avoid_misinterpretations": [...]}` - no prose, no markdown fences.

## Robust parsing (the model does not have native JSON mode)

`llama-3.2-1b-instruct` is not guaranteed to honor "JSON only" perfectly, so `_extract_json_object()` tries, in order: the raw text as-is, a `` ```json ... ``` `` fenced block, and the widest `{...}` span in the text - the first one that parses as a JSON object wins. If `optimized_prompt` is missing, not a string, or empty after all of that, **the result is discarded entirely and the deterministic fallback is used instead** - a malformed LLM response is never sent to FLUX.

## Fallback behavior (image generation never depends on the optimizer)

`optimize_prompt()` **never raises** and **always** returns a usable `optimized_prompt`. Every one of these falls through to `_deterministic_fallback()` - a small, non-LLM transformation that wraps the user's own text unchanged in restrained, non-inventive realism framing (`"Photorealistic architectural photograph of <user's exact text>. Realistic proportions, realistic materials, natural daylight, authentic residential setting."`) - never adding a feature the user didn't ask for:

- missing `CLOUDFLARE_ACCOUNT_ID` / `CLOUDFLARE_API_TOKEN`
- request timeout or network failure
- Cloudflare `401`/`403`/`429`/other `4xx`/`5xx`
- a `success: false` Cloudflare envelope (including Neuron/quota exhaustion)
- unparseable or structurally invalid LLM output (see above)
- an empty user prompt

`ImageGenerationService.generate()` calls `optimize_prompt()` unconditionally and passes whatever it returns (LLM-produced or fallback) straight to the existing FLUX call - there is no code path where a broken optimizer prevents an image from being generated.

## Examples

**Input:** `"2 bedroom house with a large kitchen"`
**Fallback output** (illustrates literal preservation): `"Photorealistic architectural photograph of 2 bedroom house with a large kitchen. Realistic proportions, realistic materials, natural daylight, authentic residential setting."` - both explicit requirements intact, nothing invented.

**Input (live-tested, see below):** `"I want a house the hall should be more spacious and ventilated, space should be more, nearly 20 people comes to my house for tuition, I am a middle class person, no need to be luxurious, my budget is low, so give me accordingly"`
**Live LLM output** (before the system-prompt strengthening described below): `"A spacious, ventilated house with a large hall for nearly 20 people to attend tuition classes, suitable for a middle-class household on a low budget."` (25 words) with `detected_requirements: ["large hall", "spacious", "ventilated", "suitable for 20 people", "middle-class", "low budget"]` and `avoid_misinterpretations: ["luxurious", "modern", "high-end"]`.

## Testing strategy

`test_image_prompt_optimizer.py` (29 tests) and additions to `test_image_service.py` (2 tests) - **no live LLM/API calls in any test**, matching this project's existing mocking convention (`unittest.mock`, mirroring `test_mappls_service.py`). Two layers are tested:

1. **The deterministic fallback**, against every scenario in this feature's own test list (basic house, spacious hall, ventilation, the tuition example, luxury villa, low-budget house, people-as-context, multiple requirements) - this is the layer whose intent-preservation behavior can be guaranteed unconditionally without a live, nondeterministic model call, and it is also literally what runs whenever the LLM is unavailable.
2. **`optimize_prompt()`'s parsing/validation**, given mocked Cloudflare responses standing in for what a well-behaved model would return - JSON-in-prose, JSON-in-markdown-fences, missing fields, empty `optimized_prompt`, HTTP failures, timeouts, and quota errors all correctly fall back rather than being passed to FLUX.
3. **`ImageGenerationService.generate()` integration** - confirms the FLUX call receives the *optimized* prompt (not the raw one), and that image generation still succeeds end-to-end when the optimizer's own HTTP call fails or returns garbage.

## Live verification (performed once)

Ran the tuition example above through the real pipeline (`ImageGenerationService.generate()`, both the optimizer and FLUX calls live). Result:

- Optimizer call succeeded (`source: "llm"`), correctly identified the house as residential, preserved "spacious", "ventilated", "large hall", "20 people", "middle-class", "low budget", and correctly avoided literally saying "classroom"/"school"/"institutional" anywhere in its output.
- FLUX generated a real 1024x1024 image from that prompt.
- **However**, the rendered image still resembled an institutional dining hall/classroom (rows of identical tables and chairs) - a genuine, disclosed limitation: the 1B model's optimized prompt, while textually correct, was only 25 words (well under the 80-180 target) and did not explicitly restate "this is a private residential home, not a classroom" *within* `optimized_prompt` itself - it only appeared in the separate `avoid_misinterpretations` list, which is never sent to FLUX.
- **In response**, the system prompt was strengthened (see rule 6 above: explicitly requiring every avoidance to be woven into `optimized_prompt`'s own wording, and requiring a full 80-180 word paragraph rather than a short summary) - this is a direct, evidence-based refinement, not blind prompt tuning.
- **A second live call was deliberately not made** after this change, to respect the "do not repeatedly generate images" constraint on Cloudflare's metered Workers AI allocation. **Recommendation: run one more live check of the tuition example when convenient**, to confirm the strengthened instructions produce a longer, more explicitly residential-framed prompt and a correspondingly more house-like (not classroom-like) image.

## Known limitations

- **`@cf/meta/llama-3.2-1b-instruct` is a genuinely small model** and does not always hit the requested 80-180 word target or fully internalize every instruction (see the live test above) - it is far more capable of avoiding literally forbidden words than of proactively reinforcing positive framing without being told to very explicitly, which is why rule 6 was strengthened.
- **No native JSON mode**: robustness here depends on this module's own multi-strategy parsing (`_extract_json_object`), not a guarantee from Cloudflare/the model itself. A future model swap to one with native structured output could simplify this.
- **The optimized prompt is currently invisible to the user** - by design, per this task's own scope ("acceptable to keep the optimized prompt invisible to the user" for the initial version). `ImageGenerationService.last_optimizer_result` is available for a future "View optimized prompt" UI control without any architecture change.
- **Image-model behavior is ultimately FLUX's**, not this optimizer's - even a well-worded, correctly-intent-preserving prompt can still be rendered in an unexpected way by the downstream image model, as the live test showed.
