from dotenv import load_dotenv
import os

# Load .env file
load_dotenv()

# Print values
print(f"OpenAI API Key: {os.getenv('OPENAI_API_KEY')}")
print(f"Flask Secret Key: {os.getenv('FLASK_SECRET_KEY')}")
