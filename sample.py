import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# Print all environment variables
print("All Environment Variables:")
for key, value in os.environ.items():
    print(f"{key}: {value}")

# Specifically print HF API key
hf_api_key = os.getenv("HF_API_KEY")
print("\nHugging Face API Key:")
print(f"Raw Key: {hf_api_key}")
print(f"Key Length: {len(hf_api_key) if hf_api_key else 'No key found'}")