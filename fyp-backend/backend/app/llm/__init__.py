from backend.app.config import LLM_MODE
from backend.app.llm.gemini import GeminiLLM
from backend.app.llm.mock import MockLLM
from backend.app.llm.ollama import OllamaLLM


def get_llm():
    if LLM_MODE == "ollama":
        return OllamaLLM()
    if LLM_MODE == "gemini":
        return GeminiLLM()
    if LLM_MODE == "mock":
        return MockLLM()
    raise RuntimeError(f"Unsupported LLM_MODE: {LLM_MODE}")