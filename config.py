import os
from dotenv import load_dotenv

# Load .env so BASE_OUTPUT_DIR can be configured there
load_dotenv()

# Central place for simple configuration values used across modules
BASE_OUTPUT_DIR = os.getenv("BASE_OUTPUT_DIR", "./outputs")

# Ensure output directory exists early
os.makedirs(BASE_OUTPUT_DIR, exist_ok=True)
