import os
import json
import time
from typing import Dict, Any
import anthropic


class ClaudeLLM:
    def __init__(self):
        api_key = os.getenv("ANTHROPIC_API_KEY", "")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY is missing")

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = os.getenv("ANTHROPIC_MODEL", "claude-3-5-sonnet-latest")

    def _extract_json(self, text: str) -> Dict[str, Any]:
        text = (text or "").strip()
        if not text:
            raise RuntimeError("Empty response from Claude")

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

        raise RuntimeError(f"Could not parse JSON from Claude response: {text[:500]}")

    def generate_json(self, system: str, user: str) -> Dict[str, Any]:
        prompt = f"{user}\n\nReturn ONLY valid JSON. No markdown."

        last_err = None
        for attempt in range(4):
            try:
                resp = self.client.messages.create(
                    model=self.model,
                    max_tokens=4000,
                    system=system,
                    messages=[
                        {"role": "user", "content": prompt}
                    ],
                )

                text_parts = []
                for block in resp.content:
                    if getattr(block, "type", "") == "text":
                        text_parts.append(block.text)

                text = "\n".join(text_parts).strip()
                return self._extract_json(text)

            except Exception as e:
                last_err = e
                wait_s = 5 * (attempt + 1)
                print(f"⚠️ Claude call failed (attempt {attempt + 1}/4): {e}")
                time.sleep(wait_s)

        raise RuntimeError(str(last_err))
