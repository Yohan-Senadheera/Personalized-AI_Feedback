import os, json
from typing import Dict, Any
from google import genai

class GeminiLLM:
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY", "")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY is missing")
        self.client = genai.Client(api_key=api_key)
        self.model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")

    def generate_json(self, system: str, user: str) -> Dict[str, Any]:
        prompt = f"{system}\n\n{user}\n\nReturn ONLY valid JSON. No markdown."
        resp = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            # Ask for JSON output
            config={"response_mime_type": "application/json"},
        )
        text = (resp.text or "").strip()
        return json.loads(text)
