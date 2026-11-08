"""Шлюз к языковым моделям: единая точка вызова LLM."""

from .gateway import (
    LLMError,
    LLMEvent,
    LLMProvider,
    OpenAICompatibleProvider,
    TextDelta,
    ToolCall,
    ToolCalls,
    make_provider,
)

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
