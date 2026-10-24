from flask import (
    Blueprint,
    render_template,
    redirect,
    url_for,
    flash
)

from flask_login import (
    login_user,
    logout_user
)

from flask_wtf import FlaskForm

from wtforms import (
    StringField,
    PasswordField,
    SubmitField
)

from wtforms.validators import (
    InputRequired,
    Length,
    Email,
    EqualTo
)

from extensions import db, bcrypt
from models import User


auth_bp = Blueprint(
    "auth",
    __name__
)


# ============================================================
# FORMS
# ============================================================

class SignupForm(FlaskForm):

    username = StringField(
        "Username",
        validators=[
            InputRequired(),
            Length(min=4, max=150)
        ]
    )

    email = StringField(
        "Email",
        validators=[
            InputRequired(),
            Email()
        ]
    )

    password = PasswordField(
        "Password",
        validators=[
            InputRequired(),
            Length(min=4, max=150),
            EqualTo(
                "confirm_password",
                message="Passwords must match."
            )
        ]
    )

    confirm_password = PasswordField(
        "Confirm Password",
        validators=[
            InputRequired()
        ]
    )

    submit = SubmitField(
        "Sign Up"
    )


class LoginForm(FlaskForm):

    username = StringField(
        "Username",
        validators=[
            InputRequired(),
            Length(min=4, max=150)
        ]
    )

    password = PasswordField(
        "Password",
        validators=[
            InputRequired(),
            Length(min=4, max=150)
        ]
    )

    submit = SubmitField(
        "Login"
    )


# ============================================================
# SIGNUP
# ============================================================

@auth_bp.route(
    "/signup",
    methods=["GET", "POST"]
)
def signup():

    form = SignupForm()

    if form.validate_on_submit():

        existing_username = User.query.filter_by(
            username=form.username.data
        ).first()

        if existing_username:

            flash(
                "Username already exists. "
                "Please choose a different one.",
                "danger"
            )

            return redirect(
                url_for("auth.signup")
            )

        existing_email = User.query.filter_by(
            email=form.email.data
        ).first()

        if existing_email:

            flash(
                "Email already exists. "
                "Please choose a different one.",
                "danger"
            )

            return redirect(
                url_for("auth.signup")
            )

        hashed_password = (
            bcrypt
            .generate_password_hash(
                form.password.data
            )
            .decode("utf-8")
        )

        new_user = User(
            username=form.username.data,
            email=form.email.data,
            password=hashed_password
        )

        db.session.add(new_user)
        db.session.commit()

        flash(
            "Account created successfully! "
            "Please log in.",
            "success"
        )

        return redirect(
            url_for("auth.login")
        )

    return render_template(
        "signup.html",
        form=form
    )


# ============================================================
# LOGIN
# ============================================================

@auth_bp.route(
    "/login",
    methods=["GET", "POST"]
)
def login():

    form = LoginForm()

    if form.validate_on_submit():

        user = User.query.filter_by(
            username=form.username.data
        ).first()

        if user and bcrypt.check_password_hash(
            user.password,
            form.password.data
        ):

            login_user(user)

            flash(
                "Login successful!",
                "success"
            )

            return redirect(
                url_for("home")
            )

        flash(
            "Invalid username or password.",
            "danger"
        )

    return render_template(
        "login.html",
        form=form
    )


# ============================================================
# LOGOUT
# ============================================================

@auth_bp.route("/logout")
def logout():

    logout_user()

    flash(
        "You have been logged out.",
        "info"
    )

    return redirect(
        url_for("auth.login")
    )