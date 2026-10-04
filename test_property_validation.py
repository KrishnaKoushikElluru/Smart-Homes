"""
Unit tests for services/property_validation.py - the registry-driven
parsing/validation logic every property-registration field goes
through (see that module's own docstring). Pure functions, no Flask
app/request context, no MongoDB, no fakes needed - `form` is just a
dict (every function only ever calls form.get(name)/form.get(name, "")).

These tests use the CURRENT implementation's actual behavior as the
source of truth throughout - they lock in existing semantics as a
regression guard, they do not redesign or "improve" any validation
rule.
"""

import unittest

from services.property_validation import (
    _check_bounds,
    parse_field,
    parse_fields,
    parse_group_for_type,
    parse_latitude_longitude,
    parse_phone,
)


# ============================================================
# _check_bounds
# ============================================================

class CheckBoundsTests(unittest.TestCase):

    def test_value_within_bounds_passes_through_unchanged(self):
        field = {"min": 1, "max": 10}
        value, error = _check_bounds(5, field, "Field")
        self.assertEqual(value, 5)
        self.assertIsNone(error)

    def test_value_exactly_at_minimum_is_accepted(self):
        field = {"min": 1, "max": 10}
        value, error = _check_bounds(1, field, "Field")
        self.assertEqual(value, 1)
        self.assertIsNone(error)

    def test_value_exactly_at_maximum_is_accepted(self):
        field = {"min": 1, "max": 10}
        value, error = _check_bounds(10, field, "Field")
        self.assertEqual(value, 10)
        self.assertIsNone(error)

    def test_value_below_minimum_is_rejected(self):
        field = {"min": 1, "max": 10}
        value, error = _check_bounds(0, field, "Price")
        self.assertIsNone(value)
        self.assertEqual(error, "Price must be at least 1.")

    def test_value_above_maximum_is_rejected(self):
        field = {"min": 1, "max": 10}
        value, error = _check_bounds(11, field, "Price")
        self.assertIsNone(value)
        self.assertEqual(error, "Price must be at most 10.")

    def test_no_bounds_declared_always_passes(self):
        field = {}
        value, error = _check_bounds(999999, field, "Field")
        self.assertEqual(value, 999999)
        self.assertIsNone(error)

    def test_only_minimum_declared_still_enforces_it(self):
        field = {"min": 0}
        value, error = _check_bounds(-1, field, "Count")
        self.assertIsNone(value)
        self.assertEqual(error, "Count must be at least 0.")

    def test_only_maximum_declared_still_enforces_it(self):
        field = {"max": 100}
        value, error = _check_bounds(101, field, "Percent")
        self.assertIsNone(value)
        self.assertEqual(error, "Percent must be at most 100.")

    def test_zero_as_minimum_is_not_confused_with_no_minimum(self):
        # min=0 must still be enforced (falsy-but-not-None pitfall).
        field = {"min": 0}
        value, error = _check_bounds(0, field, "Count")
        self.assertEqual(value, 0)
        self.assertIsNone(error)


# ============================================================
# parse_field
# ============================================================

class ParseFieldBoolTests(unittest.TestCase):

    def test_checkbox_on_is_true(self):
        value, error = parse_field({"flag": "on"}, {"name": "flag", "kind": "bool"})
        self.assertIs(value, True)
        self.assertIsNone(error)

    def test_checkbox_absent_is_false_not_missing(self):
        value, error = parse_field({}, {"name": "flag", "kind": "bool"})
        self.assertIs(value, False)
        self.assertIsNone(error)

    def test_checkbox_never_required_even_when_marked_required(self):
        # Booleans are always present (True/False) by construction -
        # "required" is meaningless for this kind, per the module's
        # own comment.
        value, error = parse_field({}, {"name": "flag", "kind": "bool", "required": True})
        self.assertIs(value, False)
        self.assertIsNone(error)


class ParseFieldTriboolTests(unittest.TestCase):

    def test_yes_is_true(self):
        value, error = parse_field({"pets": "yes"}, {"name": "pets", "kind": "tribool"})
        self.assertIs(value, True)
        self.assertIsNone(error)

    def test_no_is_false(self):
        value, error = parse_field({"pets": "no"}, {"name": "pets", "kind": "tribool"})
        self.assertIs(value, False)
        self.assertIsNone(error)

    def test_unspecified_is_none_not_an_error(self):
        value, error = parse_field({"pets": ""}, {"name": "pets", "kind": "tribool"})
        self.assertIsNone(value)
        self.assertIsNone(error)

    def test_missing_entirely_is_none_not_an_error(self):
        value, error = parse_field({}, {"name": "pets", "kind": "tribool"})
        self.assertIsNone(value)
        self.assertIsNone(error)

    def test_garbage_value_is_treated_as_unspecified_not_an_error(self):
        value, error = parse_field({"pets": "maybe"}, {"name": "pets", "kind": "tribool"})
        self.assertIsNone(value)
        self.assertIsNone(error)


class ParseFieldRequiredMissingTests(unittest.TestCase):

    def test_required_and_missing_is_an_error(self):
        value, error = parse_field({}, {"name": "title", "kind": "str", "required": True, "label": "Title"})
        self.assertIsNone(value)
        self.assertEqual(error, "Title is required.")

    def test_required_and_whitespace_only_is_still_missing(self):
        value, error = parse_field({"title": "   "}, {"name": "title", "kind": "str", "required": True, "label": "Title"})
        self.assertIsNone(value)
        self.assertEqual(error, "Title is required.")

    def test_not_required_and_missing_uses_declared_default(self):
        value, error = parse_field({}, {"name": "floor", "kind": "int", "default": 0})
        self.assertEqual(value, 0)
        self.assertIsNone(error)

    def test_not_required_and_missing_with_no_default_is_none(self):
        value, error = parse_field({}, {"name": "floor", "kind": "int"})
        self.assertIsNone(value)
        self.assertIsNone(error)


class ParseFieldStrTests(unittest.TestCase):

    def test_valid_string_passes_through_stripped(self):
        value, error = parse_field({"title": "  My Flat  "}, {"name": "title", "kind": "str"})
        self.assertEqual(value, "My Flat")
        self.assertIsNone(error)

    def test_maxlen_exceeded_is_rejected(self):
        field = {"name": "title", "kind": "str", "maxlen": 5, "label": "Title"}
        value, error = parse_field({"title": "way too long"}, field)
        self.assertIsNone(value)
        self.assertEqual(error, "Title must be under 5 characters.")

    def test_maxlen_exactly_at_limit_is_accepted(self):
        field = {"name": "title", "kind": "str", "maxlen": 5}
        value, error = parse_field({"title": "12345"}, field)
        self.assertEqual(value, "12345")
        self.assertIsNone(error)

    def test_no_maxlen_declared_allows_any_length(self):
        field = {"name": "title", "kind": "str"}
        value, error = parse_field({"title": "x" * 10000}, field)
        self.assertEqual(len(value), 10000)
        self.assertIsNone(error)


class ParseFieldIntTests(unittest.TestCase):

    def test_valid_integer_string(self):
        value, error = parse_field({"bhk": "3"}, {"name": "bhk", "kind": "int"})
        self.assertEqual(value, 3)
        self.assertIsNone(error)

    def test_float_looking_string_is_truncated_via_int_of_float(self):
        # Matches the CURRENT implementation exactly: int(float(raw)).
        value, error = parse_field({"bhk": "3.0"}, {"name": "bhk", "kind": "int"})
        self.assertEqual(value, 3)
        self.assertIsNone(error)

    def test_malformed_integer_is_rejected(self):
        field = {"name": "bhk", "kind": "int", "label": "BHK"}
        value, error = parse_field({"bhk": "three"}, field)
        self.assertIsNone(value)
        self.assertEqual(error, "BHK must be a valid whole number.")

    def test_bounds_are_enforced_for_int_kind(self):
        field = {"name": "bhk", "kind": "int", "min": 1, "max": 10, "label": "BHK"}
        value, error = parse_field({"bhk": "0"}, field)
        self.assertIsNone(value)
        self.assertEqual(error, "BHK must be at least 1.")

    def test_negative_integer_is_accepted_when_no_minimum_declared(self):
        value, error = parse_field({"floor": "-1"}, {"name": "floor", "kind": "int"})
        self.assertEqual(value, -1)
        self.assertIsNone(error)


class ParseFieldFloatTests(unittest.TestCase):

    def test_valid_float_string(self):
        value, error = parse_field({"price": "25000.50"}, {"name": "price", "kind": "float"})
        self.assertEqual(value, 25000.50)
        self.assertIsNone(error)

    def test_malformed_float_is_rejected(self):
        field = {"name": "price", "kind": "float", "label": "Price"}
        value, error = parse_field({"price": "not-a-number"}, field)
        self.assertIsNone(value)
        self.assertEqual(error, "Price must be a valid number.")

    def test_bounds_are_enforced_for_float_kind(self):
        field = {"name": "price", "kind": "float", "min": 1, "label": "Price"}
        value, error = parse_field({"price": "0"}, field)
        self.assertIsNone(value)
        self.assertEqual(error, "Price must be at least 1.")

    def test_scientific_notation_is_accepted_by_pythons_own_float(self):
        # Documents actual current behavior (float("1e3") == 1000.0) -
        # not a deliberately designed feature, just what float() does.
        value, error = parse_field({"price": "1e3"}, {"name": "price", "kind": "float"})
        self.assertEqual(value, 1000.0)
        self.assertIsNone(error)


class ParseFieldSelectTests(unittest.TestCase):

    def test_valid_option_is_accepted(self):
        field = {"name": "furnishing", "kind": "select", "options": [("unfurnished", "Unfurnished"), ("semi_furnished", "Semi")]}
        value, error = parse_field({"furnishing": "semi_furnished"}, field)
        self.assertEqual(value, "semi_furnished")
        self.assertIsNone(error)

    def test_invalid_option_is_rejected(self):
        field = {"name": "furnishing", "kind": "select", "options": [("unfurnished", "Unfurnished")], "label": "Furnishing"}
        value, error = parse_field({"furnishing": "not_a_real_option"}, field)
        self.assertIsNone(value)
        self.assertEqual(error, "Furnishing has an invalid selection.")

    def test_no_options_declared_rejects_everything(self):
        field = {"name": "furnishing", "kind": "select", "label": "Furnishing"}
        value, error = parse_field({"furnishing": "anything"}, field)
        self.assertIsNone(value)
        self.assertEqual(error, "Furnishing has an invalid selection.")


class ParseFieldDateTests(unittest.TestCase):

    def test_valid_date(self):
        value, error = parse_field({"available_from": "2026-11-01"}, {"name": "available_from", "kind": "date"})
        self.assertEqual(value, "2026-11-01")
        self.assertIsNone(error)

    def test_malformed_date_is_rejected(self):
        field = {"name": "available_from", "kind": "date", "label": "Available From"}
        value, error = parse_field({"available_from": "01/11/2026"}, field)
        self.assertIsNone(value)
        self.assertEqual(error, "Available From must be a valid date.")

    def test_nonexistent_calendar_date_is_rejected(self):
        field = {"name": "available_from", "kind": "date", "label": "Available From"}
        value, error = parse_field({"available_from": "2026-02-30"}, field)  # Feb 30 doesn't exist
        self.assertIsNone(value)
        self.assertEqual(error, "Available From must be a valid date.")


class ParseFieldPincodeTests(unittest.TestCase):

    def test_valid_six_digit_pincode(self):
        value, error = parse_field({"pincode": "600042"}, {"name": "pincode", "kind": "pincode"})
        self.assertEqual(value, "600042")
        self.assertIsNone(error)

    def test_too_short_pincode_is_rejected(self):
        field = {"name": "pincode", "kind": "pincode", "label": "Pincode"}
        value, error = parse_field({"pincode": "6004"}, field)
        self.assertIsNone(value)
        self.assertEqual(error, "Pincode must be a valid 6-digit pincode.")

    def test_too_long_pincode_is_rejected(self):
        field = {"name": "pincode", "kind": "pincode", "label": "Pincode"}
        value, error = parse_field({"pincode": "6000420"}, field)
        self.assertIsNone(value)
        self.assertEqual(error, "Pincode must be a valid 6-digit pincode.")

    def test_non_numeric_pincode_is_rejected(self):
        field = {"name": "pincode", "kind": "pincode", "label": "Pincode"}
        value, error = parse_field({"pincode": "60004A"}, field)
        self.assertIsNone(value)
        self.assertEqual(error, "Pincode must be a valid 6-digit pincode.")


# ============================================================
# parse_fields / parse_group_for_type
# ============================================================

class ParseFieldsTests(unittest.TestCase):

    def test_collects_values_and_errors_across_multiple_fields(self):
        fields = [
            {"name": "title", "kind": "str", "required": True, "label": "Title"},
            {"name": "price", "kind": "float", "required": True, "label": "Price"},
        ]
        values, errors = parse_fields({"title": "A Flat", "price": "not-a-number"}, fields)

        self.assertEqual(values, {"title": "A Flat"})
        self.assertEqual(errors, ["Price must be a valid number."])

    def test_none_values_are_never_included_in_the_result_dict(self):
        fields = [{"name": "floor", "kind": "int"}]  # not required, missing, no default
        values, errors = parse_fields({}, fields)
        self.assertNotIn("floor", values)
        self.assertEqual(errors, [])

    def test_empty_field_list_returns_empty_results(self):
        values, errors = parse_fields({"anything": "x"}, [])
        self.assertEqual(values, {})
        self.assertEqual(errors, [])


class ParseGroupForTypeTests(unittest.TestCase):

    def test_only_applicable_fields_are_parsed(self):
        fields = [
            {"name": "bathrooms", "kind": "int", "applies_to": {"apartment", "villa"}},
            {"name": "plot_sqft", "kind": "float", "applies_to": {"plot"}},
        ]
        values, errors = parse_group_for_type(
            {"bathrooms": "2", "plot_sqft": "1200"}, fields, "apartment"
        )
        # plot_sqft does NOT apply to "apartment" - must be ignored
        # entirely, not parsed and not an error.
        self.assertEqual(values, {"bathrooms": 2})
        self.assertNotIn("plot_sqft", values)
        self.assertEqual(errors, [])

    def test_a_required_field_not_applicable_to_this_type_produces_no_error(self):
        fields = [
            {"name": "plot_sqft", "kind": "float", "required": True,
             "label": "Plot Area", "applies_to": {"plot"}},
        ]
        values, errors = parse_group_for_type({}, fields, "apartment")
        self.assertEqual(errors, [])  # never evaluated - plot_sqft doesn't apply here

    def test_a_required_field_applicable_to_this_type_is_still_enforced(self):
        fields = [
            {"name": "plot_sqft", "kind": "float", "required": True,
             "label": "Plot Area", "applies_to": {"plot"}},
        ]
        values, errors = parse_group_for_type({}, fields, "plot")
        self.assertEqual(errors, ["Plot Area is required."])


# ============================================================
# parse_latitude_longitude
# ============================================================

class ParseLatitudeLongitudeTests(unittest.TestCase):

    def test_valid_coordinates(self):
        lat, lon, error = parse_latitude_longitude({"latitude": "12.9716", "longitude": "77.5946"})
        self.assertEqual(lat, 12.9716)
        self.assertEqual(lon, 77.5946)
        self.assertIsNone(error)

    def test_missing_latitude_is_rejected(self):
        lat, lon, error = parse_latitude_longitude({"longitude": "77.5946"})
        self.assertIsNone(lat)
        self.assertIsNone(lon)
        self.assertEqual(error, "Please select the property location on the map.")

    def test_missing_longitude_is_rejected(self):
        lat, lon, error = parse_latitude_longitude({"latitude": "12.9716"})
        self.assertIsNone(lat)
        self.assertIsNone(lon)
        self.assertEqual(error, "Please select the property location on the map.")

    def test_both_missing_is_rejected(self):
        lat, lon, error = parse_latitude_longitude({})
        self.assertIsNone(lat)
        self.assertIsNone(lon)
        self.assertEqual(error, "Please select the property location on the map.")

    def test_whitespace_only_values_are_treated_as_missing(self):
        lat, lon, error = parse_latitude_longitude({"latitude": "   ", "longitude": "77.5946"})
        self.assertEqual(error, "Please select the property location on the map.")

    def test_non_numeric_latitude_is_rejected_with_invalid_coordinates_message(self):
        lat, lon, error = parse_latitude_longitude({"latitude": "not-a-number", "longitude": "77.5946"})
        self.assertIsNone(lat)
        self.assertIsNone(lon)
        self.assertEqual(error, "Invalid map coordinates.")

    def test_latitude_above_90_is_rejected(self):
        lat, lon, error = parse_latitude_longitude({"latitude": "91", "longitude": "0"})
        self.assertEqual(error, "Invalid map coordinates.")

    def test_latitude_below_negative_90_is_rejected(self):
        lat, lon, error = parse_latitude_longitude({"latitude": "-91", "longitude": "0"})
        self.assertEqual(error, "Invalid map coordinates.")

    def test_latitude_exactly_at_90_boundary_is_accepted(self):
        lat, lon, error = parse_latitude_longitude({"latitude": "90", "longitude": "0"})
        self.assertEqual(lat, 90.0)
        self.assertIsNone(error)

    def test_latitude_exactly_at_negative_90_boundary_is_accepted(self):
        lat, lon, error = parse_latitude_longitude({"latitude": "-90", "longitude": "0"})
        self.assertEqual(lat, -90.0)
        self.assertIsNone(error)

    def test_longitude_above_180_is_rejected(self):
        lat, lon, error = parse_latitude_longitude({"latitude": "0", "longitude": "181"})
        self.assertEqual(error, "Invalid map coordinates.")

    def test_longitude_below_negative_180_is_rejected(self):
        lat, lon, error = parse_latitude_longitude({"latitude": "0", "longitude": "-181"})
        self.assertEqual(error, "Invalid map coordinates.")

    def test_longitude_exactly_at_180_boundary_is_accepted(self):
        lat, lon, error = parse_latitude_longitude({"latitude": "0", "longitude": "180"})
        self.assertEqual(lon, 180.0)
        self.assertIsNone(error)

    def test_longitude_exactly_at_negative_180_boundary_is_accepted(self):
        lat, lon, error = parse_latitude_longitude({"latitude": "0", "longitude": "-180"})
        self.assertEqual(lon, -180.0)
        self.assertIsNone(error)


# ============================================================
# parse_phone
# ============================================================

class ParsePhoneTests(unittest.TestCase):

    def test_valid_ten_digit_phone(self):
        value, error = parse_phone({"phone": "9876543210"}, "phone", "Phone")
        self.assertEqual(value, "9876543210")
        self.assertIsNone(error)

    def test_phone_with_formatting_characters_is_kept_as_entered(self):
        # Digits are counted for the length check, but the ORIGINAL
        # (stripped) string is what's returned - matches the current
        # implementation exactly (`return raw, None`, not `digits`).
        value, error = parse_phone({"phone": "+91 98765-43210"}, "phone", "Phone")
        self.assertEqual(value, "+91 98765-43210")
        self.assertIsNone(error)

    def test_not_required_and_missing_returns_none_no_error(self):
        value, error = parse_phone({}, "whatsapp", "WhatsApp", required=False)
        self.assertIsNone(value)
        self.assertIsNone(error)

    def test_required_and_missing_is_an_error(self):
        value, error = parse_phone({}, "phone", "Phone", required=True)
        self.assertIsNone(value)
        self.assertEqual(error, "Phone is required.")

    def test_too_few_digits_is_rejected(self):
        value, error = parse_phone({"phone": "123456789"}, "phone", "Phone")  # 9 digits
        self.assertIsNone(value)
        self.assertEqual(error, "Phone must be a valid phone number.")

    def test_too_many_digits_is_rejected(self):
        value, error = parse_phone({"phone": "12345678901234"}, "phone", "Phone")  # 14 digits
        self.assertIsNone(value)
        self.assertEqual(error, "Phone must be a valid phone number.")

    def test_exactly_ten_digits_is_the_minimum_accepted(self):
        value, error = parse_phone({"phone": "1234567890"}, "phone", "Phone")
        self.assertEqual(value, "1234567890")
        self.assertIsNone(error)

    def test_exactly_thirteen_digits_is_the_maximum_accepted(self):
        value, error = parse_phone({"phone": "1234567890123"}, "phone", "Phone")
        self.assertEqual(value, "1234567890123")
        self.assertIsNone(error)

    def test_whitespace_only_is_treated_as_missing(self):
        value, error = parse_phone({"phone": "   "}, "phone", "Phone", required=True)
        self.assertIsNone(value)
        self.assertEqual(error, "Phone is required.")

    def test_non_digit_characters_are_stripped_before_counting_length(self):
        # "(987) 654-3210" has exactly 10 digits once non-digits are
        # removed for the length check, even though it's not a bare
        # numeric string.
        value, error = parse_phone({"phone": "(987) 654-3210"}, "phone", "Phone")
        self.assertIsNone(error)


if __name__ == "__main__":
    unittest.main()
