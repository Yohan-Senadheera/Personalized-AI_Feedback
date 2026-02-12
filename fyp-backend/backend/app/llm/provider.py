from typing import Protocol, Dict, Any

class LLMProvider(Protocol):
    def generate_json(self, system: str, user: str) -> Dict[str, Any]:
        ...
