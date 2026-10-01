/* ================================================================
   Unit tests for static/voice_search.js (Phase 5.5).

   Run with:
       node --test test_voice_search.js

   This project has no JS test framework (no package.json, no Jest/
   Mocha) - per the task's own instruction not to introduce a large
   framework just for this feature, these tests use Node's BUILT-IN
   node:test + node:assert (available since Node 18, zero new
   dependencies). A hand-rolled fake SpeechRecognition class stands in
   for the browser API, matching the mocking convention the Python
   test suite already uses for external services (services.mappls_
   service, services.ola_maps_service) - fake the boundary, test the
   real logic behind it.
   ================================================================ */

const test = require("node:test");
const assert = require("node:assert/strict");

/* ============================================================
   FAKE SpeechRecognition - a minimal, scriptable stand-in.
   ============================================================ */

class FakeSpeechRecognition {
    constructor() {
        this.lang = null;
        this.interimResults = null;
        this.continuous = null;
        this.maxAlternatives = null;
        this.started = false;
        this.startCallCount = 0;

        // Handlers assigned by voice_search.js - captured here so
        // tests can invoke them directly to simulate browser events.
        this.onstart = null;
        this.onresult = null;
        this.onerror = null;
        this.onend = null;
    }

    start() {
        this.startCallCount += 1;
        this.started = true;
        if (typeof this.onstart === "function") {
            this.onstart();
        }
    }

    stop() {
        this.started = false;
        if (typeof this.onend === "function") {
            this.onend();
        }
    }

    abort() {
        this.started = false;
    }
}

function makeFakeResult(transcript, isFinal) {
    const alt = { transcript };
    const result = [alt];
    result.isFinal = isFinal;
    return result;
}

function loadVoiceSearch(RecognitionCtor) {
    // Fresh require each time (bypassing Node's module cache) so every
    // test gets an independent module instance bound to its OWN fake
    // window - this project's voice_search.js reads
    // window.SpeechRecognition/webkitSpeechRecognition at load time
    // via the IIFE's `root` argument, so a fresh global per test
    // avoids cross-test leakage.
    const path = require.resolve("./static/voice_search.js");
    delete require.cache[path];

    const fakeWindow = {};
    if (RecognitionCtor) {
        fakeWindow.SpeechRecognition = RecognitionCtor;
    }

    const originalWindow = global.window;
    global.window = fakeWindow;

    let mod;
    try {
        mod = require(path);
    } finally {
        global.window = originalWindow;
    }

    return mod;
}

/* ============================================================
   1/2. Feature detection: supported / unsupported
   ============================================================ */

test("isSupported() is true when SpeechRecognition exists", () => {
    const VoiceSearch = loadVoiceSearch(FakeSpeechRecognition);
    assert.equal(VoiceSearch.isSupported(), true);
});

test("isSupported() is false when neither SpeechRecognition nor webkitSpeechRecognition exists", () => {
    const VoiceSearch = loadVoiceSearch(null);
    assert.equal(VoiceSearch.isSupported(), false);
});

test("createController() returns null when unsupported - caller must hide/disable the mic gracefully", () => {
    const VoiceSearch = loadVoiceSearch(null);
    const controller = VoiceSearch.createController({});
    assert.equal(controller, null);
});

/* ============================================================
   3. Correct recognition object is created (right settings)
   ============================================================ */

test("createController() configures lang=en-IN, interimResults, continuous=false, maxAlternatives=1", () => {
    let createdInstance = null;
    class Spy extends FakeSpeechRecognition {
        constructor() {
            super();
            createdInstance = this;
        }
    }

    const VoiceSearch = loadVoiceSearch(Spy);
    const controller = VoiceSearch.createController({});

    assert.notEqual(controller, null);
    assert.equal(createdInstance.lang, "en-IN");
    assert.equal(createdInstance.interimResults, true);
    assert.equal(createdInstance.continuous, false);
    assert.equal(createdInstance.maxAlternatives, 1);
});

test("createController() accepts a custom lang without hardcoding en-IN forever", () => {
    let createdInstance = null;
    class Spy extends FakeSpeechRecognition {
        constructor() {
            super();
            createdInstance = this;
        }
    }
    const VoiceSearch = loadVoiceSearch(Spy);
    VoiceSearch.createController({ lang: "en-US" });
    assert.equal(createdInstance.lang, "en-US");
});

/* ============================================================
   4/7. Listening state on start; idle again on end
   ============================================================ */

test("start() enters the listening state and fires onStart", () => {
    let started = false;
    const VoiceSearch = loadVoiceSearch(FakeSpeechRecognition);
    const controller = VoiceSearch.createController({
        onStart: () => { started = true; },
    });

    assert.equal(controller.isListening(), false);
    controller.start();
    assert.equal(started, true);
    assert.equal(controller.isListening(), true);
});

test("recognition end returns the controller to idle and fires onEnd", () => {
    let ended = false;
    let instance = null;
    class Spy extends FakeSpeechRecognition {
        constructor() { super(); instance = this; }
    }
    const VoiceSearch = loadVoiceSearch(Spy);
    const controller = VoiceSearch.createController({
        onEnd: () => { ended = true; },
    });

    controller.start();
    instance.onend(); // simulate the browser ending the session
    assert.equal(ended, true);
    assert.equal(controller.isListening(), false);
});

/* ============================================================
   5/6. Final transcript vs interim transcript handling
   ============================================================ */

test("a final result is delivered via onFinalResult, not onInterimResult", () => {
    let finalText = null;
    let interimCalls = 0;
    let instance = null;
    class Spy extends FakeSpeechRecognition {
        constructor() { super(); instance = this; }
    }
    const VoiceSearch = loadVoiceSearch(Spy);
    const controller = VoiceSearch.createController({
        onFinalResult: (t) => { finalText = t; },
        onInterimResult: () => { interimCalls += 1; },
    });

    controller.start();
    instance.onresult({
        resultIndex: 0,
        results: [makeFakeResult("2 BHK flat in Chennai", true)],
    });

    assert.equal(finalText, "2 BHK flat in Chennai");
    assert.equal(interimCalls, 0);
});

test("an interim result does not overwrite/replace a final result that already arrived", () => {
    // Simulates the realistic event sequence: an interim update, then
    // the final result for the SAME utterance. The adapter must not
    // let a stray LATER interim event (e.g. from a new phrase) clobber
    // text the caller has already treated as final - onFinalResult and
    // onInterimResult are separate callbacks specifically so the
    // caller (templates/rentals.html) decides that policy, but the
    // adapter itself must still label each event correctly.
    const received = [];
    let instance = null;
    class Spy extends FakeSpeechRecognition {
        constructor() { super(); instance = this; }
    }
    const VoiceSearch = loadVoiceSearch(Spy);
    const controller = VoiceSearch.createController({
        onInterimResult: (t) => received.push(["interim", t]),
        onFinalResult: (t) => received.push(["final", t]),
    });

    controller.start();

    instance.onresult({
        resultIndex: 0,
        results: [makeFakeResult("two bhk", false)],
    });
    instance.onresult({
        resultIndex: 0,
        results: [makeFakeResult("2 BHK flat", true)],
    });

    assert.deepEqual(received, [
        ["interim", "two bhk"],
        ["final", "2 BHK flat"],
    ]);
});

test("resultIndex is respected so already-final earlier results are not re-emitted", () => {
    const finals = [];
    let instance = null;
    class Spy extends FakeSpeechRecognition {
        constructor() { super(); instance = this; }
    }
    const VoiceSearch = loadVoiceSearch(Spy);
    const controller = VoiceSearch.createController({
        onFinalResult: (t) => finals.push(t),
    });
    controller.start();

    const firstFinal = makeFakeResult("2 BHK", true);
    const secondInterim = makeFakeResult("near VIT", false);

    instance.onresult({ resultIndex: 0, results: [firstFinal] });
    // A later event only reports the NEW result at index 1 via
    // resultIndex - index 0 must not be reprocessed.
    instance.onresult({ resultIndex: 1, results: [firstFinal, secondInterim] });

    assert.deepEqual(finals, ["2 BHK"]);
});

/* ============================================================
   8. Recognition error -> idle + friendly message (never raw)
   ============================================================ */

test("a recognition error returns to idle and reports a friendly message, never the raw code", () => {
    let message = null;
    let code = null;
    let instance = null;
    class Spy extends FakeSpeechRecognition {
        constructor() { super(); instance = this; }
    }
    const VoiceSearch = loadVoiceSearch(Spy);
    const controller = VoiceSearch.createController({
        onError: (msg, rawCode) => { message = msg; code = rawCode; },
    });

    controller.start();
    instance.onerror({ error: "no-speech" });

    assert.equal(controller.isListening(), false);
    assert.equal(message, "Couldn't hear that. Please try again.");
    assert.equal(code, "no-speech");
    assert.equal(message.includes("no-speech"), false);
});

test("an unrecognized error code still produces a friendly, generic message", () => {
    let message = null;
    let instance = null;
    class Spy extends FakeSpeechRecognition {
        constructor() { super(); instance = this; }
    }
    const VoiceSearch = loadVoiceSearch(Spy);
    const controller = VoiceSearch.createController({
        onError: (msg) => { message = msg; },
    });
    controller.start();
    instance.onerror({ error: "some-new-future-browser-error-code" });

    assert.ok(message && message.length > 0);
    assert.equal(message.includes("some-new-future-browser-error-code"), false);
});

test("an 'aborted' error (our own stop()/abort()) is suppressed, not shown to the user", () => {
    let errorCalls = 0;
    let instance = null;
    class Spy extends FakeSpeechRecognition {
        constructor() { super(); instance = this; }
    }
    const VoiceSearch = loadVoiceSearch(Spy);
    const controller = VoiceSearch.createController({
        onError: () => { errorCalls += 1; },
    });
    controller.start();
    instance.onerror({ error: "aborted" });

    assert.equal(errorCalls, 0);
});

/* ============================================================
   Lifecycle safety: no duplicate start(), stop() only when listening
   ============================================================ */

test("calling start() while already listening does not create a second recognition session", () => {
    let instance = null;
    class Spy extends FakeSpeechRecognition {
        constructor() { super(); instance = this; }
    }
    const VoiceSearch = loadVoiceSearch(Spy);
    const controller = VoiceSearch.createController({});

    controller.start();
    controller.start(); // second call while already listening

    assert.equal(instance.startCallCount, 1);
});

test("stop() when not listening is a safe no-op", () => {
    const VoiceSearch = loadVoiceSearch(FakeSpeechRecognition);
    const controller = VoiceSearch.createController({});
    // Never started - must not throw.
    assert.doesNotThrow(() => controller.stop());
});

test("one controller binds handlers exactly once - no duplicate onEnd firing per session", () => {
    let endCount = 0;
    let instance = null;
    class Spy extends FakeSpeechRecognition {
        constructor() { super(); instance = this; }
    }
    const VoiceSearch = loadVoiceSearch(Spy);
    const controller = VoiceSearch.createController({
        onEnd: () => { endCount += 1; },
    });

    controller.start();
    controller.stop();

    assert.equal(endCount, 1);
});
