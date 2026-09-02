import os

from dotenv import load_dotenv


# Load environment variables before reading configuration.
load_dotenv("secret.env")


class Config:
    SECRET_KEY = os.getenv("SECRET_KEY")

    SQLALCHEMY_DATABASE_URI = os.getenv(
        "DATABASE_URL",
        "sqlite:///site.db"
    )

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MAX_CONTENT_LENGTH = 16 * 1024 * 1024

    HF_API_KEY = os.getenv("HF_API_KEY")