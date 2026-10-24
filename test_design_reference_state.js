/* ================================================================
   Unit tests for static/design_reference_state.js (the "Design Your
   Home" two-step source-selection / reference-image state machine).

   Run with:
       node --test test_design_reference_state.js

   This project has no JS test framework (no package.json, no Jest/
   Mocha) - matching test_voice_search.js's established convention,
   these tests use Node's built-in node:test + node:assert against the
   real module directly (no DOM, no mocking needed - the module itself
   has no DOM dependency).
   ================================================================ */

const test = require("node:test");
const assert = require("node:assert/strict");

const { create } = require("./static/design_reference_state.js");

test("starts in generate mode with no reference image", () => {
    const state = create();

    assert.equal(state.getMode(), "generate");
    assert.equal(state.isReady(), false);
    assert.deepEqual(state.getReferenceImage(), { source: null, url: null });
});

test("an explicit initial mode is honored", () => {
    const state = create("upload");

    assert.equal(state.getMode(), "upload");
});

test("setReferenceImage makes the state ready", () => {
    const state = create();

    state.setReferenceImage("generated", "data:image/png;base64,AAA");

    assert.equal(state.isReady(), true);
    assert.deepEqual(state.getReferenceImage(), {
        source: "generated",
        url: "data:image/png;base64,AAA",
    });
});

test("clearReferenceImage makes the state not-ready again", () => {
    const state = create();
    state.setReferenceImage("uploaded", "/static/images/design_references/x.png");

    state.clearReferenceImage();

    assert.equal(state.isReady(), false);
    assert.deepEqual(state.getReferenceImage(), { source: null, url: null });
});

test("selecting the already-active mode is a no-op and returns false", () => {
    const state = create("generate");
    state.setReferenceImage("generated", "img-url");

    const changed = state.selectMode("generate");

    assert.equal(changed, false);
    // A no-op mode "switch" must not disturb an already-ready reference
    // image - only an ACTUAL mode change invalidates it.
    assert.equal(state.isReady(), true);
    assert.equal(state.getReferenceImage().url, "img-url");
});

test("selecting a different mode returns true and clears the reference image", () => {
    const state = create("generate");
    state.setReferenceImage("generated", "img-url");

    const changed = state.selectMode("upload");

    assert.equal(changed, true);
    assert.equal(state.getMode(), "upload");
    assert.equal(state.isReady(), false);
});

test("FAILURE SCENARIO: a generated image must not remain active after switching to Upload", () => {
    const state = create("generate");
    state.setReferenceImage("generated", "generated-image-url");
    assert.equal(state.isReady(), true);

    state.selectMode("upload");

    assert.equal(state.getMode(), "upload");
    assert.equal(state.isReady(), false);
    assert.equal(state.getReferenceImage().source, null);
});

test("FAILURE SCENARIO: an uploaded image must not remain active after switching to Generate", () => {
    const state = create("upload");
    state.setReferenceImage("uploaded", "uploaded-image-url");
    assert.equal(state.isReady(), true);

    state.selectMode("generate");

    assert.equal(state.getMode(), "generate");
    assert.equal(state.isReady(), false);
    assert.equal(state.getReferenceImage().source, null);
});

test("a request token captured before any switch is current for its own mode", () => {
    const state = create("generate");

    const token = state.beginRequest();

    assert.equal(state.isRequestCurrent(token, "generate"), true);
});

test("a request token is stale once the mode is switched away", () => {
    const state = create("generate");
    const token = state.beginRequest();

    state.selectMode("upload");

    assert.equal(state.isRequestCurrent(token, "generate"), false);
});

test("a request token is stale even after switching back to the SAME mode", () => {
    // This is the stricter rule: the newly (re)selected mode must
    // produce/select its own reference image again, even if it is the
    // mode the in-flight request was originally made for.
    const state = create("generate");
    const token = state.beginRequest();

    state.selectMode("upload");
    state.selectMode("generate");

    assert.equal(state.getMode(), "generate");
    assert.equal(state.isRequestCurrent(token, "generate"), false);
});

test("a request token captured AFTER the most recent switch is current", () => {
    const state = create("generate");
    state.selectMode("upload");

    const token = state.beginRequest();

    assert.equal(state.isRequestCurrent(token, "upload"), true);
});

test("isRequestCurrent is false for the wrong mode even with a fresh token", () => {
    const state = create("generate");
    const token = state.beginRequest();

    assert.equal(state.isRequestCurrent(token, "upload"), false);
});

test("two independent state instances do not share state", () => {
    const a = create("generate");
    const b = create("generate");

    a.selectMode("upload");
    a.setReferenceImage("uploaded", "a-url");

    assert.equal(b.getMode(), "generate");
    assert.equal(b.isReady(), false);
});
