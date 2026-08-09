"""Configurable LLM provider factory."""

try:
    from langchain_core.language_models.chat_models import BaseChatModel
except Exception:
    # Fallback typing for test environments without langchain
    BaseChatModel = object

from app.config import LLMProvider, get_settings


def get_llm(temperature: float | None = None, max_tokens: int | None = None) -> BaseChatModel:
    settings = get_settings()
    temp = temperature if temperature is not None else settings.llm_temperature
    tokens = max_tokens if max_tokens is not None else settings.llm_max_tokens

    if settings.llm_provider == LLMProvider.OPENAI:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.llm_model,
            temperature=temp,
            max_tokens=tokens,
            api_key=settings.openai_api_key or None,
        )

    if settings.llm_provider == LLMProvider.ANTHROPIC:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.llm_model,
            temperature=temp,
            max_tokens=tokens,
            api_key=settings.anthropic_api_key or None,
        )

    if settings.llm_provider == LLMProvider.GEMINI:
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=settings.llm_model,
            temperature=temp,
            max_output_tokens=tokens,
            google_api_key=settings.google_api_key or None,
        )

    if settings.llm_provider == LLMProvider.DEEPSEEK:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.llm_model or "deepseek-chat",
            temperature=temp,
            max_tokens=tokens,
            api_key=settings.deepseek_api_key or None,
            base_url="https://api.deepseek.com/v1",
        )

    if settings.llm_provider == LLMProvider.OLLAMA:
        from langchain_ollama import ChatOllama

        return ChatOllama(
            model=settings.llm_model or "llama3.3",
            temperature=temp,
            base_url=settings.ollama_base_url,
        )

    raise ValueError(f"Unsupported LLM provider: {settings.llm_provider}")
