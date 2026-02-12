from backend.app.config import LLM_MODE
from backend.app.llm.mock import MockLLM
from backend.app.llm.gemini import GeminiLLM

def get_llm():
    if LLM_MODE == "gemini":
        return GeminiLLM()
    return MockLLM()
