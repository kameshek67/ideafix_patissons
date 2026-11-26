"""Шлюз LLM для API. Сам клиент живёт в пакете olymp_llm (backend/llm), здесь — только
настройка из Settings. Импорты из olymp_api.llm сохранены, чтобы не менять код модулей."""

from urllib.parse import urlparse

from olymp_llm import (
    LLMError,
    LLMEvent,
    LLMProvider,
    OpenAICompatibleProvider,
    TextDelta,
    ToolCall,
    ToolCalls,
    Usage,
    is_tool_markup,
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
    "Usage",
    "is_tool_markup",
    "make_provider",
    "provider_name",
]


def make_provider(
    settings: Settings,
    *,
    profile: str | None = None,
    model: str | None = None,
    include_usage: bool = False,
) -> LLMProvider | None:
    """Провайдер из настроек; None — помощник выключен.

    Оценка выбирает провайдера и модель: profile — имя из llm_profiles, model — подмена модели
    (резервная при этом не используется: в отчёте должна быть одна модель). include_usage
    просит у сервера расход токенов.
    """
    base_url: str | None
    api_key: str | None
    name: str | None
    fallback: str | None
    if profile is not None:
        chosen = settings.llm_profiles.get(profile)
        if chosen is None:
            return None
        base_url, api_key = chosen.base_url, chosen.api_key
        name, fallback = model or chosen.model, None if model else chosen.fallback_model
    else:
        base_url, api_key = settings.llm_base_url, settings.llm_api_key
        name = model or settings.llm_model
        fallback = None if model else settings.llm_fallback_model
    if not (settings.llm_enabled and base_url and api_key and name):
        return None
    return OpenAICompatibleProvider(
        base_url,
        api_key,
        name,
        fallback_model=fallback,
        timeout=settings.llm_timeout,
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
        top_p=settings.llm_top_p,
        deny_data_collection=settings.llm_deny_data_collection,
        include_usage=include_usage,
    )


def provider_name(settings: Settings, profile: str | None = None) -> str:
    """Как назвать провайдера в отчёте: имя профиля или хост адреса."""
    if profile is not None:
        return profile
    base_url = settings.llm_base_url or ""
    return urlparse(base_url).hostname or base_url or "—"
