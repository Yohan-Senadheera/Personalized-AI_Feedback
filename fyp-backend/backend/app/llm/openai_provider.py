import os
import json
import time
from typing import Dict, Any
from openai import OpenAI


class OpenAILLM:
    def __init__(self):
        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is missing")
        self.client = OpenAI(api_key=api_key)
        self.model = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")

    def _extract_json(self, text: str) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise RuntimeError("Empty response from OpenAI")

        # direct JSON
        try:
            return json.loads(text)
        except Exception:
            pass

        # try to extract first {...} block
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                pass

        raise RuntimeError(f"Could not parse JSON from response: {text[:500]}")

    def generate_json(self, system: str, user: str) -> Dict[str, Any]:
        prompt = f"{user}\n\nReturn ONLY valid JSON. No markdown."

        last_err = None
        for attempt in range(4):
            try:
                resp = self.client.responses.create(
                    model=self.model,
                    instructions=system,
                    input=prompt,
                )
                text = getattr(resp, "output_text", "") or ""
                return self._extract_json(text)

            except Exception as e:
                last_err = e
                wait_s = 5 * (attempt + 1)
                print(f"⚠️ OpenAI call failed (attempt {attempt + 1}/4): {e}")
                time.sleep(wait_s)

        raise RuntimeError(str(last_err))