import os

from flask import (
    Flask,
    render_template,
    flash,
    redirect,
    request,
    url_for
)

from flask_wtf.csrf import CSRFError

from dotenv import load_dotenv

from extensions import (
    db,
    bcrypt,
    migrate,
    login_manager,
    csrf
)

import extensions

from config_flags import flask_debug_enabled
from models import User
from services.mongo_service import MongoService
from services.property_services import PropertyService
from services.osm_location_service import OSMLocationService
from services import nearby_facility_service
load_dotenv("secret.env")
from routes.auth_routes import auth_bp
from routes.property_routes import property_bp
from routes.search_routes import search_bp
from routes.design_routes import design_bp



# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv("secret.env")


app = Flask(__name__)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY"
)

if not app.config["SECRET_KEY"]:

    raise RuntimeError(
        "SECRET_KEY is not configured."
    )

app.config["SQLALCHEMY_DATABASE_URI"] = os.getenv(
    "DATABASE_URL",
    "sqlite:///site.db"
)

app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

app.config["MAX_CONTENT_LENGTH"] = (
    # Large enough for a full listing submission (up to 20 images,
    # 5 videos, a floor plan and a brochure) under the per-file
    # limits enforced in services/media_service.py.
    120 * 1024 * 1024
)

app.config["GEOAPIFY_API_KEY"] = os.getenv(
    "GEOAPIFY_API_KEY"
)

app.config["MAPPLS_API_KEY"] = os.getenv(
    "MAPPLS_API_KEY"
)

app.config["OLA_MAPS_API_KEY"] = os.getenv(
    "OLA_MAPS_API_KEY"
)

# ============================================================
# OSM / NOMINATIM CONFIGURATION
#
# Kept fully env-driven and provider-isolated (see
# services/osm_location_service.py) so the OSM backend can later move
# to a self-hosted Nominatim instance, another self-hosted OSM
# geocoder, or a locally indexed dataset without any application code
# changes - only these environment variables would change.
# ============================================================

app.config["OSM_NOMINATIM_URL"] = os.getenv(
    "OSM_NOMINATIM_URL",
    "https://nominatim.openstreetmap.org/search"
)

app.config["OSM_USER_AGENT"] = os.getenv(
    "OSM_USER_AGENT",
    "SmartHomes-LocationResolver/1.0 (contact: apisupport@smarthomes.local)"
)

app.config["OSM_TIMEOUT"] = int(os.getenv(
    "OSM_TIMEOUT",
    "8"
))

app.config["OSM_CACHE_ENABLED"] = os.getenv(
    "OSM_CACHE_ENABLED",
    "true"
).strip().lower() not in ("false", "0", "no")

app.config["OSM_CACHE_TTL_SECONDS"] = int(os.getenv(
    "OSM_CACHE_TTL_SECONDS",
    str(30 * 24 * 60 * 60)
))

# See services/osm_location_service.py module docstring for how these
# were calibrated against geo_coordinate_benchmark/results/osm_results.json
# rather than chosen arbitrarily.
app.config["OSM_MATCH_MIN_SCORE"] = float(os.getenv(
    "OSM_MATCH_MIN_SCORE",
    "0.40"
))

app.config["OSM_MATCH_MIN_MARGIN"] = float(os.getenv(
    "OSM_MATCH_MIN_MARGIN",
    "0.05"
))

# ============================================================
# PHASE 3 SEARCH ORCHESTRATION CONFIGURATION
#
# How far (in km) a POI-anchored natural-language search
# (routes/search_routes.py's /search_rentals with a "query" field)
# looks for properties around a resolved POI's coordinates, via
# MongoDB's $near on the existing location.coordinates 2dsphere index.
# See services/search_orchestration.py's module docstring.
# ============================================================

app.config["SEARCH_POI_RADIUS_KM"] = float(os.getenv(
    "SEARCH_POI_RADIUS_KM",
    "5.0"
))


# ============================================================
# PHASE 4.0 NEARBY FACILITY ENRICHMENT CONFIGURATION
#
# The discovery radius (in km) used when a newly-registered property is
# enriched with nearby facilities (gyms, hospitals, schools, etc - see
# services/nearby_facility_service.py). Deliberately separate from
# SEARCH_POI_RADIUS_KM above - that one governs how far a natural-
# language property SEARCH looks around an ambiguous landmark; this one
# governs what counts as a "nearby" AMENITY for a registered property,
# a tighter, more real-estate-relevant distance.
# ============================================================

app.config["NEARBY_FACILITY_RADIUS_KM"] = float(os.getenv(
    "NEARBY_FACILITY_RADIUS_KM",
    str(nearby_facility_service.DEFAULT_RADIUS_KM)
))


# ============================================================
# EXTENSIONS
# ============================================================

db.init_app(app)

bcrypt.init_app(app)

migrate.init_app(
    app,
    db
)

login_manager.init_app(app)

login_manager.login_view = "auth.login"

# WTF_CSRF_CHECK_DEFAULT = False (set BEFORE init_app, which only
# setdefault()s it) turns off CSRFProtect's own automatic check on
# every request - this app has several JS/fetch POST endpoints
# (search, location autocomplete, image upload/generation) with no
# CSRF token today, and those must keep working completely unchanged.
# Only routes explicitly decorated with extensions.require_csrf (the
# 4 property-mutation routes) are actually checked - see
# extensions.py's own module note for the full reasoning.
app.config["WTF_CSRF_CHECK_DEFAULT"] = False

csrf.init_app(app)


@app.errorhandler(CSRFError)
def handle_csrf_error(error):
    # One shared, friendly response for every require_csrf-protected
    # route, instead of Flask-WTF's raw 400 page - mirrors this
    # project's existing flash-message + redirect convention (e.g.
    # routes/property_routes.py's own validation-error handling)
    # rather than introducing a new error-page style.
    flash(
        "Your session could not be verified, so this request was not "
        "completed. Please try again.",
        "danger"
    )
    return redirect(request.referrer or url_for("home")), 400


# ============================================================
# MONGODB
# ============================================================

mongo_uri = os.getenv("MONGO_URI")

if not mongo_uri:
    raise RuntimeError(
        "MONGO_URI is not configured."
    )

mongo_service = MongoService(
    mongo_uri,
    server_selection_timeout_ms=int(os.getenv(
        "MONGO_SERVER_SELECTION_TIMEOUT_MS",
        "5000"
    )),
    connect_timeout_ms=int(os.getenv(
        "MONGO_CONNECT_TIMEOUT_MS",
        "5000"
    )),
)

property_service = PropertyService(
    mongo_service
)

app.extensions[
    "property_service"
] = property_service

property_service.ensure_indexes()

osm_location_service = OSMLocationService(
    mongo_service=mongo_service,
    nominatim_url=app.config["OSM_NOMINATIM_URL"],
    user_agent=app.config["OSM_USER_AGENT"],
    timeout_seconds=app.config["OSM_TIMEOUT"],
    cache_enabled=app.config["OSM_CACHE_ENABLED"],
    cache_ttl_seconds=app.config["OSM_CACHE_TTL_SECONDS"],
    min_score=app.config["OSM_MATCH_MIN_SCORE"],
    min_margin=app.config["OSM_MATCH_MIN_MARGIN"],
)

app.extensions[
    "osm_location_service"
] = osm_location_service

osm_location_service.ensure_indexes()



# ============================================================
# LOGIN MANAGER
# ============================================================

@login_manager.user_loader
def load_user(user_id):

    return db.session.get(
        User,
        int(user_id)
    )


# ============================================================
# GENERAL ROUTES
# ============================================================

@app.route("/")
def home():

    return render_template(
        "index.html"
    )


# ============================================================
# BLUEPRINTS
# ============================================================

app.register_blueprint(
    auth_bp
)

app.register_blueprint(
    property_bp
)

app.register_blueprint(
    search_bp
)

app.register_blueprint(
    design_bp
)


# ============================================================
# RUN
#
# debug mode is OFF unless FLASK_DEBUG is explicitly set to a truthy
# value - a hardcoded debug=True here would expose Werkzeug's
# interactive debugger (arbitrary code execution from the browser on
# any unhandled exception) to anything that can reach this process.
# Local development still works exactly as before: set FLASK_DEBUG=true
# in secret.env (or the shell environment) to re-enable it.
#
# flask_debug_enabled() itself lives in config_flags.py, a tiny module
# with zero dependencies beyond os - importing app.py triggers a real
# MongoDB connection (see "MONGODB" section above), so the debug-flag
# logic needs to be testable WITHOUT importing this file at all. See
# test_app_config.py.
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=flask_debug_enabled()
    )