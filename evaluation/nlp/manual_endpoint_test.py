"""Manual test of POST /api/search/parse-query via a real Flask test
client (same approach used for Phase 1's endpoint verification)."""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import app as app_module

flask_app = app_module.app
flask_app.testing = True

QUERIES = [
    "2 bhk flat for rent near VIT Chennai under 25000 with parking",
    "3 BHK villa for sale in Chennai below 1.5 crore with swimming pool",
    "what's the weather today",
    "SRM",
]

with flask_app.test_client() as client:
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    for q in QUERIES:
        resp = client.post("/api/search/parse-query", json={"query": q})
        print("=" * 90)
        print(f"QUERY: {q!r}  HTTP {resp.status_code}")
        print(json.dumps(resp.get_json(), indent=2, ensure_ascii=False))
