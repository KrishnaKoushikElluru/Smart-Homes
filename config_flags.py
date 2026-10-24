"""
Tiny, dependency-free (stdlib `os` only) environment-flag helpers for
app.py.

Deliberately kept separate from app.py itself: importing app.py runs
its full startup sequence (a real MongoDB connection, index creation,
blueprint registration - see app.py's own module docstring/sections),
so anything in here that needs to be unit-tested without that side
effect has to live in a module app.py merely imports, not in app.py's
own top-level code. See test_app_config.py.
"""

import os


def flask_debug_enabled() -> bool:
    """True only when FLASK_DEBUG is explicitly set to a truthy value
    ("true"/"1"/"yes", case-insensitive). Defaults to False - a
    hardcoded debug=True in app.run() would expose Werkzeug's
    interactive debugger (arbitrary code execution from the browser on
    any unhandled exception) to anything that can reach the process."""

    return os.getenv(
        "FLASK_DEBUG",
        "false"
    ).strip().lower() in ("true", "1", "yes")
