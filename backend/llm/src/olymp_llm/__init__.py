"""Шлюз к языковым моделям: единая точка вызова LLM для API и воркеров."""

from .gateway import (
    LLMError,
    LLMEvent,
    LLMProvider,
    OpenAICompatibleProvider,
    TextDelta,
    ToolCall,
    ToolCalls,
    Usage,
    complete,
    is_tool_markup,
    provider_from_env,
)

__all__ = [
    "LLMError",
    "LLMEvent",
    "LLMProvider",
    "OpenAICompatibleProvider",
    "TextDelta",
    "ToolCall",
    "ToolCalls",
    "Usage",
    "complete",
    "is_tool_markup",
    "provider_from_env",
]
