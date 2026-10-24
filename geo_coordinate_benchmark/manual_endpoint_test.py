"""
Manual test of POST /api/location/resolve-poi through a real Flask test
client (exercises the actual route/blueprint wiring in app.py and
routes/property_routes.py - not a bypass of the HTTP layer).

Logs in as an existing user via a forced session (Flask-Login stores the
authenticated user id in the session under "_user_id") since the route
is @login_required, matching every other API route in this app.
"""
import sys
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import app as app_module  # noqa: E402

flask_app = app_module.app
flask_app.testing = True

QUERIES = [
    "VIT Chennai",
    "SRM",
    "Apollo Hospital Chennai",
    "MGM Health Care",
    "Chennai Central",
    "VIT",  # obviously ambiguous
]

with flask_app.test_client() as client:
    with client.session_transaction() as sess:
        sess["_user_id"] = "1"
        sess["_fresh"] = True

    for q in QUERIES:
        resp = client.post(
            "/api/location/resolve-poi",
            json={"query": q},
        )
        print("=" * 90)
        print(f"QUERY: {q!r}  HTTP {resp.status_code}")
        print(json.dumps(resp.get_json(), indent=2, ensure_ascii=False, default=str))
