from pymongo import MongoClient


# pymongo's own defaults (serverSelectionTimeoutMS=30000,
# connectTimeoutMS=20000) mean an unreachable Atlas cluster or a
# network outage hangs every startup/operation for up to 30 seconds
# before failing. These tightened defaults make that failure surface
# in a few seconds instead, without being so tight that a normal,
# slightly-slow Atlas connection gets rejected - overridable via the
# constructor (app.py resolves the real values from environment
# variables, matching this project's existing convention of services
# never reading os.environ themselves - see
# services/osm_location_service.py's timeout_seconds parameter for the
# same pattern).
DEFAULT_SERVER_SELECTION_TIMEOUT_MS = 5000
DEFAULT_CONNECT_TIMEOUT_MS = 5000


class MongoService:

    DATABASE_NAME = "smarthomes"

    def __init__(
        self,
        uri,
        server_selection_timeout_ms=DEFAULT_SERVER_SELECTION_TIMEOUT_MS,
        connect_timeout_ms=DEFAULT_CONNECT_TIMEOUT_MS,
    ):

        self.client = MongoClient(
            uri,
            serverSelectionTimeoutMS=server_selection_timeout_ms,
            connectTimeoutMS=connect_timeout_ms,
        )

        self.db = self.client[
            self.DATABASE_NAME
        ]

    # ========================================================
    # CONNECTION TEST
    # ========================================================

    def ping(self):

        self.client.admin.command(
            "ping"
        )

        return True

    # ========================================================
    # GET COLLECTION
    # ========================================================

    def get_collection(
        self,
        collection_name
    ):

        return self.db[
            collection_name
        ]

    # ========================================================
    # CLOSE
    # ========================================================

    def close(self):

        self.client.close()