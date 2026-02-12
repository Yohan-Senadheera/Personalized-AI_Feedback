import os
from dotenv import load_dotenv

# Load .env file
load_dotenv()

DATABASE_URL = os.getenv("DATABASE_URL", "")
REDIS_URL = os.getenv("REDIS_URL", "")
LLM_MODE = os.getenv("LLM_MODE", "mock").lower()

AWS_REGION = os.getenv("AWS_REGION", "ap-south-1")
AWS_PROFILE = os.getenv("AWS_PROFILE", "default")
BEDROCK_MODEL_ID = os.getenv("BEDROCK_MODEL_ID", "")
