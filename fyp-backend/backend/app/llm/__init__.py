from backend.app.config import LLM_MODE
from backend.app.llm.gemini import GeminiLLM
from backend.app.llm.mock import MockLLM
from backend.app.llm.ollama import OllamaLLM
from backend.app.llm.openai_provider import OpenAILLM
from backend.app.llm.claude_provider import ClaudeLLM
from backend.app.llm.groq_provider import GroqLLM


def get_llm():
    mode = (LLM_MODE or "").strip().lower()

    if mode == "ollama":
        return OllamaLLM()
    if mode == "gemini":
        return GeminiLLM()
    if mode == "openai":
        return OpenAILLM()
    if mode == "claude":
        return ClaudeLLM()
    if mode == "groq":
        return GroqLLM()
    if mode == "mock":
        return MockLLM()

    raise RuntimeError(f"Unsupported LLM_MODE: {LLM_MODE}")
