/* ================================================================
   Reference-image state machine for the "Design Your Home" two-step
   workflow (source selection -> reference image -> similarity
   search).

   Pure logic, NO DOM access - templates/design.html wires this to the
   actual page elements (showing/hiding the generate/upload sections,
   enabling "Find Similar Homes", etc.). Kept in its own file, matching
   static/voice_search.js's convention, so the state transitions can be
   unit-tested directly with Node's built-in node:test (see
   test_design_reference_state.js) - this project has no JS test
   framework, so browser-facing logic that needs real test coverage is
   isolated like this rather than left inline in a <script> tag.

   The one invariant this exists to guarantee: switching between
   "generate" and "upload" mode always invalidates whatever the
   previous mode had produced/selected, and any in-flight generate/
   upload request started before a switch is recognized as stale once
   it resolves - so a generated image can never silently become the
   active reference after switching to Upload, and vice versa (see
   selectMode()/isRequestCurrent() below).
   ================================================================ */

(function (root) {
    "use strict";

    function create(initialMode) {
        var mode = initialMode || "generate";
        var referenceImage = { source: null, url: null };
        var switchToken = 0;

        function getMode() {
            return mode;
        }

        function getReferenceImage() {
            return { source: referenceImage.source, url: referenceImage.url };
        }

        function isReady() {
            return Boolean(referenceImage.url);
        }

        function setReferenceImage(source, url) {
            referenceImage = { source: source, url: url };
        }

        function clearReferenceImage() {
            referenceImage = { source: null, url: null };
        }

        // Switches the active mode. Returns false (no-op) if `nextMode`
        // is already the active mode. Otherwise bumps switchToken (so
        // any request already in flight is recognized as stale once it
        // resolves - see isRequestCurrent()) and clears the reference
        // image, so the mode being left can never leave a stale
        // "ready" reference behind for the new mode to inherit.
        function selectMode(nextMode) {
            if (nextMode === mode) {
                return false;
            }
            switchToken += 1;
            mode = nextMode;
            clearReferenceImage();
            return true;
        }

        // Call at the start of an async generate/upload request; hand
        // the returned token to isRequestCurrent() before applying that
        // request's result.
        function beginRequest() {
            return switchToken;
        }

        // A request is only current if no mode switch has happened
        // since it began AND the app is still in the mode it was made
        // for - true even if the user switched away and back to the
        // SAME mode, since that later switch cleared the reference
        // image too and the newly (re)selected mode must produce or
        // select its own reference image again before becoming active.
        function isRequestCurrent(token, forMode) {
            return token === switchToken && mode === forMode;
        }

        return {
            getMode: getMode,
            getReferenceImage: getReferenceImage,
            isReady: isReady,
            setReferenceImage: setReferenceImage,
            clearReferenceImage: clearReferenceImage,
            selectMode: selectMode,
            beginRequest: beginRequest,
            isRequestCurrent: isRequestCurrent
        };
    }

    var DesignReferenceState = { create: create };

    if (typeof module !== "undefined" && module.exports) {
        module.exports = DesignReferenceState;
    } else {
        root.DesignReferenceState = DesignReferenceState;
    }

})(typeof window !== "undefined" ? window : globalThis);
