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