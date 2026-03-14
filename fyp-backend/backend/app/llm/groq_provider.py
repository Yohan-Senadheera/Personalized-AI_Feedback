import os
import json
import time
from typing import Dict, Any
from groq import Groq


class GroqLLM:
    def __init__(self):
        api_key = os.getenv("GROQ_API_KEY", "")
        if not api_key:
            raise RuntimeError("GROQ_API_KEY is missing")

        self.client = Groq(api_key=api_key)
        self.model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

    def _extract_json(self, text: str) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise RuntimeError("Empty response from Groq")

        try:
            return json.loads(text)
        except Exception:
            pass

        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(text[start:end + 1])
            except Exception:
                pass

        raise RuntimeError(f"Could not parse JSON from Groq response: {text[:500]}")

    def generate_json(self, system: str, user: str) -> Dict[str, Any]:
        prompt = f"{user}\n\nReturn ONLY valid JSON. No markdown."

        last_err = None
        for attempt in range(4):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model,
                    temperature=0.2,
                    messages=[
                        {"role": "system", "content": system},
                        {"role": "user", "content": prompt},
                    ],
                )

                text = resp.choices[0].message.content or ""
                return self._extract_json(text)

            except Exception as e:
                last_err = e
                wait_s = 5 * (attempt + 1)
                print(f"⚠️ Groq call failed (attempt {attempt + 1}/4): {e}")
                time.sleep(wait_s)

        raise RuntimeError(str(last_err))
