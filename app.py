import os

from flask import (
    Flask,
    render_template
)

from dotenv import load_dotenv

from extensions import (
    db,
    bcrypt,
    migrate,
    login_manager
)

import extensions

from models import User
from services.mongo_service import MongoService
from services.property_services import PropertyService
from services.osm_location_service import OSMLocationService
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

# ============================================================
# MONGODB
# ============================================================

mongo_uri = os.getenv("MONGO_URI")

if not mongo_uri:
    raise RuntimeError(
        "MONGO_URI is not configured."
    )

mongo_service = MongoService(
    mongo_uri
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
# ============================================================

if __name__ == "__main__":

    app.run(
        debug=True
    )