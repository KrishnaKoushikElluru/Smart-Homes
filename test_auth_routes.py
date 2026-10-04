"""
Integration tests for routes/auth_routes.py (signup/login/logout).

Exercises the REAL Flask blueprint + REAL Flask-SQLAlchemy models
(extensions.db/models.User) against a throwaway in-memory SQLite
database (sqlite:///:memory:) created fresh per test and dropped in
tearDown - no real database file, no shared state between tests, and
completely independent of the project's real app.py/MongoDB (which
these tests never import or connect to).

CSRF is disabled for the bulk of these tests (the standard Flask-WTF
testing convention, matching test_property_routes.py's own
WTF_CSRF_ENABLED=False pattern) so they can focus on signup/login/
logout business logic without hand-building a token for every
request. CSRFStillAppliesToAuthFormsTests below is the one class that
leaves CSRF enabled, to prove signup/login's existing FlaskForm-based
CSRF protection is genuinely still active (not a new requirement -
FlaskForm has always auto-included a CSRF token field, see
templates/signup.html and templates/login.html's own
{{ form.hidden_tag() }}).
"""

import unittest

from flask import Flask, Blueprint
from flask_login import LoginManager

from extensions import db, bcrypt, csrf
from models import User
from routes.auth_routes import auth_bp


def make_test_app(csrf_enabled=False):
    app = Flask(__name__)
    app.config["SECRET_KEY"] = "test-secret"
    app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///:memory:"
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["WTF_CSRF_ENABLED"] = csrf_enabled
    # Matches the REAL app.py: the global CSRFProtect before_request
    # check is off (property-route protection is opt-in via
    # extensions.require_csrf instead - irrelevant to this file, which
    # never touches property_bp), so signup/login are protected ONLY
    # by FlaskForm's own built-in per-form CSRF validation - exactly
    # as before this session's CSRF work, unchanged.
    app.config["WTF_CSRF_CHECK_DEFAULT"] = False
    app.testing = True

    db.init_app(app)
    bcrypt.init_app(app)
    csrf.init_app(app)

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.route("/")
    def home():
        return "home"

    # A minimal @login_required-equivalent probe route, purely so
    # tests can confirm "is a session actually authenticated?" by
    # checking who the server thinks is logged in, without depending
    # on any other blueprint's real routes.
    from flask_login import login_required, current_user
    from flask import jsonify

    @app.route("/whoami")
    @login_required
    def whoami():
        return jsonify({"username": current_user.username})

    app.register_blueprint(auth_bp)
    return app


def create_user(app, username="existinguser", email="existing@example.com", password="correct-password"):
    with app.app_context():
        hashed = bcrypt.generate_password_hash(password).decode("utf-8")
        user = User(username=username, email=email, password=hashed)
        db.session.add(user)
        db.session.commit()
        return user.id


class AuthTestCase(unittest.TestCase):
    """Shared setUp/tearDown: fresh in-memory SQLite schema per test."""

    csrf_enabled = False

    def setUp(self):
        self.app = make_test_app(csrf_enabled=self.csrf_enabled)
        with self.app.app_context():
            db.create_all()
        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()


# ============================================================
# SIGNUP
# ============================================================

class SignupTests(AuthTestCase):

    def _signup_payload(self, **overrides):
        payload = {
            "username": "newuser",
            "email": "newuser@example.com",
            "password": "secure-pass",
            "confirm_password": "secure-pass",
        }
        payload.update(overrides)
        return payload

    def test_successful_signup_creates_a_user_and_redirects_to_login(self):
        response = self.client.post(
            "/signup", data=self._signup_payload(), follow_redirects=False
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

        with self.app.app_context():
            user = User.query.filter_by(username="newuser").first()
            self.assertIsNotNone(user)
            self.assertEqual(user.email, "newuser@example.com")

    def test_password_is_hashed_never_stored_plaintext(self):
        self.client.post("/signup", data=self._signup_payload())

        with self.app.app_context():
            user = User.query.filter_by(username="newuser").first()
            self.assertNotEqual(user.password, "secure-pass")
            # bcrypt's own hash format - confirms a real hash was
            # stored, not merely "some other string".
            self.assertTrue(user.password.startswith("$2b$") or user.password.startswith("$2a$"))
            self.assertTrue(bcrypt.check_password_hash(user.password, "secure-pass"))

    def test_duplicate_username_is_rejected(self):
        create_user(self.app, username="taken", email="first@example.com")

        response = self.client.post(
            "/signup",
            data=self._signup_payload(username="taken", email="second@example.com"),
            follow_redirects=True,
        )

        self.assertIn(b"Username already exists", response.data)
        with self.app.app_context():
            # Only the original user exists - signup did not create a
            # second row under the same username.
            self.assertEqual(User.query.filter_by(username="taken").count(), 1)

    def test_duplicate_email_is_rejected(self):
        create_user(self.app, username="first_user", email="taken@example.com")

        response = self.client.post(
            "/signup",
            data=self._signup_payload(username="second_user", email="taken@example.com"),
            follow_redirects=True,
        )

        self.assertIn(b"Email already exists", response.data)
        with self.app.app_context():
            self.assertIsNone(User.query.filter_by(username="second_user").first())

    def test_missing_required_fields_rejected(self):
        response = self.client.post(
            "/signup",
            data=self._signup_payload(username="", email="", password="", confirm_password=""),
        )

        self.assertEqual(response.status_code, 200)  # re-renders the form, no redirect
        with self.app.app_context():
            self.assertEqual(User.query.count(), 0)

    def test_mismatched_passwords_rejected(self):
        response = self.client.post(
            "/signup",
            data=self._signup_payload(password="secure-pass", confirm_password="different-pass"),
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(User.query.count(), 0)

    def test_invalid_email_format_rejected(self):
        response = self.client.post(
            "/signup", data=self._signup_payload(email="not-an-email")
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(User.query.count(), 0)

    def test_username_below_minimum_length_rejected(self):
        response = self.client.post(
            "/signup", data=self._signup_payload(username="ab")  # min length is 4
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(User.query.count(), 0)


# ============================================================
# LOGIN
# ============================================================

class LoginTests(AuthTestCase):

    def test_successful_login_redirects_home(self):
        create_user(self.app, username="gooduser", password="right-password")

        response = self.client.post(
            "/login",
            data={"username": "gooduser", "password": "right-password"},
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        self.assertIn("/", response.headers["Location"])

    def test_successful_login_establishes_an_authenticated_session(self):
        """The core "session state" check: after login, a SEPARATE
        subsequent request on the SAME client must be recognized as
        authenticated by Flask-Login, not just redirected once."""
        create_user(self.app, username="gooduser", password="right-password")

        self.client.post(
            "/login", data={"username": "gooduser", "password": "right-password"}
        )

        response = self.client.get("/whoami")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["username"], "gooduser")

    def test_incorrect_password_is_rejected(self):
        create_user(self.app, username="gooduser", password="right-password")

        response = self.client.post(
            "/login",
            data={"username": "gooduser", "password": "wrong-password"},
            follow_redirects=True,
        )

        self.assertIn(b"Invalid username or password", response.data)

        # No session was established - the probe route must still
        # require login.
        whoami_response = self.client.get("/whoami")
        self.assertEqual(whoami_response.status_code, 302)  # redirected to login, not 200

    def test_nonexistent_user_is_rejected(self):
        response = self.client.post(
            "/login",
            data={"username": "nobody_registered", "password": "whatever"},
            follow_redirects=True,
        )

        self.assertIn(b"Invalid username or password", response.data)

    def test_error_message_does_not_reveal_whether_username_exists(self):
        """Same generic message for 'wrong password' and 'no such
        user' - the EXISTING, already-good behavior this test locks
        in as a regression guard (prevents username enumeration)."""
        create_user(self.app, username="realuser", password="right-password")

        wrong_password_response = self.client.post(
            "/login",
            data={"username": "realuser", "password": "wrong"},
            follow_redirects=True,
        )
        nonexistent_response = self.client.post(
            "/login",
            data={"username": "nobody_registered", "password": "whatever"},
            follow_redirects=True,
        )

        self.assertIn(b"Invalid username or password", wrong_password_response.data)
        self.assertIn(b"Invalid username or password", nonexistent_response.data)


# ============================================================
# LOGOUT
# ============================================================

class LogoutTests(AuthTestCase):

    def test_authenticated_user_can_logout(self):
        create_user(self.app, username="gooduser", password="right-password")
        self.client.post(
            "/login", data={"username": "gooduser", "password": "right-password"}
        )

        response = self.client.get("/logout", follow_redirects=False)

        self.assertEqual(response.status_code, 302)
        self.assertIn("/login", response.headers["Location"])

    def test_logout_clears_the_authenticated_session_state(self):
        create_user(self.app, username="gooduser", password="right-password")
        self.client.post(
            "/login", data={"username": "gooduser", "password": "right-password"}
        )
        self.assertEqual(self.client.get("/whoami").status_code, 200)  # sanity: logged in

        self.client.get("/logout")

        response = self.client.get("/whoami")
        self.assertEqual(response.status_code, 302)  # no longer authenticated


# ============================================================
# CSRF (auth forms) - existing behavior, must still be intact
# ============================================================

class CSRFStillAppliesToAuthFormsTests(AuthTestCase):
    """Leaves CSRF genuinely ENABLED (unlike every other class above)
    to prove signup/login's existing FlaskForm-based CSRF protection
    is unaffected by this phase's property-route CSRF work - these
    forms were ALREADY protected (FlaskForm auto-includes a token),
    this is a regression guard, not a new requirement."""

    csrf_enabled = True

    def test_signup_without_a_csrf_token_is_rejected(self):
        response = self.client.post(
            "/signup",
            data={
                "username": "newuser", "email": "newuser@example.com",
                "password": "secure-pass", "confirm_password": "secure-pass",
            },
        )

        # FlaskForm's own CSRF check fails validate_on_submit() and
        # the form simply re-renders (200), rather than Flask-WTF's
        # CSRFProtect error handler - this is existing, unchanged
        # FlaskForm behavior, not routed through extensions.require_csrf
        # (which only decorates the 4 property-mutation routes).
        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            self.assertEqual(User.query.count(), 0)

    def test_signup_with_a_valid_csrf_token_succeeds(self):
        from flask_wtf.csrf import generate_csrf
        from flask import session

        with self.app.test_request_context():
            token = generate_csrf()
            seed = session["csrf_token"]

        with self.client.session_transaction() as sess:
            sess["csrf_token"] = seed

        response = self.client.post(
            "/signup",
            data={
                "username": "newuser", "email": "newuser@example.com",
                "password": "secure-pass", "confirm_password": "secure-pass",
                "csrf_token": token,
            },
            follow_redirects=False,
        )

        self.assertEqual(response.status_code, 302)
        with self.app.app_context():
            self.assertEqual(User.query.filter_by(username="newuser").count(), 1)


if __name__ == "__main__":
    unittest.main()
