"""Поддельный провайдер для тестов: выдаёт заранее заданные ответы и запоминает запросы."""

from collections.abc import AsyncIterator, Sequence
from typing import Any

from .gateway import LLMError, LLMEvent


class FakeProvider:
    """Каждый вызов stream() проигрывает следующий раунд сценария. Исключение в раунде
    выбрасывается на этом месте: так проверяется сбой провайдера."""

    model_label = "fake"

    def __init__(self, rounds: Sequence[Sequence[LLMEvent | Exception]]) -> None:
        self.rounds = list(rounds)
        self.requests: list[dict[str, Any]] = []

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[LLMEvent]:
        self.requests.append({"messages": messages, "tools": tools})
        if not self.rounds:
            raise LLMError("сценарий закончился")
        for item in self.rounds.pop(0):
            if isinstance(item, Exception):
                raise item
            yield item
