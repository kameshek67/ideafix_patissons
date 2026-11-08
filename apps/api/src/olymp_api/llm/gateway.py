"""OpenAI-совместимый клиент: поток, вызовы инструментов, повторы и резервная модель.

Текст запросов не логируем (F-02). Повторяем и переходим на резервную модель только до первого
полученного события: иначе пользователь увидел бы ответ дважды.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from dataclasses import dataclass
from typing import Any, Protocol

import httpx
import structlog

from olymp_api.settings import Settings

log = structlog.get_logger()

ATTEMPTS_PER_MODEL = 2
RETRY_DELAY = 0.5


@dataclass(frozen=True)
class TextDelta:
    text: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # JSON-строка от модели: недоверенные данные


@dataclass(frozen=True)
class ToolCalls:
    calls: tuple[ToolCall, ...]


LLMEvent = TextDelta | ToolCalls


class LLMError(Exception):
    """Провайдер недоступен. В тексте только статус: без содержимого запроса и ответа."""


class _Retryable(LLMError):
    """Сбой, после которого есть смысл повторить запрос или сменить модель."""


class LLMProvider(Protocol):
    @property
    def model_label(self) -> str: ...

    def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[LLMEvent]: ...


class OpenAICompatibleProvider:
    def __init__(
        self,
        base_url: str,
        api_key: str,
        model: str,
        *,
        fallback_model: str | None = None,
        timeout: float = 30,
        max_tokens: int = 1500,
        deny_data_collection: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.api_key = api_key
        self.models = [model, *([fallback_model] if fallback_model else [])]
        self.timeout = timeout
        self.max_tokens = max_tokens
        # параметр есть только у OpenRouter, другие серверы могут отвергнуть лишнее поле
        self.deny_data_collection = deny_data_collection and "openrouter.ai" in base_url
        self.transport = transport

    @property
    def model_label(self) -> str:
        return self.models[0]

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[LLMEvent]:
        for model in self.models:
            for attempt in range(ATTEMPTS_PER_MODEL):
                started = False
                try:
                    async for event in self._stream_once(model, messages, tools):
                        started = True
                        yield event
                    return
                except _Retryable as exc:
                    if started:
                        raise LLMError(str(exc)) from None
                    log.warning("llm_retry", model=model, attempt=attempt, reason=str(exc))
                if attempt + 1 < ATTEMPTS_PER_MODEL:
                    await asyncio.sleep(RETRY_DELAY)
        raise LLMError("все модели недоступны")

    def _body(
        self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": True,
            "max_tokens": self.max_tokens,
        }
        if tools:
            body["tools"] = tools
        if self.deny_data_collection:
            body["provider"] = {"data_collection": "deny"}
        return body

    async def _stream_once(
        self, model: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[LLMEvent]:
        headers = {"Authorization": f"Bearer {self.api_key}"}
        pending: dict[int, dict[str, str]] = {}
        try:
            async with (
                httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client,
                client.stream(
                    "POST", self.url, json=self._body(model, messages, tools), headers=headers
                ) as response,
            ):
                if response.status_code in (401, 403):
                    raise LLMError(f"провайдер отказал в доступе: {response.status_code}")
                if response.status_code != 200:
                    raise _Retryable(f"статус {response.status_code}")
                async for line in response.aiter_lines():
                    # строки-комментарии вида «: OPENROUTER PROCESSING» держат соединение
                    if not line.startswith("data:"):
                        continue
                    payload = line.removeprefix("data:").strip()
                    if payload == "[DONE]":
                        break
                    for event in _events(json.loads(payload), pending):
                        yield event
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            raise _Retryable(type(exc).__name__) from None
        except json.JSONDecodeError:
            raise _Retryable("неразборчивый ответ") from None
        if pending:
            yield ToolCalls(
                tuple(
                    ToolCall(call["id"], call["name"], call["arguments"])
                    for _, call in sorted(pending.items())
                )
            )


def _events(chunk: dict[str, Any], pending: dict[int, dict[str, str]]) -> list[LLMEvent]:
    """Разбирает кусок потока; части вызовов инструментов копятся в pending по индексу."""
    if "error" in chunk:
        raise _Retryable("ошибка в потоке")
    events: list[LLMEvent] = []
    for choice in chunk.get("choices") or []:
        delta = choice.get("delta") or {}
        if text := delta.get("content"):
            events.append(TextDelta(text))
        for part in delta.get("tool_calls") or []:
            call = pending.setdefault(part.get("index", 0), {"id": "", "name": "", "arguments": ""})
            function = part.get("function") or {}
            call["id"] = part.get("id") or call["id"]
            call["name"] = function.get("name") or call["name"]
            call["arguments"] += function.get("arguments") or ""
    return events


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
        deny_data_collection=settings.llm_deny_data_collection,
    )
