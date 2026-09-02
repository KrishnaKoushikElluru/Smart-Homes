from pymongo import MongoClient


class MongoService:

    DATABASE_NAME = "smarthomes"

    def __init__(self, uri):

        self.client = MongoClient(
            uri
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