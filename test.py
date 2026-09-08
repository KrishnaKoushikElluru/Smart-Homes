from dotenv import load_dotenv
import os

# Load .env file
load_dotenv()

# Print whether secrets are set, without exposing their values
print(f"OpenAI API Key set: {bool(os.getenv('OPENAI_API_KEY'))}")
print(f"Flask Secret Key set: {bool(os.getenv('FLASK_SECRET_KEY'))}")
