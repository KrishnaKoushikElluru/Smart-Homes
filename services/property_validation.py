"""
Generic, registry-driven parsing/validation for property listing submission.

Every field is declared once in services/property_fields.py; this module
turns those declarations into actual parsing + validation logic so we
never hand-write near-identical "get form value, check it, flash error"
blocks for each of the dozens of listing fields.
"""

import re
from datetime import datetime

from services.property_fields import fields_for_type


PINCODE_PATTERN = re.compile(r"^\d{6}$")


def _check_bounds(value, field, label):

    minimum = field.get("min")
    maximum = field.get("max")

    if minimum is not None and value < minimum:
        return None, f"{label} must be at least {minimum}."

    if maximum is not None and value > maximum:
        return None, f"{label} must be at most {maximum}."

    return value, None


def parse_field(form, field):
    """Parse and validate a single field. Returns (value, error)."""

    name = field["name"]
    kind = field["kind"]
    label = field.get("label", name)
    required = field.get("required", False)

    # --------------------------------------------------------
    # Checkbox-style booleans are always present (True/False),
    # never "missing".
    # --------------------------------------------------------

    if kind == "bool":
        return (form.get(name) == "on"), None

    raw = form.get(name, "")

    if isinstance(raw, str):
        raw = raw.strip()

    # --------------------------------------------------------
    # Tri-state yes/no/unspecified select (e.g. pets allowed)
    # --------------------------------------------------------

    if kind == "tribool":

        if raw == "yes":
            return True, None

        if raw == "no":
            return False, None

        return None, None

    if not raw:

        if required:
            return None, f"{label} is required."

        return field.get("default"), None

    if kind in ("str", "text"):

        maxlen = field.get("maxlen")

        if maxlen and len(raw) > maxlen:
            return None, f"{label} must be under {maxlen} characters."

        return raw, None

    if kind == "int":

        try:
            value = int(float(raw))

        except ValueError:
            return None, f"{label} must be a valid whole number."

        return _check_bounds(value, field, label)

    if kind == "float":

        try:
            value = float(raw)

        except ValueError:
            return None, f"{label} must be a valid number."

        return _check_bounds(value, field, label)

    if kind == "select":

        options = {value for value, _ in field.get("options", [])}

        if raw not in options:
            return None, f"{label} has an invalid selection."

        return raw, None

    if kind == "date":

        try:
            datetime.strptime(raw, "%Y-%m-%d")

        except ValueError:
            return None, f"{label} must be a valid date."

        return raw, None

    if kind == "pincode":

        if not PINCODE_PATTERN.match(raw):
            return None, f"{label} must be a valid 6-digit pincode."

        return raw, None

    return raw, None


def parse_fields(form, fields):
    """Parse a flat list of fields (no property-type filtering)."""

    values = {}
    errors = []

    for field in fields:

        value, error = parse_field(form, field)

        if error:
            errors.append(error)
            continue

        if value is not None:
            values[field["name"]] = value

    return values, errors


def parse_group_for_type(form, fields, property_type):
    """Parse only the fields applicable to `property_type`."""

    applicable = fields_for_type(fields, property_type)

    return parse_fields(form, applicable)


def parse_latitude_longitude(form):

    latitude_raw = (form.get("latitude") or "").strip()
    longitude_raw = (form.get("longitude") or "").strip()

    if not latitude_raw or not longitude_raw:
        return None, None, "Please select the property location on the map."

    try:

        latitude = float(latitude_raw)
        longitude = float(longitude_raw)

        if not -90 <= latitude <= 90:
            raise ValueError

        if not -180 <= longitude <= 180:
            raise ValueError

    except ValueError:

        return None, None, "Invalid map coordinates."

    return latitude, longitude, None


def parse_phone(form, field_name, label, required=False):

    raw = (form.get(field_name) or "").strip()

    if not raw:

        if required:
            return None, f"{label} is required."

        return None, None

    digits = re.sub(r"[^\d]", "", raw)

    if len(digits) < 10 or len(digits) > 13:
        return None, f"{label} must be a valid phone number."

    return raw, None
