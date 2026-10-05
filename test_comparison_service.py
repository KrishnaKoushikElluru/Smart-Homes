"""
Tests for services/comparison_service.py - the pure, stateless
Property Comparison + rating engine. No database, no network, no MCP
anywhere in this file - every fixture is a plain dict shaped exactly
like a REAL SmartHomes property document (see routes/property_routes.py's
submit_listing() "BUILD MONGODB DOCUMENT" section) or a REAL Square
Yards normalized listing dict (see services/external_property_sources/
square_yards_service.py's normalize_listing_detail()).
"""

import copy
import unittest

from services.comparison_service import (
    BASE_WEIGHTS,
    compare_properties,
    compute_ratings,
    smarthomes_property_to_row,
    square_yards_listing_to_row,
)


# ============================================================
# FIXTURES
# ============================================================

def make_smarthomes_document(**overrides):
    document = {
        "listing": {
            "type": "rent",
            "status": "active",
            "price": 25000,
            "currency": "INR",
            "title": "Spacious 2BHK near tech park",
        },
        "property": {
            "type": "apartment",
            "bhk": "2",
            "area_sqft": 1100,
            "bathrooms": 2,
            "balconies": 1,
            "furnishing": "semi_furnished",
            "facing": "east",
            "floor_number": 3,
            "total_floors": 8,
        },
        "rooms": {},
        "area": {},
        "building": {
            "lift": True,
            "power_backup": True,
            "security": True,
            "cctv": False,
        },
        "project": {},
        "parking": {
            "covered_parking": True,
            "open_parking": False,
        },
        "type_details": {},
        "legal": {},
        "pg_details": {},
        "amenities": {"building": ["lift", "power_backup", "security"], "custom": []},
        "features": ["lift", "power_backup", "security"],
        "rental": {"available_from": "2026-01-01"},
        "sale": {},
        "location": {
            "address": "123 Tech Park Road",
            "city": "Chennai",
            "locality": "Velachery",
            "coordinates": {"type": "Point", "coordinates": [80.22, 12.98]},
        },
        "media": {"images": ["abc123.jpg"]},
        "nearby_facilities": [
            {"name": "City Gym", "category": "gym", "address": None, "distance_m": 300},
            {"name": "Apollo Pharmacy", "category": "pharmacy", "address": None, "distance_m": 150},
        ],
        "nearby_facilities_metadata": {"status": "completed"},
        "source": {"type": "owner", "url": None},
    }
    document.update(overrides)
    return document


def make_square_yards_listing(**overrides):
    normalized = {
        "source": "squareyards",
        "external_id": "SY12345",
        "title": "3BHK Apartment in OMR",
        "listing_type": "rent",
        "price": 32000,
        "price_on_request": False,
        "bhk": "3",
        "area_sqft": 1400,
        "property_type": "Apartment",
        "furnishing": "fully_furnished",
        "amenities": ["Gym", "Swimming Pool", "Clubhouse", "Power Backup"],
        "locality": "OMR",
        "city": "Chennai",
        "images": ["https://cdn.squareyards.com/img1.jpg"],
        "source_url": "https://www.squareyards.com/listing/SY12345",
    }
    normalized.update(overrides)
    return normalized


def make_entry(provider, item_id, raw):
    if provider == "smarthomes":
        row = smarthomes_property_to_row(item_id, raw)
    else:
        row = square_yards_listing_to_row(raw)
    return {"provider": provider, "id": item_id, "row": row, "raw": raw}


# ============================================================
# 1. SMARTHOMES NORMALIZATION
# ============================================================

class SmartHomesNormalizationTests(unittest.TestCase):

    def test_real_fields_are_preserved(self):
        document = make_smarthomes_document()
        row = smarthomes_property_to_row("prop123", document)

        self.assertEqual(row["provider"], "smarthomes")
        self.assertEqual(row["id"], "prop123")
        self.assertEqual(row["price"], 25000)
        self.assertEqual(row["bhk"], "2")
        self.assertEqual(row["area_sqft"], 1100)
        self.assertEqual(row["city"], "Chennai")
        self.assertEqual(row["locality"], "Velachery")
        self.assertEqual(row["furnishing"], "semi_furnished")
        self.assertEqual(row["bathrooms"], 2)
        self.assertEqual(row["balconies"], 1)
        self.assertEqual(row["floor_number"], 3)
        self.assertEqual(row["facing"], "east")
        self.assertEqual(row["status"], "active")
        self.assertEqual(row["coordinates"], [80.22, 12.98])
        self.assertEqual(row["detail_url"], "/property/prop123")
        self.assertEqual(row["image_url"], "/static/images/properties/abc123.jpg")

    def test_amenities_flattened_from_features(self):
        document = make_smarthomes_document()
        row = smarthomes_property_to_row("prop123", document)
        self.assertEqual(row["amenities_flat"], ["lift", "power_backup", "security"])

    def test_price_on_request_always_false(self):
        document = make_smarthomes_document()
        row = smarthomes_property_to_row("prop123", document)
        self.assertFalse(row["price_on_request"])

    def test_nearby_facilities_preserved_when_enrichment_completed(self):
        document = make_smarthomes_document()
        row = smarthomes_property_to_row("prop123", document)
        self.assertEqual(len(row["nearby_facilities"]), 2)

    def test_nearby_facilities_none_when_enrichment_pending(self):
        document = make_smarthomes_document(
            nearby_facilities=[],
            nearby_facilities_metadata={"status": "pending"},
        )
        row = smarthomes_property_to_row("prop123", document)
        self.assertIsNone(row["nearby_facilities"])

    def test_nearby_facilities_none_when_enrichment_failed(self):
        document = make_smarthomes_document(
            nearby_facilities=[],
            nearby_facilities_metadata={"status": "failed"},
        )
        row = smarthomes_property_to_row("prop123", document)
        self.assertIsNone(row["nearby_facilities"])

    def test_nearby_facilities_none_when_enrichment_skipped(self):
        # STATUS_SKIPPED - "no valid coordinates to enrich from" (see
        # services/nearby_facility_service.py's
        # enrich_property_nearby_facilities() docstring: distinct from
        # "failed", but equally untrustworthy as a facility signal).
        document = make_smarthomes_document(
            nearby_facilities=[],
            nearby_facilities_metadata={"status": "skipped"},
        )
        row = smarthomes_property_to_row("prop123", document)
        self.assertIsNone(row["nearby_facilities"])

    def test_nearby_facilities_none_when_metadata_missing_entirely(self):
        # A property registered before this feature existed, or never
        # enriched at all - no nearby_facilities_metadata key at all.
        document = make_smarthomes_document()
        del document["nearby_facilities_metadata"]
        row = smarthomes_property_to_row("prop123", document)
        self.assertIsNone(row["nearby_facilities"])

    def test_nearby_facilities_preserved_when_enrichment_partial(self):
        # STATUS_PARTIAL - some categories succeeded, some failed; the
        # categories that DID succeed are real, genuine data and must
        # still count (services/nearby_facility_service.py's own
        # build_nearby_facilities_display() groups "whatever was
        # actually stored" for a partial run, by the same reasoning).
        document = make_smarthomes_document(
            nearby_facilities=[
                {"name": "City Gym", "category": "gym", "address": None, "distance_m": 300},
            ],
            nearby_facilities_metadata={"status": "partial"},
        )
        row = smarthomes_property_to_row("prop123", document)
        self.assertEqual(len(row["nearby_facilities"]), 1)

    def test_nearby_facilities_empty_list_when_completed_with_zero_found(self):
        document = make_smarthomes_document(
            nearby_facilities=[],
            nearby_facilities_metadata={"status": "completed"},
        )
        row = smarthomes_property_to_row("prop123", document)
        self.assertEqual(row["nearby_facilities"], [])

    def test_available_from_and_possession_status_read_from_rental_and_sale(self):
        document = make_smarthomes_document()
        row = smarthomes_property_to_row("prop123", document)
        self.assertEqual(row["available_from"], "2026-01-01")

        sale_document = make_smarthomes_document(
            listing={"type": "sell", "status": "active", "price": 5000000, "title": "Villa"},
            sale={"possession_status": "ready_to_move"},
            rental={},
        )
        sale_row = smarthomes_property_to_row("prop456", sale_document)
        self.assertEqual(sale_row["possession_status"], "ready_to_move")

    def test_missing_image_is_none(self):
        document = make_smarthomes_document(media={"images": []})
        row = smarthomes_property_to_row("prop123", document)
        self.assertIsNone(row["image_url"])


# ============================================================
# 2. SQUARE YARDS NORMALIZATION
# ============================================================

class SquareYardsNormalizationTests(unittest.TestCase):

    def test_real_fields_are_preserved(self):
        normalized = make_square_yards_listing()
        row = square_yards_listing_to_row(normalized)

        self.assertEqual(row["provider"], "squareyards")
        self.assertEqual(row["id"], "SY12345")
        self.assertEqual(row["price"], 32000)
        self.assertEqual(row["bhk"], "3")
        self.assertEqual(row["area_sqft"], 1400)
        self.assertEqual(row["city"], "Chennai")
        self.assertEqual(row["locality"], "OMR")
        self.assertEqual(row["furnishing"], "fully_furnished")
        self.assertEqual(row["amenities_flat"], ["Gym", "Swimming Pool", "Clubhouse", "Power Backup"])
        self.assertEqual(row["image_url"], "https://cdn.squareyards.com/img1.jpg")
        self.assertEqual(row["detail_url"], "https://www.squareyards.com/listing/SY12345")

    def test_unavailable_fields_are_explicitly_none_never_invented(self):
        normalized = make_square_yards_listing()
        row = square_yards_listing_to_row(normalized)

        self.assertIsNone(row["bathrooms"])
        self.assertIsNone(row["balconies"])
        self.assertIsNone(row["floor_number"])
        self.assertIsNone(row["facing"])
        self.assertIsNone(row["status"])
        self.assertIsNone(row["available_from"])
        self.assertIsNone(row["possession_status"])
        self.assertIsNone(row["nearby_facilities"])
        self.assertIsNone(row["coordinates"])

    def test_price_on_request_passthrough(self):
        normalized = make_square_yards_listing(price=None, price_on_request=True)
        row = square_yards_listing_to_row(normalized)
        self.assertTrue(row["price_on_request"])
        self.assertIsNone(row["price"])

    def test_missing_image_is_none(self):
        normalized = make_square_yards_listing(images=[])
        row = square_yards_listing_to_row(normalized)
        self.assertIsNone(row["image_url"])


# ============================================================
# 3. MIXED-SOURCE NORMALIZATION
# ============================================================

class MixedSourceNormalizationTests(unittest.TestCase):

    def test_both_sources_produce_the_same_row_shape(self):
        sh_row = smarthomes_property_to_row("p1", make_smarthomes_document())
        sy_row = square_yards_listing_to_row(make_square_yards_listing())
        self.assertEqual(set(sh_row.keys()), set(sy_row.keys()))

    def test_mixed_entries_can_be_compared_together(self):
        entries = [
            make_entry("smarthomes", "p1", make_smarthomes_document()),
            make_entry("squareyards", "SY12345", make_square_yards_listing()),
        ]
        results = compare_properties(entries)
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["row"]["provider"], "smarthomes")
        self.assertEqual(results[1]["row"]["provider"], "squareyards")


# ============================================================
# 4 & 5. PRICE / VALUE SCORING + PRICE ON REQUEST
# ============================================================

class PriceValueScoringTests(unittest.TestCase):

    def test_cheaper_price_per_bhk_scores_higher(self):
        cheap = make_entry("smarthomes", "cheap", make_smarthomes_document(
            listing={"type": "rent", "status": "active", "price": 10000, "title": "Cheap"}
        ))
        expensive = make_entry("smarthomes", "expensive", make_smarthomes_document(
            listing={"type": "rent", "status": "active", "price": 30000, "title": "Expensive"}
        ))
        entries = [cheap, expensive]

        cheap_rating = compute_ratings(cheap, entries)
        expensive_rating = compute_ratings(expensive, entries)

        cheap_score = cheap_rating["categories"]["price_value"]["score"]
        expensive_score = expensive_rating["categories"]["price_value"]["score"]

        self.assertGreater(cheap_score, expensive_score)
        self.assertEqual(cheap_score, 100.0)
        self.assertEqual(expensive_score, 0.0)

    def test_price_on_request_is_unavailable_not_zero(self):
        on_request = make_entry("squareyards", "SY1", make_square_yards_listing(
            price=None, price_on_request=True
        ))
        normal = make_entry("squareyards", "SY2", make_square_yards_listing(price=20000))
        entries = [on_request, normal]

        result = compute_ratings(on_request, entries)["categories"]["price_value"]
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["score"])

    def test_missing_price_is_unavailable_not_zero(self):
        document = make_smarthomes_document()
        document["listing"] = dict(document["listing"])
        document["listing"]["price"] = None
        entry = make_entry("smarthomes", "p1", document)
        other = make_entry("smarthomes", "p2", make_smarthomes_document())

        result = compute_ratings(entry, [entry, other])["categories"]["price_value"]
        self.assertEqual(result["status"], "unavailable")

    def test_falls_back_to_price_per_sqft_when_bhk_missing(self):
        document = make_smarthomes_document()
        document["property"] = dict(document["property"])
        document["property"]["bhk"] = None
        entry = make_entry("smarthomes", "p1", document)
        other = make_entry("smarthomes", "p2", make_smarthomes_document())

        result = compute_ratings(entry, [entry, other])["categories"]["price_value"]
        self.assertEqual(result["status"], "valid")
        self.assertIn("sq.ft", result["reason"])

    def test_falls_back_to_raw_price_when_bhk_and_area_missing(self):
        document = make_smarthomes_document()
        document["property"] = dict(document["property"])
        document["property"]["bhk"] = None
        document["property"]["area_sqft"] = None
        entry = make_entry("smarthomes", "p1", document)
        other = make_entry("smarthomes", "p2", make_smarthomes_document())

        result = compute_ratings(entry, [entry, other])["categories"]["price_value"]
        self.assertEqual(result["status"], "valid")

    def test_equal_costs_all_score_100(self):
        a = make_entry("smarthomes", "a", make_smarthomes_document())
        b = make_entry("smarthomes", "b", make_smarthomes_document())
        entries = [a, b]

        for entry in entries:
            result = compute_ratings(entry, entries)["categories"]["price_value"]
            self.assertEqual(result["score"], 100.0)


# ============================================================
# 6. FACILITIES / AMENITIES SCORING
# ============================================================

class FacilitiesScoringTests(unittest.TestCase):

    def test_more_amenities_scores_higher(self):
        few = make_entry("smarthomes", "few", make_smarthomes_document(
            features=["lift"]
        ))
        many = make_entry("smarthomes", "many", make_smarthomes_document(
            features=["lift", "power_backup", "security", "gym", "pool"]
        ))
        entries = [few, many]

        few_score = compute_ratings(few, entries)["categories"]["facilities"]["score"]
        many_score = compute_ratings(many, entries)["categories"]["facilities"]["score"]

        self.assertEqual(many_score, 100.0)
        self.assertLess(few_score, many_score)

    def test_explicitly_empty_amenities_scores_zero_not_unavailable(self):
        entry = make_entry("smarthomes", "p1", make_smarthomes_document(features=[]))
        other = make_entry("smarthomes", "p2", make_smarthomes_document(features=["lift"]))

        result = compute_ratings(entry, [entry, other])["categories"]["facilities"]
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["score"], 0.0)

    def test_missing_amenities_data_is_unavailable(self):
        document = make_smarthomes_document()
        del document["features"]
        entry = make_entry("smarthomes", "p1", document)
        other = make_entry("smarthomes", "p2", make_smarthomes_document())

        result = compute_ratings(entry, [entry, other])["categories"]["facilities"]
        self.assertEqual(result["status"], "unavailable")

    def test_works_for_square_yards_too(self):
        entry = make_entry("squareyards", "SY1", make_square_yards_listing(
            amenities=["Gym", "Pool"]
        ))
        other = make_entry("squareyards", "SY2", make_square_yards_listing(
            amenities=["Gym", "Pool", "Clubhouse", "Gym2"]
        ))
        result = compute_ratings(entry, [entry, other])["categories"]["facilities"]
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["score"], 50.0)


# ============================================================
# 7. LOCATION SCORING
# ============================================================

class LocationScoringTests(unittest.TestCase):

    def test_smarthomes_uses_nearby_facilities_as_a_signal(self):
        with_facilities = make_entry("smarthomes", "p1", make_smarthomes_document())
        without_facilities = make_entry("smarthomes", "p2", make_smarthomes_document(
            nearby_facilities=[], nearby_facilities_metadata={"status": "completed"}
        ))
        entries = [with_facilities, without_facilities]

        score_with = compute_ratings(with_facilities, entries)["categories"]["location"]["score"]
        score_without = compute_ratings(without_facilities, entries)["categories"]["location"]["score"]

        self.assertGreater(score_with, score_without)

    def test_square_yards_uses_city_locality_only(self):
        entry = make_entry("squareyards", "SY1", make_square_yards_listing())
        result = compute_ratings(entry, [entry])["categories"]["location"]
        self.assertEqual(result["status"], "valid")
        self.assertIn("city/locality", result["reason"])

    def test_missing_city_is_unavailable(self):
        document = make_smarthomes_document()
        document["location"] = dict(document["location"])
        document["location"]["city"] = None
        entry = make_entry("smarthomes", "p1", document)

        result = compute_ratings(entry, [entry])["categories"]["location"]
        self.assertEqual(result["status"], "unavailable")

    def test_never_invents_square_yards_coordinates_or_facilities(self):
        entry = make_entry("squareyards", "SY1", make_square_yards_listing())
        self.assertIsNone(entry["row"]["coordinates"])
        self.assertIsNone(entry["row"]["nearby_facilities"])

    def test_pending_enrichment_falls_back_to_completeness_only_not_zero(self):
        document = make_smarthomes_document(
            nearby_facilities=[], nearby_facilities_metadata={"status": "pending"}
        )
        entry = make_entry("smarthomes", "p1", document)
        result = compute_ratings(entry, [entry])["categories"]["location"]
        # Still valid (city/locality alone is enough) - "pending" must
        # not silently zero out the whole category, only the
        # facility-count component of it.
        self.assertEqual(result["status"], "valid")
        self.assertIn("not yet available", result["reason"])

    def test_failed_enrichment_falls_back_to_completeness_only_not_zero(self):
        document = make_smarthomes_document(
            nearby_facilities=[], nearby_facilities_metadata={"status": "failed"}
        )
        entry = make_entry("smarthomes", "p1", document)
        result = compute_ratings(entry, [entry])["categories"]["location"]
        self.assertEqual(result["status"], "valid")
        self.assertIn("not yet available", result["reason"])

    def test_skipped_enrichment_falls_back_to_completeness_only_not_zero(self):
        document = make_smarthomes_document(
            nearby_facilities=[], nearby_facilities_metadata={"status": "skipped"}
        )
        entry = make_entry("smarthomes", "p1", document)
        result = compute_ratings(entry, [entry])["categories"]["location"]
        self.assertEqual(result["status"], "valid")
        self.assertIn("not yet available", result["reason"])

    def test_genuinely_zero_facilities_distinguishable_from_not_yet_enriched(self):
        """A completed enrichment that found zero facilities must score
        DIFFERENTLY (lower, but still a real signal) than a property
        that hasn't been enriched at all - both must not collapse to
        the same 'ignore nearby facilities entirely' behavior."""
        zero_found = make_entry("smarthomes", "p1", make_smarthomes_document(
            nearby_facilities=[], nearby_facilities_metadata={"status": "completed"}
        ))
        not_enriched = make_entry("smarthomes", "p2", make_smarthomes_document(
            nearby_facilities=[], nearby_facilities_metadata={"status": "pending"}
        ))
        entries = [zero_found, not_enriched]

        zero_found_result = compute_ratings(zero_found, entries)["categories"]["location"]
        not_enriched_result = compute_ratings(not_enriched, entries)["categories"]["location"]

        self.assertIn("nearby facilities", zero_found_result["reason"])
        self.assertIn("not yet available", not_enriched_result["reason"])
        self.assertNotEqual(zero_found_result["reason"], not_enriched_result["reason"])


# ============================================================
# 8. AVAILABILITY SCORING
# ============================================================

class AvailabilityScoringTests(unittest.TestCase):

    def test_active_with_no_date_scores_well(self):
        document = make_smarthomes_document(rental={})
        entry = make_entry("smarthomes", "p1", document)
        result = compute_ratings(entry, [entry])["categories"]["availability"]
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["score"], 90.0)

    def test_active_available_in_the_past_scores_highest(self):
        document = make_smarthomes_document(rental={"available_from": "2020-01-01"})
        entry = make_entry("smarthomes", "p1", document)
        result = compute_ratings(entry, [entry])["categories"]["availability"]
        self.assertEqual(result["score"], 100.0)

    def test_active_available_in_the_future_scores_partial(self):
        document = make_smarthomes_document(rental={"available_from": "2099-01-01"})
        entry = make_entry("smarthomes", "p1", document)
        result = compute_ratings(entry, [entry])["categories"]["availability"]
        self.assertEqual(result["score"], 60.0)

    def test_inactive_listing_scores_low_but_not_unavailable(self):
        document = make_smarthomes_document(
            listing={"type": "rent", "status": "inactive", "price": 25000, "title": "x"}
        )
        entry = make_entry("smarthomes", "p1", document)
        result = compute_ratings(entry, [entry])["categories"]["availability"]
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["score"], 10.0)

    def test_ready_to_move_sale_scores_highest(self):
        document = make_smarthomes_document(
            listing={"type": "sell", "status": "active", "price": 5000000, "title": "x"},
            sale={"possession_status": "ready_to_move"},
            rental={},
        )
        entry = make_entry("smarthomes", "p1", document)
        result = compute_ratings(entry, [entry])["categories"]["availability"]
        self.assertEqual(result["score"], 100.0)

    def test_square_yards_always_unavailable(self):
        entry = make_entry("squareyards", "SY1", make_square_yards_listing())
        result = compute_ratings(entry, [entry])["categories"]["availability"]
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["score"])

    def test_square_yards_never_scored_as_worst(self):
        """The literal regression guard this phase's instructions called
        out by name: no availability info must never become a 0."""
        entry = make_entry("squareyards", "SY1", make_square_yards_listing())
        result = compute_ratings(entry, [entry])["categories"]["availability"]
        self.assertNotEqual(result["score"], 0.0)
        self.assertIsNone(result["score"])


# ============================================================
# 9. CONNECTIVITY SCORING
# ============================================================

class ConnectivityScoringTests(unittest.TestCase):

    def test_more_distinct_categories_scores_higher(self):
        diverse = make_entry("smarthomes", "p1", make_smarthomes_document(nearby_facilities=[
            {"name": "A", "category": "gym", "distance_m": 100},
            {"name": "B", "category": "school", "distance_m": 200},
            {"name": "C", "category": "hospital", "distance_m": 300},
        ]))
        narrow = make_entry("smarthomes", "p2", make_smarthomes_document(nearby_facilities=[
            {"name": "D", "category": "gym", "distance_m": 50},
            {"name": "E", "category": "gym", "distance_m": 60},
        ]))
        entries = [diverse, narrow]

        diverse_score = compute_ratings(diverse, entries)["categories"]["connectivity"]["score"]
        narrow_score = compute_ratings(narrow, entries)["categories"]["connectivity"]["score"]

        self.assertEqual(diverse_score, 100.0)
        self.assertLess(narrow_score, diverse_score)

    def test_duplicate_category_facilities_do_not_inflate_score(self):
        five_gyms = make_entry("smarthomes", "p1", make_smarthomes_document(nearby_facilities=[
            {"name": "Gym %d" % i, "category": "gym", "distance_m": 100 + i} for i in range(5)
        ]))
        one_each = make_entry("smarthomes", "p2", make_smarthomes_document(nearby_facilities=[
            {"name": "Gym", "category": "gym", "distance_m": 100},
            {"name": "School", "category": "school", "distance_m": 200},
        ]))
        entries = [five_gyms, one_each]

        five_gyms_score = compute_ratings(five_gyms, entries)["categories"]["connectivity"]["score"]
        one_each_score = compute_ratings(one_each, entries)["categories"]["connectivity"]["score"]

        self.assertLess(five_gyms_score, one_each_score)

    def test_square_yards_always_unavailable(self):
        entry = make_entry("squareyards", "SY1", make_square_yards_listing())
        result = compute_ratings(entry, [entry])["categories"]["connectivity"]
        self.assertEqual(result["status"], "unavailable")

    def test_pending_enrichment_is_unavailable_not_zero(self):
        document = make_smarthomes_document(
            nearby_facilities=[], nearby_facilities_metadata={"status": "pending"}
        )
        entry = make_entry("smarthomes", "p1", document)
        result = compute_ratings(entry, [entry])["categories"]["connectivity"]
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["score"])

    def test_failed_enrichment_is_unavailable_not_zero(self):
        document = make_smarthomes_document(
            nearby_facilities=[], nearby_facilities_metadata={"status": "failed"}
        )
        entry = make_entry("smarthomes", "p1", document)
        result = compute_ratings(entry, [entry])["categories"]["connectivity"]
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["score"])

    def test_skipped_enrichment_is_unavailable_not_zero(self):
        document = make_smarthomes_document(
            nearby_facilities=[], nearby_facilities_metadata={"status": "skipped"}
        )
        entry = make_entry("smarthomes", "p1", document)
        result = compute_ratings(entry, [entry])["categories"]["connectivity"]
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["score"])

    def test_genuinely_zero_facilities_scores_zero_not_unavailable(self):
        """Distinguishes 'enrichment completed, nothing found nearby'
        (a real, valid 0) from 'enrichment hasn't happened'
        (unavailable) - these must never collapse into the same
        result."""
        document = make_smarthomes_document(
            nearby_facilities=[], nearby_facilities_metadata={"status": "completed"}
        )
        entry = make_entry("smarthomes", "p1", document)
        result = compute_ratings(entry, [entry])["categories"]["connectivity"]
        self.assertEqual(result["status"], "valid")
        self.assertEqual(result["score"], 0.0)

    def test_square_yards_has_no_nearby_facility_field_at_all(self):
        entry = make_entry("squareyards", "SY1", make_square_yards_listing())
        self.assertIsNone(entry["row"]["nearby_facilities"])
        result = compute_ratings(entry, [entry])["categories"]["connectivity"]
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["score"])


# ============================================================
# 10 & 11. PROPERTY FEATURES + TYPE-AWARE APPLICABILITY
# ============================================================

class PropertyFeaturesScoringTests(unittest.TestCase):

    def test_counts_only_applicable_true_features(self):
        document = make_smarthomes_document()
        document["building"] = {"lift": True, "power_backup": True, "security": False, "cctv": False}
        document["parking"] = {"covered_parking": True, "open_parking": False}
        entry = make_entry("smarthomes", "p1", document)

        result = compute_ratings(entry, [entry])["categories"]["property_features"]
        self.assertEqual(result["status"], "valid")
        self.assertGreater(result["score"], 0.0)
        self.assertLess(result["score"], 100.0)

    def test_never_penalized_for_inapplicable_fields(self):
        """A plot has no 'lift'/'furnishing' etc. - those fields must
        never count against it (applies_to filtering)."""
        document = make_smarthomes_document(
            property={"type": "plot", "bhk": None, "area_sqft": 2400},
            type_details={"corner_plot": True, "gated_layout": True, "boundary_wall_plot": True},
        )
        entry = make_entry("smarthomes", "p1", document)
        result = compute_ratings(entry, [entry])["categories"]["property_features"]
        self.assertEqual(result["status"], "valid")
        # All 3 plot-applicable booleans set True among the plot's
        # applicable fields - should score reasonably high, never
        # penalized by fields (like "lift") that simply don't apply.
        self.assertGreater(result["score"], 0.0)

    def test_square_yards_is_unavailable_not_invented(self):
        entry = make_entry("squareyards", "SY1", make_square_yards_listing())
        result = compute_ratings(entry, [entry])["categories"]["property_features"]
        self.assertEqual(result["status"], "unavailable")


# ============================================================
# 12. MISSING-DATA HANDLING (general)
# ============================================================

class MissingDataHandlingTests(unittest.TestCase):

    def test_unavailable_category_has_none_score(self):
        entry = make_entry("squareyards", "SY1", make_square_yards_listing())
        ratings = compute_ratings(entry, [entry])
        for key in ("availability", "connectivity", "property_features"):
            self.assertIsNone(ratings["categories"][key]["score"])
            self.assertEqual(ratings["categories"][key]["status"], "unavailable")


# ============================================================
# 13. WEIGHT REDISTRIBUTION
# ============================================================

class WeightRedistributionTests(unittest.TestCase):

    def test_overall_uses_only_valid_categories_renormalized(self):
        entry = make_entry("squareyards", "SY1", make_square_yards_listing())
        ratings = compute_ratings(entry, [entry])

        valid_keys = [
            key for key, c in ratings["categories"].items() if c["status"] == "valid"
        ]
        expected_weight_sum = sum(BASE_WEIGHTS[key] for key in valid_keys)
        expected_overall = sum(
            ratings["categories"][key]["score"] * BASE_WEIGHTS[key] for key in valid_keys
        ) / expected_weight_sum

        self.assertAlmostEqual(ratings["overall"]["score"], round(expected_overall, 2), places=2)

    def test_base_weights_sum_to_one(self):
        self.assertAlmostEqual(sum(BASE_WEIGHTS.values()), 1.0, places=6)

    def test_all_unavailable_categories_yields_unavailable_overall(self):
        # Square Yards with no price/amenities/city at all.
        entry = make_entry("squareyards", "SY1", make_square_yards_listing(
            price=None, price_on_request=True, amenities=None, city=None, locality=None,
        ))
        ratings = compute_ratings(entry, [entry])
        self.assertEqual(ratings["overall"]["status"], "unavailable")
        self.assertIsNone(ratings["overall"]["score"])


# ============================================================
# 14. OVERALL RATING CALCULATION
# ============================================================

class OverallRatingTests(unittest.TestCase):

    def test_overall_is_between_0_and_100_when_valid(self):
        entry = make_entry("smarthomes", "p1", make_smarthomes_document())
        ratings = compute_ratings(entry, [entry])
        self.assertEqual(ratings["overall"]["status"], "valid")
        self.assertGreaterEqual(ratings["overall"]["score"], 0.0)
        self.assertLessEqual(ratings["overall"]["score"], 100.0)

    def test_overall_basis_lists_only_valid_category_labels(self):
        entry = make_entry("squareyards", "SY1", make_square_yards_listing())
        ratings = compute_ratings(entry, [entry])
        basis = ratings["overall"]["basis"]
        self.assertIn("Price / Value", basis)
        self.assertNotIn("Availability", basis)
        self.assertNotIn("Connectivity / Nearby Facilities", basis)
        self.assertNotIn("Property Features", basis)


# ============================================================
# 15. DETERMINISM
# ============================================================

class DeterminismTests(unittest.TestCase):

    def test_repeated_calculation_is_identical(self):
        entries = [
            make_entry("smarthomes", "p1", make_smarthomes_document()),
            make_entry("squareyards", "SY1", make_square_yards_listing()),
        ]

        first = compare_properties(entries)
        second = compare_properties(entries)

        self.assertEqual(first, second)

    def test_order_of_other_entries_does_not_change_the_math_inputs(self):
        a = make_entry("smarthomes", "a", make_smarthomes_document())
        b = make_entry("smarthomes", "b", make_smarthomes_document(
            listing={"type": "rent", "status": "active", "price": 40000, "title": "b"}
        ))

        ratings_1 = compute_ratings(a, [a, b])
        ratings_2 = compute_ratings(a, [b, a])

        self.assertEqual(ratings_1, ratings_2)


# ============================================================
# 16. NO MUTATION OF INPUT DATA
# ============================================================

class NoMutationTests(unittest.TestCase):

    def test_smarthomes_document_is_not_mutated(self):
        document = make_smarthomes_document()
        snapshot = copy.deepcopy(document)
        smarthomes_property_to_row("p1", document)
        self.assertEqual(document, snapshot)

    def test_square_yards_normalized_dict_is_not_mutated(self):
        normalized = make_square_yards_listing()
        snapshot = copy.deepcopy(normalized)
        square_yards_listing_to_row(normalized)
        self.assertEqual(normalized, snapshot)

    def test_entries_are_not_mutated_by_compare_properties(self):
        entries = [
            make_entry("smarthomes", "p1", make_smarthomes_document()),
            make_entry("squareyards", "SY1", make_square_yards_listing()),
        ]
        snapshot = copy.deepcopy(entries)

        compare_properties(entries)

        self.assertEqual(entries, snapshot)

    def test_row_dicts_are_not_mutated_by_compute_ratings(self):
        entry = make_entry("smarthomes", "p1", make_smarthomes_document())
        row_snapshot = copy.deepcopy(entry["row"])

        compute_ratings(entry, [entry])

        self.assertEqual(entry["row"], row_snapshot)


if __name__ == "__main__":
    unittest.main()
