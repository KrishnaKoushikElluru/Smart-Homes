/* ================================================================
   Voice search adapter (Phase 5.5).

   A SMALL, ISOLATED wrapper around the browser's native Web Speech
   API (SpeechRecognition / webkitSpeechRecognition) - no API key, no
   backend speech service, no ML model, no external speech API. This
   file is the ONLY place that ever touches SpeechRecognition; the
   rest of the app (templates/rentals.html's existing NL search code)
   only ever sees plain transcript TEXT handed back through the
   callbacks below, exactly as if the user had typed it.

   This isolation is deliberate: the browser engine here could later
   be swapped for a different speech backend (Vosk, Whisper, another
   engine) by rewriting ONLY this file's internals, as long as the
   same createController(options)/isSupported() public shape is kept -
   services/nlp/parser.py, StructuredQuery, search orchestration,
   MongoDB filtering, and location resolution never need to change,
   since they only ever receive ordinary text via the EXISTING
   #nlpQuery input + searchNaturalLanguage()/performNlpSearch() flow
   already in templates/rentals.html.

   Runnable standalone under Node (no browser, no bundler) for
   test_voice_search.js via the CommonJS export guard at the bottom -
   this project has no JS test framework, so tests use Node's built-in
   node:test runner directly against this file.
   ================================================================ */

(function (root) {
    "use strict";

    function getSpeechRecognitionCtor() {
        return root.SpeechRecognition || root.webkitSpeechRecognition || null;
    }

    function isSupported() {
        return typeof getSpeechRecognitionCtor() === "function";
    }

    // Never expose a raw browser exception/error code to the user (see
    // this project's task instructions) - every SpeechRecognition
    // "error" event code is mapped to a short, friendly sentence here,
    // and nowhere else.
    var ERROR_MESSAGES = {
        "no-speech": "Couldn't hear that. Please try again.",
        "audio-capture": "No microphone was found. Please check your device.",
        "not-allowed": "Microphone access was blocked. Please allow microphone access and try again.",
        "service-not-allowed": "Microphone access was blocked. Please allow microphone access and try again.",
        "network": "Voice search needs an internet connection. Please try again.",
        "bad-grammar": "Voice search couldn't process that. Please try again or type your search.",
        "language-not-supported": "Voice search isn't available in this language yet. Please type your search."
    };

    var DEFAULT_ERROR_MESSAGE =
        "Voice search couldn't process that. Please try again or type your search.";

    function friendlyErrorMessage(code) {
        return ERROR_MESSAGES[code] || DEFAULT_ERROR_MESSAGE;
    }

    /* ============================================================
       createController(options)

       options:
         lang              (default "en-IN" - see this phase's report
                            for why: target users/queries are primarily
                            Indian English; no language picker yet)
         interimResults     (default true)
         continuous          (default false - one utterance per click,
                            never continuously recording)
         onStart()           - listening began
         onInterimResult(t)  - a non-final transcript update (display
                              only; never treated as the final query)
         onFinalResult(t)    - a final transcript segment
         onEnd()             - recognition session ended (any reason)
         onError(message, code) - message is ALREADY the friendly
                              string above; code is the raw
                              SpeechRecognition error for callers that
                              want it (e.g. logging), never shown as-is

       Returns null if the browser has no SpeechRecognition
       implementation at all (caller must feature-detect via
       isSupported() and hide/disable the mic button instead of
       calling this) - or a controller object:

         { start(), stop(), abort(), isListening() }

       ONE controller owns exactly ONE underlying SpeechRecognition
       instance and binds its handlers exactly once at creation time -
       calling start()/stop() repeatedly never re-attaches listeners,
       so a caller that (incorrectly) re-initializes the UI without
       reusing the same controller is the only way to get duplicate
       instances; the normal one-controller-per-page usage in
       templates/rentals.html cannot produce duplicate handlers or a
       memory leak.
       ============================================================ */

    function createController(options) {
        options = options || {};

        var Ctor = getSpeechRecognitionCtor();

        if (!Ctor) {
            return null;
        }

        var recognition = new Ctor();
        recognition.lang = options.lang || "en-IN";
        recognition.interimResults = options.interimResults !== false;
        recognition.continuous = options.continuous === true;
        recognition.maxAlternatives = 1;

        var listening = false;

        recognition.onstart = function () {
            listening = true;
            if (typeof options.onStart === "function") {
                options.onStart();
            }
        };

        recognition.onresult = function (event) {
            var finalTranscript = "";
            var interimTranscript = "";

            // event.resultIndex marks where THIS event's new results
            // start - browsers still resend earlier, already-final
            // results before it on some updates, so starting from
            // resultIndex (not 0) avoids re-emitting old text.
            var startIndex = typeof event.resultIndex === "number" ? event.resultIndex : 0;

            for (var i = startIndex; i < event.results.length; i++) {

                var result = event.results[i];
                var transcript = (result && result[0] && result[0].transcript) || "";

                if (result && result.isFinal) {
                    finalTranscript += transcript;
                } else {
                    interimTranscript += transcript;
                }
            }

            if (finalTranscript) {
                if (typeof options.onFinalResult === "function") {
                    options.onFinalResult(finalTranscript.trim());
                }
            } else if (interimTranscript) {
                if (typeof options.onInterimResult === "function") {
                    options.onInterimResult(interimTranscript.trim());
                }
            }
        };

        recognition.onerror = function (event) {
            listening = false;

            var code = event && event.error;

            // "aborted" fires from our OWN stop()/abort() calls (or the
            // user closing the permission prompt) - not a real failure
            // worth surfacing to the user.
            if (code === "aborted") {
                return;
            }

            if (typeof options.onError === "function") {
                options.onError(friendlyErrorMessage(code), code);
            }
        };

        recognition.onend = function () {
            listening = false;
            if (typeof options.onEnd === "function") {
                options.onEnd();
            }
        };

        return {
            start: function () {
                if (listening) {
                    return;
                }
                try {
                    recognition.start();
                } catch (err) {
                    // Some browsers throw synchronously if start() is
                    // called again before the previous session's onend
                    // has fired (e.g. a fast double click) - treat as a
                    // harmless no-op rather than an uncaught exception.
                }
            },
            stop: function () {
                if (!listening) {
                    return;
                }
                recognition.stop();
            },
            abort: function () {
                listening = false;
                recognition.abort();
            },
            isListening: function () {
                return listening;
            }
        };
    }

    var VoiceSearch = {
        isSupported: isSupported,
        createController: createController,
        // Exported for tests only - not part of the UI-facing contract.
        _friendlyErrorMessage: friendlyErrorMessage
    };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = VoiceSearch;
    } else {
        root.VoiceSearch = VoiceSearch;
    }

})(typeof window !== "undefined" ? window : globalThis);
