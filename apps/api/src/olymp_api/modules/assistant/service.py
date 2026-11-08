"""Диалог с моделью: цикл вызовов инструментов и события для потока.

Текст переписки не логируем и не храним. Карточки и источники собирает сервер из результатов
инструментов, оговорку о проверке условий дописывает тоже он: это не зависит от модели.
"""

import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import structlog
from olymp_domain import squash
from olymp_domain.pii import mask_personal_data

from olymp_api.llm import LLMError, LLMProvider, TextDelta, ToolCalls

from .prompt import DIPLOMAS_NOTE, PROMPT_VERSION, SYSTEM_PROMPT
from .schemas import ChatMessage
from .tools import TOOLS, ToolContext, ToolResult, error, run_tool

log = structlog.get_logger()

# обращений к модели на сообщение: бесплатный бюджет мал, последнее — всегда без инструментов
MAX_ROUNDS = 4
MAX_TOOL_CALLS = 5
MAX_ENTITIES = 6
MAX_SOURCES = 4

STATUS_SEARCH = "Ищу в базе льгот…"
DISCLAIMER = "\n\nПроверь условия в правилах приёма вуза: они меняются каждый год."
SUGGESTIONS = [
    "Люблю программирование — какие олимпиады?",
    "Куда мои дипломы дают БВИ?",
    "План на год до ВШЭ",
]

Event = tuple[str, dict[str, Any]]
Spend = Callable[[], Awaitable[bool]]


def build_history(messages: list[ChatMessage], diplomas: list[str]) -> list[dict[str, Any]]:
    """Сообщения для модели: серверный промпт и текст без персональных данных."""
    system = SYSTEM_PROMPT
    if diplomas:
        system += "\n" + DIPLOMAS_NOTE.format(count=len(diplomas))
    return [
        {"role": "system", "content": system},
        *[{"role": m.role, "content": mask_personal_data(m.content)} for m in messages],
    ]


def mentioned(items: list[dict[str, Any]], answer: str, limit: int) -> list[dict[str, Any]]:
    """Сначала то, что названо в ответе; если ничего не названо — первые из найденных.

    Служебное поле match наружу не уходит, повторы убираются.
    """
    key = squash(answer)
    named = [i for i in items if any(m and squash(m) in key for m in i["match"])]
    seen: set[tuple[Any, ...]] = set()
    out: list[dict[str, Any]] = []
    for item in named or items:
        marker = (item.get("kind"), item.get("id"), item.get("url"))
        if marker not in seen:
            seen.add(marker)
            out.append({k: v for k, v in item.items() if k != "match"})
    return out[:limit]


async def conversation(
    provider: LLMProvider,
    messages: list[ChatMessage],
    ctx: ToolContext,
    spend: Spend,
) -> AsyncIterator[Event]:
    """События одного ответа: status, delta, entities, sources, done или error."""
    history = build_history(messages, ctx.diplomas)
    results: list[ToolResult] = []
    calls_used = rounds = 0
    answer = ""
    # весь текст, уже отправленный ученику: модель часто пишет «Сейчас найду…» до поиска
    # и продолжает после него — без разделителя фразы склеивались («найду.Вот»)
    shown = ""
    started = time.perf_counter()

    for round_number in range(MAX_ROUNDS):
        if not await spend():
            yield "error", {"code": "budget"}
            return
        rounds += 1
        last = round_number == MAX_ROUNDS - 1 or calls_used >= MAX_TOOL_CALLS
        answer = ""
        calls: tuple[Any, ...] = ()
        try:
            async for event in provider.stream(history, [] if last else TOOLS):
                if isinstance(event, TextDelta):
                    text = event.text
                    if not answer and shown and not shown[-1].isspace():
                        text = "\n\n" + text.lstrip()
                    answer += event.text
                    shown += text
                    yield "delta", {"text": text}
                elif isinstance(event, ToolCalls):
                    calls = event.calls
        except LLMError as exc:
            log.warning("assistant_llm_failed", reason=str(exc), rounds=rounds)
            yield "error", {"code": "unavailable"}
            return
        if not calls or last:
            break

        yield "status", {"text": STATUS_SEARCH}
        history.append(
            {
                "role": "assistant",
                "content": answer,
                "tool_calls": [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {"name": call.name, "arguments": call.arguments},
                    }
                    for call in calls
                ],
            }
        )
        for call in calls:
            calls_used += 1
            result = (
                await run_tool(call.name, call.arguments, ctx)
                if calls_used <= MAX_TOOL_CALLS
                else error("Лимит поисков исчерпан: отвечай по тому, что уже найдено")
            )
            results.append(result)
            history.append({"role": "tool", "tool_call_id": call.id, "content": result.content})

    if not answer.strip():
        yield "error", {"code": "empty"}
        return
    if calls_used:
        yield "delta", {"text": DISCLAIMER}
    entities = [item for result in results for item in result.entities]
    sources = [item for result in results for item in result.sources]
    yield "entities", {"entities": mentioned(entities, answer, MAX_ENTITIES)}
    yield "sources", {"sources": mentioned(sources, answer, MAX_SOURCES)}
    yield "done", {"message_id": uuid.uuid4().hex}
    log.info(
        "assistant_chat",
        prompt=PROMPT_VERSION,
        model=provider.model_label,
        rounds=rounds,
        tools=calls_used,
        chars=len(answer),
        seconds=round(time.perf_counter() - started, 2),
    )
