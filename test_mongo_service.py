"""
Unit tests for services/mongo_service.py's connection timeout
configuration. pymongo.MongoClient connects LAZILY - constructing one
never makes a network call, so these tests never touch a real
MongoDB, even with an unreachable URI.
"""

import unittest

from services.mongo_service import (
    MongoService,
    DEFAULT_SERVER_SELECTION_TIMEOUT_MS,
    DEFAULT_CONNECT_TIMEOUT_MS,
)


# A syntactically valid but deliberately unreachable URI (port 1) -
# constructing a MongoClient against it never connects (pymongo is
# lazy), so this is safe to use in every test below without risking a
# real network call.
FAKE_URI = "mongodb://localhost:1/"


class MongoServiceTimeoutTests(unittest.TestCase):

    def test_default_server_selection_timeout_is_applied(self):
        service = MongoService(FAKE_URI)
        try:
            applied_ms = service.client.options.server_selection_timeout * 1000
            self.assertEqual(applied_ms, DEFAULT_SERVER_SELECTION_TIMEOUT_MS)
        finally:
            service.close()

    def test_default_connect_timeout_is_applied(self):
        service = MongoService(FAKE_URI)
        try:
            applied_ms = service.client.options.pool_options.connect_timeout * 1000
            self.assertEqual(applied_ms, DEFAULT_CONNECT_TIMEOUT_MS)
        finally:
            service.close()

    def test_defaults_are_tighter_than_pymongos_own_30_second_default(self):
        # The whole point of this change: an unreachable Atlas cluster
        # must fail fast, not after pymongo's own 30-second default.
        self.assertLess(DEFAULT_SERVER_SELECTION_TIMEOUT_MS, 30000)

    def test_explicit_timeout_overrides_are_respected(self):
        service = MongoService(
            FAKE_URI,
            server_selection_timeout_ms=1234,
            connect_timeout_ms=5678,
        )
        try:
            self.assertAlmostEqual(service.client.options.server_selection_timeout, 1.234)
            self.assertAlmostEqual(service.client.options.pool_options.connect_timeout, 5.678)
        finally:
            service.close()

    def test_constructing_the_client_never_makes_a_network_call(self):
        # pymongo connects lazily - this must complete instantly even
        # against an unreachable host, proving no eager connection
        # attempt happens at construction time.
        import time
        start = time.perf_counter()
        service = MongoService(FAKE_URI)
        elapsed = time.perf_counter() - start
        service.close()
        self.assertLess(elapsed, 1.0)

    def test_get_collection_still_works_as_before(self):
        service = MongoService(FAKE_URI)
        try:
            collection = service.get_collection("properties")
            self.assertEqual(collection.name, "properties")
        finally:
            service.close()


if __name__ == "__main__":
    unittest.main()
