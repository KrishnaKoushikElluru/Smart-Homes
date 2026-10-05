/*
 * Property Comparison - selection state + floating bar.
 *
 * Self-contained module, loaded on templates/rentals.html and
 * templates/property_details.html. Does NOT touch property_form.js
 * (submission-form logic), voice_search.js, search/filter/NLP
 * handling, or anything already on either page - it only reads
 * `.compare-checkbox` elements those templates now render and writes
 * to its own localStorage key.
 *
 * Selection is stored client-side only, as a plain array of
 * {provider, id} objects - no backend call happens until the user
 * actually clicks "Compare Now", which navigates to
 * /compare?items=provider:id,provider:id,... (routes/comparison_routes.py).
 */

(function () {
    "use strict";

    var STORAGE_KEY = "smarthomes_compare_selection";
    var MIN_ITEMS = 2;
    var MAX_ITEMS = 4;

    function getSelection() {
        try {
            var raw = window.localStorage.getItem(STORAGE_KEY);
            if (!raw) {
                return [];
            }
            var parsed = JSON.parse(raw);
            if (!Array.isArray(parsed)) {
                return [];
            }
            return parsed.filter(function (item) {
                return item && typeof item.provider === "string" && typeof item.id === "string";
            });
        } catch (error) {
            return [];
        }
    }

    function saveSelection(selection) {
        try {
            window.localStorage.setItem(STORAGE_KEY, JSON.stringify(selection));
        } catch (error) {
            // Private browsing / storage disabled / quota exceeded - the
            // feature simply stops persisting across reloads, nothing
            // else on the page is affected.
        }
    }

    function findIndex(selection, provider, id) {
        for (var i = 0; i < selection.length; i++) {
            if (selection[i].provider === provider && selection[i].id === id) {
                return i;
            }
        }
        return -1;
    }

    function isSelected(provider, id) {
        return findIndex(getSelection(), provider, id) !== -1;
    }

    function addSelection(provider, id) {
        var selection = getSelection();
        if (findIndex(selection, provider, id) !== -1) {
            return true;
        }
        if (selection.length >= MAX_ITEMS) {
            window.alert("You can compare at most " + MAX_ITEMS + " properties at a time.");
            return false;
        }
        selection.push({ provider: provider, id: id });
        saveSelection(selection);
        return true;
    }

    function removeSelection(provider, id) {
        var selection = getSelection();
        var index = findIndex(selection, provider, id);
        if (index !== -1) {
            selection.splice(index, 1);
            saveSelection(selection);
        }
    }

    function clearSelection() {
        saveSelection([]);
        syncCheckboxes();
        updateFloatingBar();
    }

    function syncCheckboxes() {
        var selection = getSelection();
        var checkboxes = document.querySelectorAll(".compare-checkbox");
        for (var i = 0; i < checkboxes.length; i++) {
            var box = checkboxes[i];
            var provider = box.getAttribute("data-provider");
            var id = box.getAttribute("data-id");
            box.checked = findIndex(selection, provider, id) !== -1;
        }
    }

    function updateFloatingBar() {
        var bar = document.getElementById("compareFloatingBar");
        if (!bar) {
            return;
        }
        var selection = getSelection();
        var countLabel = document.getElementById("compareFloatingBarCount");
        if (countLabel) {
            countLabel.textContent = "Compare (" + selection.length + ")";
        }
        bar.style.display = selection.length >= MIN_ITEMS ? "" : "none";
    }

    function navigateToCompare() {
        var selection = getSelection();
        if (selection.length < MIN_ITEMS) {
            window.alert("Select at least " + MIN_ITEMS + " properties to compare.");
            return;
        }
        var items = selection
            .map(function (item) {
                return encodeURIComponent(item.provider) + ":" + encodeURIComponent(item.id);
            })
            .join(",");
        window.location.href = "/compare?items=" + items;
    }

    function handleCheckboxChange(event) {
        var target = event.target;
        if (!target || !target.classList || !target.classList.contains("compare-checkbox")) {
            return;
        }
        var provider = target.getAttribute("data-provider");
        var id = target.getAttribute("data-id");
        if (!provider || !id) {
            return;
        }

        if (target.checked) {
            var added = addSelection(provider, id);
            if (!added) {
                target.checked = false;
            }
        } else {
            removeSelection(provider, id);
        }

        updateFloatingBar();
    }

    function init() {
        // Event delegation on document - works for cards that exist at
        // load time AND cards re-rendered later by search/filter
        // (renderPropertyResults() in templates/rentals.html), without
        // needing to touch that rendering code at all.
        document.addEventListener("change", handleCheckboxChange);

        var goButton = document.getElementById("compareFloatingBarGo");
        if (goButton) {
            goButton.addEventListener("click", navigateToCompare);
        }

        var clearButton = document.getElementById("compareFloatingBarClear");
        if (clearButton) {
            clearButton.addEventListener("click", clearSelection);
        }

        syncCheckboxes();
        updateFloatingBar();

        // Search results are re-rendered into #listingsContainer by
        // existing code this module never calls directly - a
        // MutationObserver keeps newly-rendered checkboxes' checked
        // state in sync with the stored selection without requiring
        // any change to that rendering code.
        var container = document.getElementById("listingsContainer");
        if (container && window.MutationObserver) {
            var observer = new MutationObserver(syncCheckboxes);
            observer.observe(container, { childList: true, subtree: true });
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

    // Exposed for the compare page itself (templates/compare.html) to
    // read/clear the same stored selection without duplicating the
    // localStorage logic above.
    window.SmartHomesCompare = {
        getSelection: getSelection,
        clearSelection: clearSelection,
    };
})();
