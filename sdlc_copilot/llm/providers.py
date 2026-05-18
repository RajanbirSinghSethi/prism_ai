from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from sdlc_copilot.config import Settings


def build_chat_model(settings: Settings, temperature: float = 0.1) -> BaseChatModel:
    provider = settings.llm_provider.lower().strip()

    if provider == "openrouter":
        if not settings.openrouter_api_key:
            raise ValueError("OPENROUTER_API_KEY is required when LLM_PROVIDER=openrouter")
        return ChatOpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            model=settings.openrouter_model,
            temperature=temperature,
            default_headers={
                "HTTP-Referer": "http://localhost:8000",
                "X-Title": settings.app_name,
            },
        )

    if provider == "groq":
        if not settings.groq_api_key:
            raise ValueError("GROQ_API_KEY is required when LLM_PROVIDER=groq")
        return ChatOpenAI(
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
            model=settings.groq_model,
            temperature=temperature,
        )

    raise ValueError(f"Unsupported LLM_PROVIDER '{settings.llm_provider}'. Use openrouter or groq.")
