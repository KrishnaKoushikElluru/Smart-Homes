"""
Unit tests for config_flags.py - deliberately NOT for app.py itself,
since importing app.py triggers a real MongoDB connection (see
config_flags.py's own module docstring). These tests exercise
flask_debug_enabled() in complete isolation, with os.environ patched
per-test so they never depend on (or mutate) the real process
environment.
"""

import unittest
from unittest.mock import patch

from config_flags import flask_debug_enabled


class FlaskDebugEnabledTests(unittest.TestCase):

    def test_defaults_to_false_when_unset(self):
        with patch.dict("os.environ", {}, clear=True):
            self.assertFalse(flask_debug_enabled())

    def test_true_string_enables_debug(self):
        with patch.dict("os.environ", {"FLASK_DEBUG": "true"}):
            self.assertTrue(flask_debug_enabled())

    def test_uppercase_true_is_accepted(self):
        with patch.dict("os.environ", {"FLASK_DEBUG": "TRUE"}):
            self.assertTrue(flask_debug_enabled())

    def test_one_is_accepted(self):
        with patch.dict("os.environ", {"FLASK_DEBUG": "1"}):
            self.assertTrue(flask_debug_enabled())

    def test_yes_is_accepted(self):
        with patch.dict("os.environ", {"FLASK_DEBUG": "yes"}):
            self.assertTrue(flask_debug_enabled())

    def test_false_string_stays_disabled(self):
        with patch.dict("os.environ", {"FLASK_DEBUG": "false"}):
            self.assertFalse(flask_debug_enabled())

    def test_empty_string_stays_disabled(self):
        with patch.dict("os.environ", {"FLASK_DEBUG": ""}):
            self.assertFalse(flask_debug_enabled())

    def test_garbage_value_stays_disabled_not_an_error(self):
        # Fail-safe: anything unrecognized must default to OFF, never
        # raise and never accidentally enable debug mode.
        with patch.dict("os.environ", {"FLASK_DEBUG": "maybe"}):
            self.assertFalse(flask_debug_enabled())

    def test_surrounding_whitespace_is_tolerated(self):
        with patch.dict("os.environ", {"FLASK_DEBUG": "  true  "}):
            self.assertTrue(flask_debug_enabled())


if __name__ == "__main__":
    unittest.main()
