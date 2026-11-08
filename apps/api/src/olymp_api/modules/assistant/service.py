"""Диалог с моделью: цикл вызовов инструментов и события для потока.

Текст переписки не логируем и не храним. Карточки и источники собирает сервер из результатов
инструментов, оговорку о проверке условий дописывает тоже он: это не зависит от модели.
"""

import re
import time
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any

import structlog
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


def words(value: str) -> str:
    """Слова через пробел и с пробелами по краям: так ищутся целые слова, а не куски.

    Склеенные строки давали ложные совпадения коротких названий («НТО» в «он то»).
    """
    return " " + " ".join(re.findall(r"[^\W_]+", value.lower().replace("ё", "е"))) + " "


def acronym(value: str) -> str | None:
    """«Московская олимпиада школьников» → «мош»: модель часто пишет сокращение."""
    parts = [w for w in words(value).split() if len(w) > 2 and w.isalpha()]
    return "".join(w[0] for w in parts) if len(parts) >= 3 else None


def position(item: dict[str, Any], key: str) -> int | None:
    """Где в ответе впервые названа карточка или источник; None — не названы."""
    found: list[int] = []
    for name in item["match"]:
        if not name:
            continue
        for variant in (words(name), f" {acronym(name)} " if acronym(name) else None):
            if variant and variant.strip() and (at := key.find(variant)) >= 0:
                found.append(at)
    return min(found) if found else None


def mentioned(items: list[dict[str, Any]], answer: str, limit: int) -> list[dict[str, Any]]:
    """Сначала то, что названо в ответе, в порядке упоминания; если ничего не названо — первые
    из найденных.

    У одной олимпиады бывает несколько профилей: остаётся тот, чей профиль (hint) тоже назван.
    Служебное поле match наружу не уходит, повторы убираются.
    """
    key = words(answer)
    best: dict[tuple[Any, ...], tuple[tuple[int, int, int], dict[str, Any]]] = {}
    for order, item in enumerate(items):
        at = position(item, key)
        hint = item.get("hint")
        hint_named = bool(hint) and words(str(hint)) in key
        rank = (0 if at is not None else 1, 0 if hint_named else 1, order)
        marker = (item.get("kind"), item.get("id"), item.get("url"))
        if marker not in best or rank < best[marker][0]:
            best[marker] = (rank, {**item, "_at": at})
    chosen = [entry for _, entry in sorted(best.values(), key=lambda v: v[0][2])]
    named = sorted((e for e in chosen if e["_at"] is not None), key=lambda e: e["_at"])
    return [{k: v for k, v in e.items() if k not in {"match", "_at"}} for e in (named or chosen)][
        :limit
    ]


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
