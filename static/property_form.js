/* ================================================================
   Dynamic property listing submission form.

   Reads window.PROPERTY_FIELD_CONFIG (built from
   services/property_fields.py) so the show/hide rules here can
   never drift from what the backend actually accepts.
   ================================================================ */

(function () {
    "use strict";

    const CONFIG = window.PROPERTY_FIELD_CONFIG || {};
    const IMAGE_CATEGORIES = window.PROPERTY_IMAGE_CATEGORIES || [];
    const GEOAPIFY_ENABLED = window.GEOAPIFY_ENABLED === true;

    let map = null;
    let marker = null;
    let searchDebounce = null;

    const DEFAULT_LAT = 12.84230234;
    const DEFAULT_LON = 80.15376091;


    // ============================================================
    // FIELD VISIBILITY
    // ============================================================

    function currentPropertyType() {
        const el = document.getElementById("pf_property_type");
        return el ? el.value : "";
    }

    function currentListingType() {
        const el = document.getElementById("pf_listing_type");
        return el ? el.value : "";
    }

    function updateListingTypeAvailability() {
        const listingSelect = document.getElementById("pf_listing_type");
        if (!listingSelect) return;

        const isRentOnly = (CONFIG.rentOnlyPropertyTypes || [])
            .includes(currentPropertyType());

        const sellOption = listingSelect.querySelector('option[value="sell"]');
        if (!sellOption) return;

        sellOption.disabled = isRentOnly;

        if (isRentOnly && listingSelect.value === "sell") {
            listingSelect.value = "rent";
        }
    }

    function updateFieldVisibility() {
        const propertyType = currentPropertyType();
        const listingType = currentListingType();

        document.querySelectorAll(".pf-field[data-applies-to]").forEach(function (el) {
            const raw = el.getAttribute("data-applies-to") || "";
            const applies = raw.split(",").filter(Boolean);

            // Before a property type is chosen, don't hide anything —
            // the form narrows down once the user actually picks one.
            const show = !propertyType || applies.length === 0 || applies.includes(propertyType);

            el.hidden = !show;

            el.querySelectorAll("input, select, textarea").forEach(function (input) {
                input.disabled = !show;
            });
        });

        document.querySelectorAll(".pf-group").forEach(function (group) {
            const listingOnly = group.getAttribute("data-listing-only");
            const excludeRaw = group.getAttribute("data-property-exclude") || "";
            const excludeTypes = excludeRaw.split(",").filter(Boolean);

            let visible = true;

            if (listingOnly === "rent" && listingType !== "rent") visible = false;
            if (listingOnly === "sale" && listingType !== "sell") visible = false;
            if (excludeTypes.includes(propertyType)) visible = false;

            if (visible && group.getAttribute("data-always-show") !== "true") {
                const visibleFields = Array.prototype.slice
                    .call(group.querySelectorAll(".pf-field"))
                    .filter(function (field) { return !field.hidden; });

                visible = visibleFields.length > 0;
            }

            group.hidden = !visible;
        });
    }

    function handleTypeChange() {
        updateListingTypeAvailability();
        updateFieldVisibility();
    }


    // ============================================================
    // IMAGE UPLOAD PREVIEW (category + cover selection)
    // ============================================================

    function renderImagePreviews() {
        const input = document.getElementById("pf_images");
        const list = document.getElementById("pfImagePreviewList");

        if (!input || !list) return;

        list.innerHTML = "";

        const files = Array.prototype.slice.call(input.files || []);

        files.forEach(function (file, index) {

            const item = document.createElement("div");
            item.className = "pf-image-item";

            const img = document.createElement("img");
            img.src = URL.createObjectURL(file);
            img.alt = file.name;
            item.appendChild(img);

            const categorySelect = document.createElement("select");
            categorySelect.name = "image_category_" + index;

            IMAGE_CATEGORIES.forEach(function (pair) {
                const option = document.createElement("option");
                option.value = pair[0];
                option.textContent = pair[1];
                if (pair[0] === "other") option.selected = true;
                categorySelect.appendChild(option);
            });

            item.appendChild(categorySelect);

            const coverLabel = document.createElement("label");
            const coverRadio = document.createElement("input");
            coverRadio.type = "radio";
            coverRadio.name = "cover_image";
            coverRadio.value = String(index);
            if (index === 0) coverRadio.checked = true;

            coverLabel.appendChild(coverRadio);
            coverLabel.appendChild(document.createTextNode(" Cover photo"));
            item.appendChild(coverLabel);

            list.appendChild(item);
        });
    }


    // ============================================================
    // MAP + GEOAPIFY LOCATION SEARCH
    // ============================================================

    function initMap() {

        if (map !== null) {
            map.invalidateSize();
            return;
        }

        const mapContainer = document.getElementById("pfPropertyMap");
        if (!mapContainer || typeof L === "undefined") return;

        map = L.map("pfPropertyMap").setView([DEFAULT_LAT, DEFAULT_LON], 14);

        L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
            maxZoom: 19,
            attribution: "&copy; OpenStreetMap contributors"
        }).addTo(map);

        map.on("click", function (event) {
            setMarker(event.latlng.lat, event.latlng.lng, true);
        });

        setMarker(DEFAULT_LAT, DEFAULT_LON, false);
    }

    function setMarker(lat, lon, reverseGeocode) {

        if (marker === null) {

            marker = L.marker([lat, lon], { draggable: true }).addTo(map);

            marker.on("dragend", function () {
                const pos = marker.getLatLng();
                setMarker(pos.lat, pos.lng, true);
            });

        } else {

            marker.setLatLng([lat, lon]);
        }

        map.setView([lat, lon], 16);

        const latInput = document.getElementById("pf_latitude");
        const lonInput = document.getElementById("pf_longitude");

        if (latInput) latInput.value = lat.toFixed(8);
        if (lonInput) lonInput.value = lon.toFixed(8);

        if (reverseGeocode && GEOAPIFY_ENABLED) {
            reverseGeocodeLocation(lat, lon);
        }
    }

    function fillLocationFields(data) {

        const map = {
            "pf_address": data.formatted || data.address_line1,
            "pf_city": data.city,
            "pf_state": data.state,
            "pf_locality": data.locality,
            "pf_sub_locality": data.sub_locality,
            "pf_pincode": data.postcode
        };

        Object.keys(map).forEach(function (id) {
            const el = document.getElementById(id);
            const value = map[id];
            if (el && value) el.value = value;
        });
    }

    async function reverseGeocodeLocation(lat, lon) {

        try {

            const url = "/api/location/reverse?lat=" + encodeURIComponent(lat) +
                "&lon=" + encodeURIComponent(lon);

            const response = await fetch(url);
            if (!response.ok) return;

            const data = await response.json();
            fillLocationFields(data);

            const searchBox = document.getElementById("pfLocationSearch");
            if (searchBox && data.formatted) searchBox.value = data.formatted;

        } catch (error) {
            console.error("Reverse geocoding error:", error);
        }
    }

    async function searchLocation(query) {

        try {

            const params = new URLSearchParams({ text: query });

            if (marker) {
                const pos = marker.getLatLng();
                params.set("lat", pos.lat);
                params.set("lon", pos.lng);
            }

            const response = await fetch("/api/location/autocomplete?" + params.toString());
            if (!response.ok) return;

            const data = await response.json();
            renderSuggestions(data.results || []);

        } catch (error) {
            console.error("Location search error:", error);
        }
    }

    function renderSuggestions(results) {

        const container = document.getElementById("pfLocationSuggestions");
        if (!container) return;

        container.innerHTML = "";

        if (!results.length) {
            container.style.display = "none";
            return;
        }

        results.forEach(function (result) {

            const item = document.createElement("div");
            item.className = "pf-location-suggestion";
            item.textContent = result.formatted || result.address_line1 || "Unknown location";

            item.addEventListener("click", function () {

                fillLocationFields(result);

                const searchBox = document.getElementById("pfLocationSearch");
                if (searchBox) searchBox.value = result.formatted || "";

                container.style.display = "none";

                if (result.lat && result.lon) {
                    setMarker(parseFloat(result.lat), parseFloat(result.lon), false);
                }
            });

            container.appendChild(item);
        });

        container.style.display = "block";
    }


    // ============================================================
    // INIT
    // ============================================================

    function init() {

        const propertyTypeSelect = document.getElementById("pf_property_type");
        const listingTypeSelect = document.getElementById("pf_listing_type");

        if (propertyTypeSelect) {
            propertyTypeSelect.addEventListener("change", handleTypeChange);
        }

        if (listingTypeSelect) {
            listingTypeSelect.addEventListener("change", updateFieldVisibility);
        }

        handleTypeChange();

        const imagesInput = document.getElementById("pf_images");
        if (imagesInput) {
            imagesInput.addEventListener("change", renderImagePreviews);
        }

        if (GEOAPIFY_ENABLED) {

            const searchBox = document.getElementById("pfLocationSearch");

            if (searchBox) {

                searchBox.addEventListener("input", function () {

                    const query = this.value.trim();
                    clearTimeout(searchDebounce);

                    if (query.length < 3) {
                        document.getElementById("pfLocationSuggestions").style.display = "none";
                        return;
                    }

                    searchDebounce = setTimeout(function () {
                        searchLocation(query);
                    }, 500);
                });
            }

            document.addEventListener("click", function (event) {

                const wrapper = document.querySelector(".pf-location-search-wrapper");

                if (wrapper && !wrapper.contains(event.target)) {
                    const suggestions = document.getElementById("pfLocationSuggestions");
                    if (suggestions) suggestions.style.display = "none";
                }
            });
        }

        // The map lives inside the "Sell" tab, which starts hidden.
        // Initialize it once that tab becomes visible.
        window.pfInitMapIfVisible = function () {

            const sellForm = document.getElementById("sellForm");

            if (sellForm && sellForm.style.display !== "none") {

                setTimeout(function () {
                    initMap();
                    if (map) map.invalidateSize();
                }, 100);
            }
        };
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }

})();
