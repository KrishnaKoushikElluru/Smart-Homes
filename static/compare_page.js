/*
 * templates/compare.html's own rendering logic.
 *
 * Fetches GET /api/compare?items=... (routes/comparison_routes.py),
 * then renders a properties-as-columns / dimensions-as-rows table
 * plus a per-property rating section. Entirely separate from
 * static/comparison.js (which only manages the selection/localStorage
 * state on the OTHER pages) - this file never writes to localStorage
 * itself, it only reads the selection once, as a fallback, via
 * window.SmartHomesCompare.getSelection().
 */

(function () {
    "use strict";

    var CATEGORY_ORDER = [
        "price_value",
        "location",
        "facilities",
        "availability",
        "connectivity",
        "property_features",
    ];

    function esc(value) {
        var div = document.createElement("div");
        div.textContent = value === null || value === undefined ? "" : String(value);
        return div.innerHTML;
    }

    function naOr(value, formatter) {
        if (value === null || value === undefined || value === "") {
            return '<span class="not-available">Not available</span>';
        }
        return formatter ? formatter(value) : esc(value);
    }

    function getItemsFromUrlOrSelection() {
        var params = new URLSearchParams(window.location.search);
        var items = params.get("items");
        if (items) {
            return items;
        }

        if (window.SmartHomesCompare) {
            var selection = window.SmartHomesCompare.getSelection();
            if (selection.length >= 2) {
                return selection
                    .map(function (item) {
                        return encodeURIComponent(item.provider) + ":" + encodeURIComponent(item.id);
                    })
                    .join(",");
            }
        }

        return null;
    }

    function showError(message) {
        var loading = document.getElementById("compareLoading");
        var errorBox = document.getElementById("compareError");
        if (loading) {
            loading.style.display = "none";
        }
        if (errorBox) {
            errorBox.textContent = message;
            errorBox.style.display = "block";
        }
    }

    function renderFailed(failed) {
        var container = document.getElementById("compareFailed");
        if (!container || !failed || failed.length === 0) {
            return;
        }

        var html = "";
        failed.forEach(function (item) {
            html +=
                '<div class="compare-failed-item">' +
                "<strong>" + esc(item.provider) + ":" + esc(item.id) + "</strong> - " +
                esc(item.reason) +
                "</div>";
        });
        container.innerHTML = html;
    }

    function formatPrice(property) {
        if (property.price_on_request) {
            return "Price on request";
        }
        if (property.price === null || property.price === undefined) {
            return naOr(null);
        }
        return "&#8377;" + esc(property.price);
    }

    function formatAmenities(property) {
        var amenities = property.amenities_flat;
        if (amenities === null || amenities === undefined) {
            return naOr(null);
        }
        if (amenities.length === 0) {
            return "<em>None listed</em>";
        }
        return esc(amenities.length) + " amenities: " + esc(amenities.slice(0, 8).join(", ")) +
            (amenities.length > 8 ? ", &hellip;" : "");
    }

    function formatNearbyFacilities(property) {
        var facilities = property.nearby_facilities;
        if (facilities === null || facilities === undefined) {
            return naOr(null);
        }
        if (facilities.length === 0) {
            return "<em>None found nearby</em>";
        }
        var byCategory = {};
        facilities.forEach(function (facility) {
            var category = facility.category || "other";
            byCategory[category] = (byCategory[category] || 0) + 1;
        });
        var parts = [];
        Object.keys(byCategory).forEach(function (category) {
            parts.push(esc(category) + " (" + byCategory[category] + ")");
        });
        return parts.join(", ");
    }

    var DIMENSION_ROWS = [
        {
            label: "Source",
            render: function (p) {
                var cls = p.provider === "squareyards" ? "squareyards" : "smarthomes";
                var text = p.provider === "squareyards" ? "Square Yards" : "SmartHomes";
                return '<span class="source-badge ' + cls + '">' + text + "</span>";
            },
        },
        {
            label: "Image",
            render: function (p) {
                if (!p.image_url) {
                    return naOr(null);
                }
                return '<img class="compare-image" src="' + esc(p.image_url) + '" alt="Property image">';
            },
        },
        { label: "Title", render: function (p) { return naOr(p.title); } },
        { label: "Price", render: formatPrice },
        { label: "BHK", render: function (p) { return naOr(p.bhk); } },
        { label: "Area (sq.ft)", render: function (p) { return naOr(p.area_sqft); } },
        { label: "Property Type", render: function (p) { return naOr(p.property_type); } },
        { label: "Listing Type", render: function (p) { return naOr(p.listing_type); } },
        { label: "City", render: function (p) { return naOr(p.city); } },
        { label: "Locality", render: function (p) { return naOr(p.locality); } },
        { label: "Furnishing", render: function (p) { return naOr(p.furnishing); } },
        { label: "Bathrooms", render: function (p) { return naOr(p.bathrooms); } },
        { label: "Balconies", render: function (p) { return naOr(p.balconies); } },
        { label: "Floor", render: function (p) { return naOr(p.floor_number); } },
        { label: "Facing", render: function (p) { return naOr(p.facing); } },
        { label: "Amenities", render: formatAmenities },
        { label: "Listing Status", render: function (p) { return naOr(p.status); } },
        { label: "Available From", render: function (p) { return naOr(p.available_from); } },
        { label: "Possession Status", render: function (p) { return naOr(p.possession_status); } },
        { label: "Nearby Facilities", render: formatNearbyFacilities },
        {
            label: "Full Listing",
            render: function (p) {
                if (!p.detail_url) {
                    return naOr(null);
                }
                var external = p.provider === "squareyards";
                return '<a href="' + esc(p.detail_url) + '"' +
                    (external ? ' target="_blank" rel="noopener noreferrer"' : "") +
                    ">View" + (external ? " on Square Yards" : " full details") + "</a>";
            },
        },
    ];

    function renderRatingCell(category) {
        if (category.status !== "valid" || category.score === null) {
            return (
                '<p class="not-available">' + esc(category.reason) + "</p>"
            );
        }
        var score = category.score;
        return (
            '<div class="rating-row">' +
                '<div class="rating-bar-track"><div class="rating-bar-fill" style="width: ' + score + '%;"></div></div>' +
                '<span class="rating-score">' + score + "/100</span>" +
            "</div>" +
            '<p class="rating-reason">' + esc(category.reason) + "</p>"
        );
    }

    function renderOverallCell(overall) {
        if (overall.status !== "valid" || overall.score === null) {
            return '<p class="not-available">' + esc(overall.reason) + "</p>";
        }
        return (
            '<div class="overall-rating">' + overall.score + "/100</div>" +
            '<p class="overall-basis">Based on: ' + esc(overall.basis.join(", ")) + "</p>"
        );
    }

    function renderTable(properties) {
        var wrap = document.getElementById("compareTableWrap");
        if (!wrap) {
            return;
        }

        var html = '<table class="compare-table"><tbody>';

        html += "<tr><th></th>";
        properties.forEach(function () {
            html += '<th class="property-column-header">Property</th>';
        });
        html += "</tr>";

        DIMENSION_ROWS.forEach(function (row) {
            html += '<tr><th class="dimension-label">' + esc(row.label) + "</th>";
            properties.forEach(function (p) {
                html += "<td>" + row.render(p) + "</td>";
            });
            html += "</tr>";
        });

        html += '<tr><th class="dimension-label" colspan="' + (properties.length + 1) + '" style="text-align:center; background:#ddd;">Category Ratings</th></tr>';

        CATEGORY_ORDER.forEach(function (key) {
            var firstCategory = properties.length > 0 ? properties[0].ratings.categories[key] : null;
            var label = firstCategory ? firstCategory.label : key;
            html += '<tr><th class="dimension-label">' + esc(label) + "</th>";
            properties.forEach(function (p) {
                var category = p.ratings.categories[key];
                html += "<td>" + renderRatingCell(category) + "</td>";
            });
            html += "</tr>";
        });

        html += '<tr><th class="dimension-label">Overall Rating</th>';
        properties.forEach(function (p) {
            html += "<td>" + renderOverallCell(p.ratings.overall) + "</td>";
        });
        html += "</tr>";

        html += "</tbody></table>";

        wrap.innerHTML = html;
    }

    function init() {
        var clearLink = document.getElementById("compareClearLink");
        if (clearLink) {
            clearLink.addEventListener("click", function () {
                if (window.SmartHomesCompare) {
                    window.SmartHomesCompare.clearSelection();
                }
                window.location.href = "/rentals";
            });
        }

        var items = getItemsFromUrlOrSelection();
        if (!items) {
            showError("No properties selected for comparison. Go back and select at least 2 properties.");
            return;
        }

        fetch("/api/compare?items=" + encodeURIComponent(items))
            .then(function (response) {
                if (!response.ok) {
                    return response.json().then(function (body) {
                        throw new Error((body && body.error) || "Could not load comparison.");
                    });
                }
                return response.json();
            })
            .then(function (data) {
                var loading = document.getElementById("compareLoading");
                if (loading) {
                    loading.style.display = "none";
                }

                renderFailed(data.failed);

                if (!data.properties || data.properties.length === 0) {
                    showError("None of the selected properties could be loaded.");
                    return;
                }

                renderTable(data.properties);
            })
            .catch(function (error) {
                showError(error.message || "Could not load comparison.");
            });
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
