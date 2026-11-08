"""Шлюз LLM для API. Сам клиент живёт в пакете olymp_llm (packages/llm), здесь — только
настройка из Settings. Импорты из olymp_api.llm сохранены, чтобы не менять код модулей."""

from olymp_llm import (
    LLMError,
    LLMEvent,
    LLMProvider,
    OpenAICompatibleProvider,
    TextDelta,
    ToolCall,
    ToolCalls,
)

from olymp_api.settings import Settings

__all__ = [
    "LLMError",
    "LLMEvent",
    "LLMProvider",
    "OpenAICompatibleProvider",
    "TextDelta",
    "ToolCall",
    "ToolCalls",
    "make_provider",
]


def make_provider(settings: Settings) -> LLMProvider | None:
    """Провайдер из настроек; None — помощник выключен."""
    if not (
        settings.llm_enabled
        and settings.llm_base_url
        and settings.llm_api_key
        and settings.llm_model
    ):
        return None
    return OpenAICompatibleProvider(
        settings.llm_base_url,
        settings.llm_api_key,
        settings.llm_model,
        fallback_model=settings.llm_fallback_model,
        timeout=settings.llm_timeout,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
        top_p=settings.llm_top_p,
        deny_data_collection=settings.llm_deny_data_collection,
    )
