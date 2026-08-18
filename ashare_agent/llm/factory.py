from langchain_deepseek import ChatDeepSeek

from ashare_agent.config import get_settings


def create_default_model() -> ChatDeepSeek:
    settings = get_settings()

    return ChatDeepSeek(
        model=settings.deepseek_model,
        api_key=(settings.deepseek_api_key.get_secret_value()),
        api_base=settings.deepseek_api_base,
        timeout=settings.llm_timeout,
        max_retries=settings.llm_max_retries,
        extra_body={"thinking": {"type": "disabled"}},
    )
