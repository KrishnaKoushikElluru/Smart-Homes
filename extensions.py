from functools import wraps

from flask import current_app
from flask_sqlalchemy import SQLAlchemy
from flask_bcrypt import Bcrypt
from flask_migrate import Migrate
from flask_login import LoginManager
from flask_wtf import CSRFProtect



# ============================================================
# SQLAlchemy
# ============================================================

db = SQLAlchemy()


# ============================================================
# Bcrypt
# ============================================================

bcrypt = Bcrypt()


# ============================================================
# Flask-Migrate
# ============================================================

migrate = Migrate()


# ============================================================
# Flask-Login
# ============================================================

login_manager = LoginManager()

login_manager.login_view = "auth.login"


# ============================================================
# Flask-WTF CSRF
#
# app.py sets WTF_CSRF_CHECK_DEFAULT = False, which turns OFF
# CSRFProtect's own automatic before_request check for every route -
# this app has several JS/fetch POST endpoints (search, location
# autocomplete, image upload/generation) that send no CSRF token and
# must keep working completely untouched. require_csrf below is the
# explicit, opt-in alternative: only routes decorated with it are
# actually checked, via the SAME CSRFProtect instance/token (reusing
# Flask-WTF, not a second implementation) - see routes/property_routes.py's
# submit_listing/update_listing/delete_listing/relist_listing for the
# only routes that currently use it.
# ============================================================

csrf = CSRFProtect()


def require_csrf(view_func):
    """Explicitly opts ONE view into CSRF checking (see the module
    note above for why this isn't just the global CSRFProtect
    default). Reads the same "csrf_token" form field / X-CSRFToken
    header Flask-WTF always does - a plain <form> just needs a hidden
    {{ csrf_token() }} input; nothing else changes about the route's
    request/response handling. Raises flask_wtf.csrf.CSRFError (a
    werkzeug BadRequest) on a missing/invalid/expired token - app.py
    registers one error handler for that, so every route using this
    decorator gets the same friendly flash+redirect behavior for free,
    not a raw 400 page."""

    @wraps(view_func)
    def wrapped(*args, **kwargs):
        if current_app.config.get("WTF_CSRF_ENABLED", True):
            csrf.protect()
        return view_func(*args, **kwargs)
    return wrapped


# ============================================================
# MongoDB
# ============================================================
