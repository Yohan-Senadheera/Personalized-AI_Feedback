import os
from dotenv import load_dotenv
import google.generativeai as genai

load_dotenv()  # loads .env from current folder

api_key = os.getenv("GEMINI_API_KEY")
model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-pro")

if not api_key:
    raise RuntimeError("GEMINI_API_KEY is missing. Put it in .env or set env var.")

genai.configure(api_key=api_key)

model = genai.GenerativeModel(model_name)
resp = model.generate_content("Say hello in one short sentence.")
print(resp.text)
