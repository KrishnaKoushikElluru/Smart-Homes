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

    # Cloudflare Workers AI (image generation - services/image_service.py).
    # Declared here for documentation parity with the other keys above;
    # services/image_service.py reads these itself via os.getenv, same as
    # HF_API_KEY was previously read directly rather than via this class.
    CLOUDFLARE_ACCOUNT_ID = os.getenv("CLOUDFLARE_ACCOUNT_ID")
    CLOUDFLARE_API_TOKEN = os.getenv("CLOUDFLARE_API_TOKEN")

    # Gemini (image prompt understanding - services/image_prompt_optimizer.py).
    # Same documentation-parity convention as above; the optimizer reads
    # this itself via os.getenv (passed in by services/image_service.py).
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")