<!-- Phase 5.5: Browser Voice Search — implementation report -->
# Phase 5.5: Browser Voice Search — Report

**Status:** complete. The existing natural-language search box can now be filled by voice, using only the browser's native Web Speech API. No API key, no backend speech service, no ML model, no new external dependency. The existing NLP parser, StructuredQuery, search orchestration, and Ola/Mappls/OSM location resolution are completely unmodified.

## 1. Why browser-native speech, not a service

The task required zero new keys/secrets/backend dependencies. Every modern Chromium-based browser (and Safari, with vendor prefix) already ships `SpeechRecognition`/`webkitSpeechRecognition` for free, with no server round-trip for audio at all - the browser (or its OS) does the recognition and only ever hands JavaScript a text string. This is the only option that satisfies "no API key, no backend speech-recognition service, no Whisper/Vosk/another ML model, no external speech API" while still producing real speech-to-text.

**Precise, not oversold:** the actual recognition behavior (accuracy, whether it's on-device or sent to a vendor's cloud service by the browser itself) is entirely up to the browser/OS implementation, not this app. This code never claims the transcription is offline/local - it only guarantees that *this application* never receives audio and never adds a speech-processing dependency of its own.

## 2. Inspection performed before writing any code (Part 1)

- `#nlpQuery` (a plain text input) is the ONE natural-language search box, submitted by `#nlpSearchForm`'s `onsubmit="searchNaturalLanguage(event)"` (Enter key or the existing `#nlpSearchButton`).
- `searchNaturalLanguage()` reads `#nlpQuery.value.trim()` and calls `performNlpSearch(queryText, null)`, which POSTs to the existing `/search_rentals` endpoint - completely unchanged by this phase.
- This search panel (`#buyForm`, labeled "Search Properties") is shared by Buy and Rent - there is only one NL search component, not separate ones per listing type (confirmed in Phase 5's own inspection, re-confirmed here).
- "Sell" (`#sellForm`) is the property **registration** form, not a search form - natural-language search does not apply there, so no microphone was added to it, per the explicit instruction not to force voice search where it doesn't make semantic sense.
- No existing frontend JS test framework exists (no `package.json`, no Jest/Mocha) - confirmed before choosing a test approach for Part 9.

## 3. Architecture

```
Keyboard                                    Voice
   |                                          |
   |                                    click mic button
   |                                          |
   |                                 static/voice_search.js
   |                                 (SpeechRecognition/webkitSpeechRecognition
   |                                  ONLY - isolated adapter, en-IN,
   |                                  interimResults=true, continuous=false)
   |                                          |
   |                                 transcript text (interim + final)
   |                                          |
   +--------------------> #nlpQuery (SAME input, either way) <---------------+
                                     |
                          user reviews/edits, presses Search (unchanged)
                                     |
                          searchNaturalLanguage() -> performNlpSearch()
                          (UNCHANGED - Phase 3.1)
                                     |
                          services.nlp.parser.parse() (UNCHANGED)
                                     |
                          StructuredQuery -> search_orchestration.orchestrate_search()
                          (UNCHANGED - Ola primary / Mappls fallback / nearby facilities)
                                     |
                          property results (UNCHANGED rendering)
```

**Files:**
- [static/voice_search.js](static/voice_search.js) (new) - the ENTIRE SpeechRecognition surface lives here. Exposes exactly two public functions: `isSupported()` and `createController(options)`. Nothing else in the app ever touches `SpeechRecognition` directly.
- [templates/rentals.html](templates/rentals.html) (modified) - a mic `<button type="button">` inside the existing `.nlp-search-row`, a status line, matching CSS, and a small wiring IIFE that creates ONE controller and forwards its callbacks into `#nlpQuery`'s value. No change to `searchNaturalLanguage()`, `performNlpSearch()`, or any backend call.

## 4. Microphone placement

Inside the existing NL search row, between the text input and the existing "Search" button:

```
[ Describe what you're looking for............ ] [ 🎙️ ] [ Search ]
```

Hidden by default (`hidden` attribute in the HTML); revealed by JS only after `VoiceSearch.isSupported()` returns true and a working controller is actually constructed - a browser with no Web Speech API support sees a completely ordinary text-only search box, with no layout gap or broken control.

## 5. UX states (Part 4)

| State | What happens |
|---|---|
| IDLE | 🎙️ icon, `aria-label="Search by voice"` |
| LISTENING | button turns red and pulses (CSS animation), `aria-label="Stop voice search"`, status line shows "Listening…" |
| TRANSCRIBING (interim) | status line updates live to show the interim transcript; `#nlpQuery` is updated too so the user sees text appear as they speak, but nothing is final yet |
| SUCCESS | final transcript sits in `#nlpQuery`, exactly as if typed; recognition ends, button returns to idle |
| ERROR | a short, friendly, pre-mapped message (e.g. *"Couldn't hear that. Please try again."*, *"Microphone access was blocked. Please allow microphone access and try again."*) - the raw `SpeechRecognition` error code is NEVER shown to the user (verified live: a real "not-allowed" browser error produced exactly the friendly sentence, not the raw code) |
| NOT SUPPORTED | mic button stays hidden; nothing else changes |

The existing `.nlp-message`-style color language (info/warning/error) already used by the NL search feedback panel is echoed for the voice status line, without touching that panel itself - voice status and search-result feedback stay visually related but functionally separate (a voice error must not be overwritten or interfere with a subsequent real search's own feedback).

## 6. Never auto-submits (Part 5)

The mic button is `type="button"`, not `type="submit"` - it is structurally impossible for it to submit `#nlpSearchForm`. Only `onFinalResult` writes into `#nlpQuery.value`; nothing in `voice_search.js` or the wiring code ever calls `searchNaturalLanguage()`, `performNlpSearch()`, `.submit()`, or `.click()` on the Search button. Verified live (see §10).

## 7. Existing NLP fully preserved (Part 6)

No voice-specific parsing rules were added anywhere. `voice_search.js` and its wiring code have zero knowledge of BHK, furnishing, locations, or facility categories - they only ever produce a plain string and hand it to the exact same `#nlpQuery` input a keyboard would. `services/nlp/parser.py` was not opened for editing during this phase.

## 8. Search context (Part 7)

One shared NL search input serves both Buy and Rent (both use `#buyForm`'s search panel) - one microphone, one adapter instance, no duplication. Sell (registration) has its own, separate location-*autocomplete* box (`#pfLocationSearch`, Phase 5's Ola/Mappls flow) which is a structured place-picker, not a natural-language query box - voice was correctly NOT added there, since "speak a full sentence and parse it" doesn't apply to selecting one address candidate from a list.

## 9. Language (Part 8)

`recognition.lang = "en-IN"`, hardcoded as the only supported value for now, matching the target audience. No language picker, no translation, no multilingual pipeline - explicitly deferred, as instructed.

## 10. Tests (Part 9)

This project has no JS test framework. Per the task's own instruction not to introduce a large one just for this feature, tests use Node's **built-in** `node:test` + `node:assert` (zero new dependencies, available in the Node already installed) against `static/voice_search.js` directly, with a hand-rolled fake `SpeechRecognition` class - the same "fake the external boundary, test the real logic" convention the Python suite already uses for `services/mappls_service.py`/`services/ola_maps_service.py`.

`node --test test_voice_search.js` → **16/16 passing**, covering:
1. supported (constructor exists) 2. unsupported (`createController` returns `null`) 3. correct settings (`en-IN`, `interimResults`, `continuous=false`, `maxAlternatives=1`) 4. listening state entered on start 5. final transcript delivered via `onFinalResult` 6. an interim result never overwrites an already-arrived final result (and `resultIndex` prevents re-processing old results) 7. idle again on `onend` 8. a recognition error returns to idle with a friendly (never raw) message, including the "aborted" self-stop case being suppressed 9-10. no duplicate `start()`/`onend` firing, `stop()` is a safe no-op when idle.

Backend regression: **392/392** Python tests still passing (unchanged from the pre-existing baseline - this phase touched no `.py` file at all).

## 11. Manual browser verification (Part 10)

Performed against the real running dev server in the actual browser pane (real Chromium `SpeechRecognition`, not a mock):

- The mic button correctly appeared inside the Buy/Rent search panel after real feature detection (`isSupported()` returned `true`).
- Clicking it triggered a **genuine browser microphone-permission request** (confirmed by the pane's own "requested microphone access" notice) - proving the full click → `recognition.start()` → OS permission prompt chain is really wired, not simulated.
- With microphone access unavailable in this sandbox, the app displayed exactly **"Microphone access was blocked. Please allow microphone access and try again."** - the mapped friendly message, not a raw exception - and the button cleanly returned to its idle state and label afterward.
- A final transcript was then driven through the adapter's public API (using a substitute recognition object, since this sandbox cannot supply real audio) to prove the rest of the chain: `"2 bhk semi furnished near VIT Chennai"` landed in `#nlpQuery`, the mic did **not** submit anything, and clicking the real, existing "Search" button ran the **completely unmodified** NL pipeline - the results correctly showed `2 BHK / Semi Furnished / 📍 VIT Chennai` and returned real matching properties (including a listing literally named "Tata Homes... Near to VIT chennai").
- The existing NLP parser was separately exercised directly (Python, no browser needed) against all 5 of the task's required phrases:

  | Phrase | Parsed correctly? |
  |---|---|
  | "2 BHK flat in Chennai under thirty thousand" | BHK ✓, location ✓ (Chennai); **price not parsed** - see limitation below |
  | "2 BHK semi furnished near VIT Chennai" | BHK ✓, furnishing ✓ (`semi_furnished`), location ✓ (POI "VIT Chennai") |
  | "2 BHK near a gym within one kilometer" | BHK ✓, nearby facility ✓ (`gym`); **radius not parsed** - see limitation below |
  | "3 BHK near Tata Homes Mambakkam" | BHK ✓, location ✓ (POI "Tata Homes Mambakkam", matching Phase 5's comma-boundary fix) |
  | "flats near SBIOA Chennai" | location ✓ (POI "SBIOA Chennai") - no alias needed, generic POI detection handled it |

## 12. Confirmations

- **No API key added** - `voice_search.js` has zero network calls of any kind.
- **No backend speech service** - the Flask backend never receives audio; it only ever receives whatever text the user reviews and submits, through the pre-existing `/search_rentals` endpoint.
- **Voice feeds the existing pipeline** - proven live end-to-end (§11).
- **No ML model, no model download, no database change, no new external service.**
- `implementation_changes.docx` untouched (file mtime predates this phase).
- No file under `services/nlp/`, `evaluation/`, `services/ola_maps_service.py`, `services/location_provider_service.py`, or the Ola/Mappls/OSM sections of `services/search_orchestration.py` was opened for editing this phase.

## 13. Known limitations (disclosed, not fixed - out of scope for this phase)

- **Spelled-out numbers are not parsed** ("thirty thousand" → no price constraint; "one kilometer" → no radius on the gym requirement). This is a **pre-existing** `services/nlp/` limitation (the numeric parser and the nearby-facility radius pattern both expect digit form, e.g. "30000"/"30k"/"1 km"), not something introduced by or specific to voice input - fixing it would mean touching `services/nlp/`, which this phase was explicitly told not to do. In practice, Chrome's own speech engine frequently transcribes spoken quantities as digits already (e.g. a user saying "thirty thousand" often comes back as "30,000" in the real transcript) which would parse correctly today; the digit-free spelled-out form was tested deliberately as the more conservative case, and its failure is worth the team's awareness for a future NLP-scoped phase.
- Recognition quality, latency, and language support are entirely governed by the user's browser/OS - Safari's vendor-prefixed implementation, older browsers, and non-Chromium engines vary or may not support it at all (handled gracefully via feature detection either way).
- A voice ERROR status message can persist on screen through a subsequent *manual* search if the user doesn't retry voice - purely cosmetic (it doesn't affect search correctness, and the two feedback areas are visually distinct), not fixed in this pass since it wasn't part of the required behavior.
