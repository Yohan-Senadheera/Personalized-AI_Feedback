import os
import json
import requests
from typing import Dict, Any


class OllamaLLM:
    def __init__(self):
        self.base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
        self.model = os.getenv("OLLAMA_MODEL", "qwen3:8b")

    def generate_json(self, system: str, user: str) -> Dict[str, Any]:
        prompt = f"{system}\n\n{user}\n\nReturn ONLY valid JSON. No markdown."

        r = requests.post(
            f"{self.base_url}/api/generate",
            json={
                "model": self.model,
                "prompt": prompt,
                "stream": False,
                "format": "json",
            },
            timeout=240,
        )
        r.raise_for_status()
        data = r.json()
        text = (data.get("response") or "").strip()

        if not text:
            raise RuntimeError("Ollama returned empty response")

        return json.loads(text)