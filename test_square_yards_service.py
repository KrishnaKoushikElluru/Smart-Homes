"""
Unit tests for services/external_property_sources/square_yards_service.py
- the Square Yards external search provider.

Every test here is fully OFFLINE: the `mcp` SDK and the real MCP
endpoint are never touched. MCP calls go through _call_tool(), which
this file patches directly (mirrors test_property_routes.py's existing
convention of patching a lazily-imported module's call sites rather
than mocking the import machinery itself). The one live-MCP check for
this feature is a separate, explicitly-manual script - not part of
this automated suite (see Phase 7/8's reports).
"""

import unittest
from unittest.mock import patch

from services.external_property_sources import square_yards_service as sy


# ============================================================
# URL CONSTRUCTION (Phase 2)
# ============================================================

class BuildListingUrlTests(unittest.TestCase):

    def test_relative_slug_is_prefixed_with_domain(self):
        url = sy.build_listing_url("rental-2-bhk-1071-sq-ft-apartment-in-pushkar-kausaliya-enclave/10681304")
        self.assertEqual(
            url,
            "https://www.squareyards.com/rental-2-bhk-1071-sq-ft-apartment-in-pushkar-kausaliya-enclave/10681304",
        )

    def test_leading_slash_does_not_produce_a_double_slash(self):
        url = sy.build_listing_url("/rental-foo/123")
        self.assertEqual(url, "https://www.squareyards.com/rental-foo/123")
        self.assertNotIn("//rental-foo", url.replace("https://", ""))

    def test_already_complete_squareyards_url_passes_through(self):
        url = sy.build_listing_url("https://www.squareyards.com/rental-foo/123")
        self.assertEqual(url, "https://www.squareyards.com/rental-foo/123")

    def test_complete_url_on_bare_squareyards_domain_passes_through(self):
        url = sy.build_listing_url("https://squareyards.com/rental-foo/123")
        self.assertEqual(url, "https://squareyards.com/rental-foo/123")

    def test_complete_url_on_unrelated_domain_is_rejected(self):
        self.assertIsNone(sy.build_listing_url("https://evil-phishing-site.com/rental-foo/123"))

    def test_complete_url_on_lookalike_domain_is_rejected(self):
        # "notsquareyards.com" must not match via a naive substring check.
        self.assertIsNone(sy.build_listing_url("https://notsquareyards.com/foo/123"))

    def test_none_is_rejected(self):
        self.assertIsNone(sy.build_listing_url(None))

    def test_empty_string_is_rejected(self):
        self.assertIsNone(sy.build_listing_url(""))

    def test_whitespace_only_is_rejected(self):
        self.assertIsNone(sy.build_listing_url("   "))

    def test_value_containing_whitespace_is_rejected(self):
        self.assertIsNone(sy.build_listing_url("not a url at all/123"))

    def test_non_string_is_rejected(self):
        self.assertIsNone(sy.build_listing_url(12345))

    def test_relative_path_with_only_slashes_is_rejected(self):
        self.assertIsNone(sy.build_listing_url("///"))


# ============================================================
# STRUCTURED FILTER -> SEARCH ARGS (Phase 4)
# ============================================================

class BuildSearchArgsTests(unittest.TestCase):

    def test_full_filters_map_correctly(self):
        args = sy.build_search_args({
            "listing_type": "rent",
            "area_or_city_text": "Chennai",
            "bhk": 2,
            "furnishing": "semi_furnished",
            "price": {"mongo": {"$lte": 30000}},
        })
        self.assertEqual(args["listingType"], "Rent")
        self.assertEqual(args["location"], "Chennai")
        self.assertEqual(args["bedrooms"], "2 BHK")
        self.assertEqual(args["furnishing"], "Semi-Furnished")
        self.assertEqual(args["maxPrice"], 30000)

    def test_sale_listing_type_maps_to_sale(self):
        args = sy.build_search_args({"listing_type": "sell", "area_or_city_text": "Chennai"})
        self.assertEqual(args["listingType"], "Sale")

    def test_missing_city_returns_none(self):
        self.assertIsNone(sy.build_search_args({"listing_type": "rent"}))

    def test_missing_listing_type_returns_none(self):
        self.assertIsNone(sy.build_search_args({"area_or_city_text": "Chennai"}))

    def test_unmapped_property_type_is_omitted_not_guessed(self):
        args = sy.build_search_args({
            "listing_type": "rent", "area_or_city_text": "Chennai", "property_type": "pg_hostel",
        })
        self.assertNotIn("propertyTypeName", args)

    def test_mapped_property_type_is_included(self):
        args = sy.build_search_args({
            "listing_type": "rent", "area_or_city_text": "Chennai", "property_type": "apartment",
        })
        self.assertEqual(args["propertyTypeName"], "Apartment")

    def test_price_gte_maps_to_min_price(self):
        args = sy.build_search_args({
            "listing_type": "rent", "area_or_city_text": "Chennai",
            "price": {"mongo": {"$gte": 15000}},
        })
        self.assertEqual(args["minPrice"], 15000)

    def test_half_bhk_formats_correctly(self):
        args = sy.build_search_args({
            "listing_type": "rent", "area_or_city_text": "Chennai", "bhk": 2.5,
        })
        self.assertEqual(args["bedrooms"], "2.5 BHK")


# ============================================================
# NORMALIZATION (Phase 1)
# ============================================================

class NormalizeSearchCardTests(unittest.TestCase):

    def test_normalizes_a_real_shaped_card(self):
        card = {
            "id": "10681304", "title": "2 BHK Apartment", "transactionType": "rent",
            "price": 31000, "bhk": 2, "areaSqft": 1071, "propertyType": "Apartment",
            "locality": "Kil Ayanambakkam", "city": "Chennai",
            "image": "https://img.squareyards.com/x.jpg",
            "url": "rental-foo/10681304",
            "amenities": ["Power Backup"],
        }
        n = sy._normalize_search_card(card)
        self.assertEqual(n["source"], "squareyards")
        self.assertEqual(n["external_id"], "10681304")
        self.assertEqual(n["listing_type"], "rent")
        self.assertEqual(n["price"], 31000)
        self.assertEqual(n["bhk"], 2)
        self.assertEqual(n["source_url"], "https://www.squareyards.com/rental-foo/10681304")
        self.assertEqual(n["images"], ["https://img.squareyards.com/x.jpg"])

    def test_missing_fields_stay_none_never_invented(self):
        n = sy._normalize_search_card({"id": "1"})
        self.assertIsNone(n["title"])
        self.assertIsNone(n["price"])
        self.assertIsNone(n["bhk"])
        self.assertEqual(n["amenities"], [])
        self.assertEqual(n["images"], [])
        self.assertIsNone(n["source_url"])

    def test_price_on_request_flag(self):
        n = sy._normalize_search_card({"id": "1", "priceOnRequest": True, "price": None})
        self.assertTrue(n["price_on_request"])
        self.assertIsNone(n["price"])

    def test_sale_transaction_type_normalizes_to_sell(self):
        n = sy._normalize_search_card({"id": "1", "transactionType": "sale"})
        self.assertEqual(n["listing_type"], "sell")

    def test_rent_transaction_type_stays_rent(self):
        n = sy._normalize_search_card({"id": "1", "transactionType": "rent"})
        self.assertEqual(n["listing_type"], "rent")

    def test_transaction_type_normalization_is_case_insensitive(self):
        n = sy._normalize_search_card({"id": "1", "transactionType": "Sale"})
        self.assertEqual(n["listing_type"], "sell")

    def test_unrecognized_transaction_type_is_unknown_not_invented(self):
        n = sy._normalize_search_card({"id": "1", "transactionType": "lease"})
        self.assertIsNone(n["listing_type"])

    def test_other_fields_unaffected_by_listing_type_normalization(self):
        card = {
            "id": "10681304", "title": "2 BHK Apartment", "transactionType": "sale",
            "price": 7000000, "bhk": 2, "areaSqft": 830, "propertyType": "Apartment",
            "locality": "Vadapalani", "city": "Chennai",
        }
        n = sy._normalize_search_card(card)
        self.assertEqual(n["listing_type"], "sell")
        self.assertEqual(n["price"], 7000000)
        self.assertEqual(n["bhk"], 2)
        self.assertEqual(n["locality"], "Vadapalani")
        self.assertEqual(n["city"], "Chennai")


class NormalizeListingDetailTests(unittest.TestCase):

    def _make_detail(self, **listing_data_overrides):
        listing_data = {
            "propertyId": 10681304, "propertyTitle": "2 BHK Apartment",
            "totalPrice": "31000", "listingType": "Rent", "unitType": "2 BHK",
            "propertyType": "Apartment", "atreaInSqFt": 1071,
            "subLocalityName": "Kil Ayanambakkam", "cityName": "Chennai",
            "url": "rental-foo/10681304",
            "attributes": {"Furnishing Status": "Semi-Furnished"},
            "amenities": ["Power Backup"],
            "images": ["https://img.squareyards.com/a.jpg", "https://img.squareyards.com/b.jpg"],
        }
        listing_data.update(listing_data_overrides)
        return {"detail": {"listingData": listing_data}}

    def test_normalizes_a_real_shaped_detail(self):
        n = sy.normalize_listing_detail(self._make_detail())
        self.assertEqual(n["external_id"], "10681304")
        self.assertEqual(n["price"], 31000.0)
        self.assertEqual(n["bhk"], 2.0)
        self.assertEqual(n["furnishing"], "semi_furnished")
        self.assertEqual(len(n["images"]), 2)
        self.assertEqual(n["source_url"], "https://www.squareyards.com/rental-foo/10681304")

    def test_furnished_maps_to_fully_furnished(self):
        n = sy.normalize_listing_detail(self._make_detail(attributes={"Furnishing Status": "Furnished"}))
        self.assertEqual(n["furnishing"], "fully_furnished")

    def test_price_on_request_when_total_price_missing(self):
        n = sy.normalize_listing_detail(self._make_detail(totalPrice=None))
        self.assertIsNone(n["price"])
        self.assertTrue(n["price_on_request"])

    def test_malformed_response_returns_none(self):
        self.assertIsNone(sy.normalize_listing_detail({}))
        self.assertIsNone(sy.normalize_listing_detail({"detail": {}}))
        self.assertIsNone(sy.normalize_listing_detail("not even a dict"))
        self.assertIsNone(sy.normalize_listing_detail(None))

    def test_studio_unit_type_has_no_bhk(self):
        n = sy.normalize_listing_detail(self._make_detail(unitType="Studio"))
        self.assertIsNone(n["bhk"])

    def test_sale_listing_type_normalizes_to_sell(self):
        n = sy.normalize_listing_detail(self._make_detail(listingType="Sale"))
        self.assertEqual(n["listing_type"], "sell")

    def test_rent_listing_type_stays_rent(self):
        n = sy.normalize_listing_detail(self._make_detail(listingType="Rent"))
        self.assertEqual(n["listing_type"], "rent")


# ============================================================
# SAFETY FILTER (Phase 4's second layer)
# ============================================================

class SafetyFilterTests(unittest.TestCase):

    def test_matching_listing_passes(self):
        normalized = {"listing_type": "rent", "bhk": 2, "furnishing": "semi_furnished", "price": 24000}
        applied = {
            "listing_type": "rent", "bhk": 2, "furnishing": "semi_furnished",
            "price": {"mongo": {"$lte": 30000}},
        }
        self.assertTrue(sy._matches_safety_filter(normalized, applied))

    def test_wrong_bhk_is_rejected(self):
        normalized = {"bhk": 1}
        applied = {"bhk": 2}
        self.assertFalse(sy._matches_safety_filter(normalized, applied))

    def test_over_budget_is_rejected(self):
        normalized = {"price": 35000}
        applied = {"price": {"mongo": {"$lte": 30000}}}
        self.assertFalse(sy._matches_safety_filter(normalized, applied))

    def test_wrong_furnishing_is_rejected(self):
        normalized = {"furnishing": "furnished"}  # not a real SmartHomes code, intentionally mismatched
        applied = {"furnishing": "semi_furnished"}
        self.assertFalse(sy._matches_safety_filter(normalized, applied))

    def test_missing_field_on_listing_is_not_auto_rejected(self):
        # Square Yards didn't provide furnishing on this candidate -
        # that must not auto-reject it; only an outright MISMATCH does.
        normalized = {"bhk": 2, "furnishing": None}
        applied = {"bhk": 2, "furnishing": "semi_furnished"}
        self.assertTrue(sy._matches_safety_filter(normalized, applied))

    def test_no_requirements_always_passes(self):
        self.assertTrue(sy._matches_safety_filter({"bhk": 3}, {}))

    def test_normalized_sell_listing_passes_when_sell_requested(self):
        # The actual bug this follow-up fixes: a real Square Yards Sale
        # card, once correctly normalized to "sell" (not left as the
        # raw "sale" string), must survive this filter.
        normalized = {"listing_type": "sell", "bhk": 2}
        applied = {"listing_type": "sell", "bhk": 2}
        self.assertTrue(sy._matches_safety_filter(normalized, applied))

    def test_normalized_rent_listing_passes_when_rent_requested(self):
        normalized = {"listing_type": "rent", "bhk": 2}
        applied = {"listing_type": "rent", "bhk": 2}
        self.assertTrue(sy._matches_safety_filter(normalized, applied))

    def test_mismatched_listing_type_is_still_rejected(self):
        normalized = {"listing_type": "rent"}
        applied = {"listing_type": "sell"}
        self.assertFalse(sy._matches_safety_filter(normalized, applied))


# ============================================================
# is_enabled() / config (Phase 16)
# ============================================================

class IsEnabledTests(unittest.TestCase):

    def test_disabled_via_config_flag(self):
        self.assertFalse(sy.is_enabled({"SQUARE_YARDS_ENABLED": False}))

    def test_disabled_via_string_false(self):
        self.assertFalse(sy.is_enabled({"SQUARE_YARDS_ENABLED": "false"}))

    @patch.dict("sys.modules", {"mcp": None})
    def test_disabled_when_sdk_not_importable(self):
        # Simulates the `mcp` package being absent (ImportError path).
        self.assertFalse(sy.is_enabled({"SQUARE_YARDS_ENABLED": True}))


# ============================================================
# search_rental_properties() / get_listing_images() - MCP mocked
# (Phase 13: failure handling)
# ============================================================

class SearchRentalPropertiesTests(unittest.TestCase):
    """is_enabled() is patched True for the whole class EXCEPT the one
    test that specifically exercises its config-override disable path
    - otherwise every test here would vacuously pass with an empty
    result just because the real `mcp` SDK isn't installed in this
    test environment, without ever actually reaching the mocked
    _call_tool() path below it. (Caught by test_qualifying_listing_
    survives_the_safety_filter initially failing - the other "expect
    []" tests in this class were silently vacuous until this was
    added.)"""

    # Deliberately has NO "furnishing" key - that requirement triggers
    # a SEPARATE get_entity_details() resolution path (see
    # FurnishingResolutionTests below), which these tests are not
    # about and don't mock; adding it here would make every "expect a
    # survivor" test below also need a get_entity_details mock.
    APPLIED = {
        "listing_type": "rent", "area_or_city_text": "Chennai",
        "bhk": 2, "price": {"mongo": {"$lte": 30000}},
    }

    def setUp(self):
        self._enabled_patcher = patch(
            "services.external_property_sources.square_yards_service.is_enabled", return_value=True
        )
        self._enabled_patcher.start()
        self.addCleanup(self._enabled_patcher.stop)

    def test_returns_empty_list_when_disabled(self):
        self._enabled_patcher.stop()  # test the REAL is_enabled() gate for this one case
        results = sy.search_rental_properties(self.APPLIED, config={"SQUARE_YARDS_ENABLED": False})
        self.assertEqual(results, [])
        self._enabled_patcher.start()  # addCleanup will stop() again; start() keeps that balanced

    def test_returns_empty_list_when_filters_insufficient(self):
        results = sy.search_rental_properties({"listing_type": "rent"})
        self.assertEqual(results, [])

    @patch("services.external_property_sources.square_yards_service._call_tool")
    def test_mcp_failure_returns_empty_list_not_an_exception(self, mock_call):
        mock_call.return_value = None
        results = sy.search_rental_properties(self.APPLIED)
        self.assertEqual(results, [])
        mock_call.assert_called_once()

    @patch("services.external_property_sources.square_yards_service._call_tool")
    def test_malformed_response_returns_empty_list(self, mock_call):
        mock_call.return_value = {"ok": True}  # no "listings" key at all
        results = sy.search_rental_properties(self.APPLIED)
        self.assertEqual(results, [])
        mock_call.assert_called_once()

    @patch("services.external_property_sources.square_yards_service._call_tool")
    def test_zero_listings_returns_empty_list(self, mock_call):
        mock_call.return_value = {"listings": []}
        results = sy.search_rental_properties(self.APPLIED)
        self.assertEqual(results, [])
        mock_call.assert_called_once()

    @patch("services.external_property_sources.square_yards_service._call_tool")
    def test_qualifying_listing_survives_the_safety_filter(self, mock_call):
        mock_call.return_value = {"listings": [
            {"id": "1", "transactionType": "rent", "bhk": 2, "price": 24000, "url": "rental-a/1"},
            {"id": "2", "transactionType": "rent", "bhk": 1, "price": 24000, "url": "rental-b/2"},  # wrong BHK
            {"id": "3", "transactionType": "rent", "bhk": 2, "price": 99999, "url": "rental-c/3"},  # over budget
        ]}
        results = sy.search_rental_properties(self.APPLIED)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["external_id"], "1")
        self.assertEqual(results[0]["source"], "squareyards")

    @patch("services.external_property_sources.square_yards_service._call_tool")
    def test_results_respect_max_listings_cap(self, mock_call):
        mock_call.return_value = {"listings": [
            {"id": str(i), "transactionType": "rent", "bhk": 2, "price": 20000, "url": f"rental/{i}"}
            for i in range(20)
        ]}
        results = sy.search_rental_properties(self.APPLIED, max_listings=3)
        self.assertEqual(len(results), 3)  # 20 qualifying candidates exist - the cap must actually bind

    @patch("services.external_property_sources.square_yards_service._call_tool")
    def test_card_missing_id_is_skipped_not_crashed(self, mock_call):
        mock_call.return_value = {"listings": [{"transactionType": "rent", "bhk": 2, "price": 20000}]}
        results = sy.search_rental_properties(self.APPLIED)
        self.assertEqual(results, [])
        mock_call.assert_called_once()


class ResolveUnknownFurnishingTests(unittest.TestCase):
    """Direct unit tests for _resolve_unknown_furnishing() - the fix
    ensuring a Square Yards listing is never treated as a CONFIRMED
    match for an explicit furnishing requirement while its furnishing
    is still unknown (search cards never carry it - only
    get_entity_details does)."""

    APPLIED = {"furnishing": "semi_furnished"}

    def test_already_known_furnishing_is_not_rechecked(self):
        candidate = {"external_id": "1", "furnishing": "semi_furnished"}
        with patch(
            "services.external_property_sources.square_yards_service.get_listing_details"
        ) as mock_details:
            result = sy._resolve_unknown_furnishing([candidate], self.APPLIED)
        mock_details.assert_not_called()  # already available - no "unnecessary" detail call
        self.assertEqual(result, [candidate])

    @patch("services.external_property_sources.square_yards_service.get_listing_details")
    def test_unknown_furnishing_resolved_and_matches_is_kept(self, mock_details):
        mock_details.return_value = {"furnishing": "semi_furnished", "images": []}
        candidate = {"external_id": "1", "furnishing": None, "images": []}

        result = sy._resolve_unknown_furnishing([candidate], self.APPLIED)

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["furnishing"], "semi_furnished")
        mock_details.assert_called_once_with("1", config=None)

    @patch("services.external_property_sources.square_yards_service.get_listing_details")
    def test_unknown_furnishing_resolved_but_does_not_match_is_dropped(self, mock_details):
        mock_details.return_value = {"furnishing": "unfurnished", "images": []}
        candidate = {"external_id": "1", "furnishing": None}

        result = sy._resolve_unknown_furnishing([candidate], self.APPLIED)

        self.assertEqual(result, [])

    @patch("services.external_property_sources.square_yards_service.get_listing_details")
    def test_details_call_failure_drops_candidate_not_kept_just_in_case(self, mock_details):
        mock_details.return_value = None
        candidate = {"external_id": "1", "furnishing": None}

        result = sy._resolve_unknown_furnishing([candidate], self.APPLIED)

        self.assertEqual(result, [])

    @patch("services.external_property_sources.square_yards_service.get_listing_details")
    def test_details_call_succeeds_but_still_has_no_furnishing_drops_candidate(self, mock_details):
        mock_details.return_value = {"furnishing": None, "images": []}
        candidate = {"external_id": "1", "furnishing": None}

        result = sy._resolve_unknown_furnishing([candidate], self.APPLIED)

        self.assertEqual(result, [])

    @patch("services.external_property_sources.square_yards_service.get_listing_details")
    def test_fuller_image_list_from_details_is_merged_in(self, mock_details):
        mock_details.return_value = {
            "furnishing": "semi_furnished",
            "images": ["https://img.squareyards.com/a.jpg", "https://img.squareyards.com/b.jpg"],
        }
        candidate = {"external_id": "1", "furnishing": None, "images": []}

        result = sy._resolve_unknown_furnishing([candidate], self.APPLIED)

        self.assertEqual(len(result[0]["images"]), 2)

    @patch("services.external_property_sources.square_yards_service.get_listing_details")
    def test_existing_search_card_image_is_not_overwritten(self, mock_details):
        mock_details.return_value = {
            "furnishing": "semi_furnished",
            "images": ["https://img.squareyards.com/from-detail.jpg"],
        }
        candidate = {"external_id": "1", "furnishing": None, "images": ["https://img.squareyards.com/from-card.jpg"]}

        result = sy._resolve_unknown_furnishing([candidate], self.APPLIED)

        self.assertEqual(result[0]["images"], ["https://img.squareyards.com/from-card.jpg"])

    def test_other_fields_still_enforced_after_furnishing_resolves(self):
        """Merging furnishing back in re-runs the FULL safety filter,
        not just the furnishing check - a candidate that fails on
        price/bhk after merging must still be dropped."""
        applied = {"furnishing": "semi_furnished", "bhk": 2}
        candidate = {"external_id": "1", "furnishing": None, "bhk": 3}  # wrong BHK regardless of furnishing

        with patch(
            "services.external_property_sources.square_yards_service.get_listing_details",
            return_value={"furnishing": "semi_furnished", "images": []},
        ):
            result = sy._resolve_unknown_furnishing([candidate], applied)

        self.assertEqual(result, [])


class SearchRentalPropertiesFurnishingIntegrationTests(unittest.TestCase):
    """End-to-end tests through search_rental_properties() itself,
    with a tool-name-aware _call_tool mock (search_properties vs
    get_entity_details) - proves the real wiring, not just the helper
    function in isolation above."""

    def setUp(self):
        self._enabled_patcher = patch(
            "services.external_property_sources.square_yards_service.is_enabled", return_value=True
        )
        self._enabled_patcher.start()
        self.addCleanup(self._enabled_patcher.stop)

    def _mock_call_tool(self, search_response, detail_responses):
        def side_effect(tool_name, arguments, config=None):
            if tool_name == "search_properties":
                return search_response
            if tool_name == "get_entity_details":
                return detail_responses.get(arguments.get("id"))
            return None
        return side_effect

    def test_furnishing_requirement_triggers_exactly_one_detail_call_for_the_survivor(self):
        applied = {
            "listing_type": "rent", "area_or_city_text": "Chennai",
            "bhk": 2, "furnishing": "semi_furnished",
        }
        search_response = {"listings": [
            {"id": "1", "transactionType": "rent", "bhk": 2, "price": 24000, "url": "rental-a/1"},
        ]}
        detail_responses = {
            "1": {"detail": {"listingData": {
                "propertyId": 1, "unitType": "2 BHK", "totalPrice": "24000",
                "attributes": {"Furnishing Status": "Semi-Furnished"}, "images": [],
            }}},
        }

        with patch(
            "services.external_property_sources.square_yards_service._call_tool",
            side_effect=self._mock_call_tool(search_response, detail_responses),
        ) as mock_call:
            results = sy.search_rental_properties(applied)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["furnishing"], "semi_furnished")
        # exactly 2 calls total: one search_properties, one get_entity_details
        self.assertEqual(mock_call.call_count, 2)

    def test_furnishing_mismatch_after_detail_call_excludes_the_listing(self):
        applied = {
            "listing_type": "rent", "area_or_city_text": "Chennai",
            "bhk": 2, "furnishing": "semi_furnished",
        }
        search_response = {"listings": [
            {"id": "1", "transactionType": "rent", "bhk": 2, "price": 24000, "url": "rental-a/1"},
        ]}
        detail_responses = {
            "1": {"detail": {"listingData": {
                "propertyId": 1, "unitType": "2 BHK", "totalPrice": "24000",
                "attributes": {"Furnishing Status": "Unfurnished"}, "images": [],
            }}},
        }

        with patch(
            "services.external_property_sources.square_yards_service._call_tool",
            side_effect=self._mock_call_tool(search_response, detail_responses),
        ):
            results = sy.search_rental_properties(applied)

        self.assertEqual(results, [])

    def test_no_furnishing_requirement_never_calls_get_entity_details(self):
        """'Do not make unnecessary detail calls for fields already
        available' - no furnishing requirement at all means no detail
        call for furnishing's sake."""
        applied = {"listing_type": "rent", "area_or_city_text": "Chennai", "bhk": 2}
        search_response = {"listings": [
            {"id": "1", "transactionType": "rent", "bhk": 2, "price": 24000, "url": "rental-a/1"},
        ]}

        with patch(
            "services.external_property_sources.square_yards_service._call_tool",
            side_effect=self._mock_call_tool(search_response, {}),
        ) as mock_call:
            results = sy.search_rental_properties(applied)

        self.assertEqual(len(results), 1)
        self.assertEqual(mock_call.call_count, 1)  # search_properties only

    def test_details_failure_during_furnishing_resolution_excludes_the_listing(self):
        applied = {
            "listing_type": "rent", "area_or_city_text": "Chennai",
            "bhk": 2, "furnishing": "semi_furnished",
        }
        search_response = {"listings": [
            {"id": "1", "transactionType": "rent", "bhk": 2, "price": 24000, "url": "rental-a/1"},
        ]}

        with patch(
            "services.external_property_sources.square_yards_service._call_tool",
            side_effect=self._mock_call_tool(search_response, {}),  # "1" -> no detail entry -> None
        ):
            results = sy.search_rental_properties(applied)

        self.assertEqual(results, [])


class GetListingImagesTests(unittest.TestCase):

    def test_uses_search_card_image_when_enough_already(self):
        normalized = {"external_id": "1", "images": ["https://img.squareyards.com/a.jpg"]}
        images = sy.get_listing_images(normalized, max_images=1)
        self.assertEqual(images, ["https://img.squareyards.com/a.jpg"])

    @patch("services.external_property_sources.square_yards_service.get_listing_details")
    def test_falls_back_to_details_call_for_more_images(self, mock_details):
        mock_details.return_value = {"images": ["https://img.squareyards.com/a.jpg", "https://img.squareyards.com/b.jpg"]}
        normalized = {"external_id": "1", "images": []}
        images = sy.get_listing_images(normalized, max_images=2)
        self.assertEqual(len(images), 2)
        mock_details.assert_called_once()

    @patch("services.external_property_sources.square_yards_service.get_listing_details")
    def test_details_failure_falls_back_to_whatever_search_card_had(self, mock_details):
        mock_details.return_value = None
        normalized = {"external_id": "1", "images": ["https://img.squareyards.com/a.jpg"]}
        images = sy.get_listing_images(normalized, max_images=3)
        self.assertEqual(images, ["https://img.squareyards.com/a.jpg"])


class GetListingDetailsTests(unittest.TestCase):

    def test_returns_none_without_external_id(self):
        self.assertIsNone(sy.get_listing_details(None))
        self.assertIsNone(sy.get_listing_details(""))

    @patch("services.external_property_sources.square_yards_service.is_enabled", return_value=True)
    @patch("services.external_property_sources.square_yards_service._call_tool")
    def test_mcp_failure_returns_none(self, mock_call, mock_enabled):
        mock_call.return_value = None
        self.assertIsNone(sy.get_listing_details("10681304"))
        mock_call.assert_called_once()  # proves the mocked failure path was actually reached


# ============================================================
# fetch_listing_image_bytes() (Phase 6/13)
# ============================================================

class FetchListingImageBytesTests(unittest.TestCase):

    def test_none_url_returns_none(self):
        self.assertIsNone(sy.fetch_listing_image_bytes(None))
        self.assertIsNone(sy.fetch_listing_image_bytes(""))

    @patch("services.external_property_sources.square_yards_service.requests.get")
    def test_successful_download_returns_bytes(self, mock_get):
        mock_response = mock_get.return_value
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.iter_content.return_value = [b"fake", b"image", b"bytes"]
        mock_response.raise_for_status.return_value = None

        result = sy.fetch_listing_image_bytes("https://img.squareyards.com/x.jpg")
        self.assertEqual(result, b"fakeimagebytes")

    @patch("services.external_property_sources.square_yards_service.requests.get")
    def test_non_image_content_type_is_rejected(self, mock_get):
        mock_response = mock_get.return_value
        mock_response.headers = {"Content-Type": "text/html"}
        mock_response.raise_for_status.return_value = None

        result = sy.fetch_listing_image_bytes("https://img.squareyards.com/x.jpg")
        self.assertIsNone(result)

    @patch("services.external_property_sources.square_yards_service.requests.get")
    def test_oversized_image_is_rejected(self, mock_get):
        mock_response = mock_get.return_value
        mock_response.headers = {"Content-Type": "image/jpeg"}
        mock_response.raise_for_status.return_value = None
        big_chunk = b"x" * (sy.MAX_IMAGE_DOWNLOAD_BYTES + 1)
        mock_response.iter_content.return_value = [big_chunk]

        result = sy.fetch_listing_image_bytes("https://img.squareyards.com/x.jpg")
        self.assertIsNone(result)

    @patch("services.external_property_sources.square_yards_service.requests.get")
    def test_network_error_returns_none_not_an_exception(self, mock_get):
        import requests
        mock_get.side_effect = requests.ConnectionError("boom")

        result = sy.fetch_listing_image_bytes("https://img.squareyards.com/x.jpg")
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
