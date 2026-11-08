"""Шлюз к языковым моделям (ADR 0010): единая точка вызова LLM для API и воркеров."""

from .gateway import (
    LLMError,
    LLMEvent,
    LLMProvider,
    OpenAICompatibleProvider,
    TextDelta,
    ToolCall,
    ToolCalls,
    complete,
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
    "complete",
    "provider_from_env",
]
