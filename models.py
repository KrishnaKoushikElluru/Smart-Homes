from flask_login import UserMixin

from extensions import db


class User(UserMixin, db.Model):

    __tablename__ = "user"

    id = db.Column(
        db.Integer,
        primary_key=True
    )

    username = db.Column(
        db.String(150),
        nullable=False,
        unique=True
    )

    email = db.Column(
        db.String(150),
        nullable=False,
        unique=True
    )

    password = db.Column(
        db.String(200),
        nullable=False
    )

    def __repr__(self):

        return f"<User {self.username}>"