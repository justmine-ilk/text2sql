import os
from langchain_core.language_models import BaseChatModel
from src.config import get_settings

settings = get_settings()


def get_llm() -> BaseChatModel:
    """Returns the LLM configured with Google AI Studio API Key."""
    api_key = settings.google_api_key or os.getenv("GOOGLE_API_KEY")
    model_name = settings.gemini_model or "gemini-2.5-flash"

    # Try ChatGoogleGenerativeAI
    try:
        from langchain_google_genai import ChatGoogleGenerativeAI
        return ChatGoogleGenerativeAI(
            model=model_name,
            google_api_key=api_key,
            temperature=settings.llm_temperature,
        )
    except Exception as e:
        print(f"[LLM] Fallback to ChatOpenAI with Google AI Studio endpoint due to: {e}")
        from langchain_openai import ChatOpenAI
        return ChatOpenAI(
            model=model_name,
            api_key=api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
            temperature=settings.llm_temperature,
        )
