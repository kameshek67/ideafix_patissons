"""Диалог с моделью: цикл вызовов инструментов и события для потока.

Текст переписки не логируем и не храним. Карточки и источники собирает сервер из результатов
инструментов, оговорку о проверке условий отдаёт тоже он: это не зависит от модели.

Порядок событий одного ответа:
  status (по инструменту, на каждый поиск) … status «Пишу ответ…» → status «Проверяю ответ…»
  → delta (кусками по абзацам) → notice (только если были поиски) → entities → sources
  → done (с подписанным контекстом диалога); при сбое — error.
Текст раунда, который закончился вызовом инструментов («Сейчас найду…»), ученику не показывается
и в историю модели не попадает. Финальный ответ собирается целиком и проходит через review() —
проверку фактов (V2), поэтому ученик не видит ни слова непроверенного ответа.
"""

import re
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import structlog
from olymp_domain.pii import mask_personal_data

from olymp_api.llm import LLMError, LLMProvider, TextDelta, ToolCalls

from .context import DialogContext, advance, encode
from .factcheck import Facts, Violation, Vocabulary, check, cut
from .prompt import CONTEXT_NOTE, DIPLOMAS_NOTE, FIX_NOTE, PROMPT_VERSION, SYSTEM_PROMPT
from .schemas import ChatMessage
from .tools import TOOLS, ToolContext, ToolResult, error, run_tool

log = structlog.get_logger()

# обращений к модели на сообщение: бесплатный бюджет мал, последнее — всегда без инструментов
MAX_ROUNDS = 4
MAX_TOOL_CALLS = 5
MAX_ENTITIES = 6
MAX_SOURCES = 4

# статусы — по имени инструмента, без слов ученика и аргументов модели
STATUS_SEARCH = "Ищу в базе льгот…"
STATUS_TOOLS = {
    "find_profiles": "Подбираю олимпиады по интересам…",
    "find_olympiads": "Ищу олимпиаду…",
    "olympiad_card": "Смотрю, как устроена олимпиада…",
    "universities_for_olympiad": "Ищу вузы для олимпиады…",
    "olympiads_for_program": "Ищу олимпиады для направления…",
    "benefit_conditions": "Смотрю условия льготы…",
    "explain_rule": "Смотрю правила приёма…",
    "match_diplomas": "Проверяю твои дипломы…",
    "list_universities": "Смотрю список вузов…",
}
STATUS_WRITING = "Пишу ответ…"
STATUS_CHECKING = "Проверяю ответ…"
# повтор не помог и вырезано всё — честное «нет данных» вместо догадок
NO_DATA_ANSWER = (
    "По этому вопросу в базе нет данных. Проверь на официальном сайте олимпиады или в правилах "
    "приёма вуза, а я могу поискать другие олимпиады или вузы."
)
CUT_NOTE = "Остального в базе нет: проверь на официальном сайте олимпиады или в правилах приёма."
MAX_FIX_ITEMS = 8
# оговорка — отдельным событием notice: не часть ответа и в историю модели не попадает
DISCLAIMER = "Проверь условия в правилах приёма вуза: они меняются каждый год."
SUGGESTIONS = [
    "Люблю программирование — какие олимпиады?",
    "Куда мои дипломы дают БВИ?",
    "План на год до ВШЭ",
]

Event = tuple[str, dict[str, Any]]
Spend = Callable[[], Awaitable[bool]]


def build_history(
    messages: list[ChatMessage], diplomas: list[str], notes: list[str] | None = None
) -> list[dict[str, Any]]:
    """Сообщения для модели: серверный промпт, сводка фактов прошлых ответов из проверенного
    контекста и текст без персональных данных."""
    system = SYSTEM_PROMPT
    if diplomas:
        system += "\n" + DIPLOMAS_NOTE.format(count=len(diplomas))
    if notes:
        system += "\n\n" + CONTEXT_NOTE + "".join(f"\n- {note}" for note in notes)
    return [
        {"role": "system", "content": system},
        *[{"role": m.role, "content": mask_personal_data(m.content)} for m in messages],
    ]


def tool_status(name: str) -> str:
    return STATUS_TOOLS.get(name, STATUS_SEARCH)


@dataclass
class Review:
    """Всё, что нужно проверке ответа: факты диалога, словарь и возможность одного повтора."""

    provider: LLMProvider
    history: list[dict[str, Any]]
    spend: Spend
    facts: Facts
    vocab: Vocabulary
    retried: bool = False


def collect_facts(
    results: list[ToolResult], messages: list[ChatMessage], dialog: DialogContext | None
) -> Facts:
    """Разрешённое в ответе: результаты инструментов этого ответа, реплики ученика, сводка
    проверенного контекста (без id) и прошлые ответы, которые сервер сам проверил и отдал."""
    facts = Facts.collect(
        (r.content for r in results), (m.content for m in messages if m.role == "user")
    )
    if dialog:
        for line in dialog.fact_lines():
            facts.add_text(line)
        for m in messages:
            if m.role == "assistant" and dialog.verified(m.content):
                facts.add_text(m.content)
    return facts


def fix_request(problems: list[Violation]) -> str:
    items = list(dict.fromkeys(f"«{p.fragment}»" for p in problems))[:MAX_FIX_ITEMS]
    return FIX_NOTE.format(items=", ".join(items))


def log_problems(stage: str, problems: list[Violation]) -> None:
    """Только число нарушений и их виды: текст ответа в логи не попадает."""
    kinds = Counter(p.kind for p in problems)
    log.info("assistant_factcheck", stage=stage, violations=len(problems), kinds=dict(kinds))


async def regenerate(checker: Review, answer: str, problems: list[Violation]) -> str:
    """Один повтор финального ответа без инструментов; нет бюджета или сбой — пустая строка."""
    if not await checker.spend():
        return ""
    checker.retried = True
    history = [
        *checker.history,
        {"role": "assistant", "content": answer},
        {"role": "system", "content": fix_request(problems)},
    ]
    text = ""
    try:
        async for event in checker.provider.stream(history, []):
            if isinstance(event, TextDelta):
                text += event.text
    except LLMError as exc:
        log.warning("assistant_llm_failed", reason=str(exc), stage="factcheck")
        return ""
    return text.strip()


async def review(answer: str, checker: Review) -> str:
    """Проверка готового ответа до показа ученику (V2, V4): выдуманные вузы и олимпиады, числа
    не из данных, «обычно…» про олимпиаду. Нарушения — один повтор генерации; повтор тоже
    с нарушениями — предложения с ними вырезаются; вырезано всё — «в базе нет данных»."""
    problems = check(answer, checker.facts, checker.vocab)
    if not problems:
        return answer
    log_problems("answer", problems)
    retry = await regenerate(checker, answer, problems)
    if retry:
        again = check(retry, checker.facts, checker.vocab)
        if not again:
            return retry
        log_problems("retry", again)
        answer, problems = retry, again
    kept = cut(answer, problems)
    return f"{kept}\n\n{CUT_NOTE}" if kept else NO_DATA_ANSWER


def chunks(text: str) -> list[str]:
    """Ответ кусками по абзацам: склеенные куски дают ровно исходный текст."""
    return [part for part in re.split(r"(?<=\n\n)", text) if part]


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
    *,
    key: bytes,
    dialog: DialogContext | None = None,
    vocab: Vocabulary | None = None,
) -> AsyncIterator[Event]:
    """События одного ответа: status, delta, notice, entities, sources, done или error.

    dialog — проверенный контекст прошлых ответов: его id сразу доступны инструментам, сводка
    фактов идёт в системное сообщение. key подписывает новый контекст в событии done.
    """
    if dialog:
        dialog.seed(ctx)
    history = build_history(messages, ctx.diplomas, dialog.notes if dialog else None)
    results: list[ToolResult] = []
    calls_used = rounds = 0
    answer = ""
    started = time.perf_counter()

    for round_number in range(MAX_ROUNDS):
        if not await spend():
            yield "error", {"code": "budget"}
            return
        rounds += 1
        last = round_number == MAX_ROUNDS - 1 or calls_used >= MAX_TOOL_CALLS
        # текст раунда копится: станет ответом, только если раунд закончится без инструментов
        answer = ""
        writing = False
        calls: tuple[Any, ...] = ()
        try:
            async for event in provider.stream(history, [] if last else TOOLS):
                if isinstance(event, TextDelta):
                    answer += event.text
                    if not writing and answer.strip():
                        writing = True
                        yield "status", {"text": STATUS_WRITING}
                elif isinstance(event, ToolCalls):
                    calls = event.calls
        except LLMError as exc:
            log.warning("assistant_llm_failed", reason=str(exc), rounds=rounds)
            yield "error", {"code": "unavailable"}
            return
        if not calls or last:
            break

        # «Сейчас найду…» — не ответ: в историю идут только вызовы, без текста раунда
        history.append(
            {
                "role": "assistant",
                "content": None,
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
        shown_status = ""
        for call in calls:
            calls_used += 1
            if calls_used <= MAX_TOOL_CALLS:
                status = tool_status(call.name)
                if status != shown_status:
                    shown_status = status
                    yield "status", {"text": status}
                result = await run_tool(call.name, call.arguments, ctx)
            else:
                result = error("Лимит поисков исчерпан: отвечай по тому, что уже найдено")
            results.append(result)
            history.append({"role": "tool", "tool_call_id": call.id, "content": result.content})

    answer = answer.strip()
    if not answer:
        yield "error", {"code": "empty"}
        return
    yield "status", {"text": STATUS_CHECKING}
    facts = collect_facts(results, messages, dialog)
    checker = Review(provider, history, spend, facts, vocab or Vocabulary())
    answer = (await review(answer, checker)).strip()
    for part in chunks(answer):
        yield "delta", {"text": part}
    if calls_used:
        yield "notice", {"text": DISCLAIMER}
    entities = [item for result in results for item in result.entities]
    sources = [item for result in results for item in result.sources]
    yield "entities", {"entities": mentioned(entities, answer, MAX_ENTITIES)}
    yield "sources", {"sources": mentioned(sources, answer, MAX_SOURCES)}
    found = mentioned(entities, answer, len(entities))
    context = encode(advance(dialog, ctx, found, answer), key)
    yield "done", {"message_id": uuid.uuid4().hex, "context": context}
    log.info(
        "assistant_chat",
        prompt=PROMPT_VERSION,
        model=provider.model_label,
        rounds=rounds + checker.retried,
        tools=calls_used,
        context=dialog is not None,
        retried=checker.retried,
        chars=len(answer),
        seconds=round(time.perf_counter() - started, 2),
    )
