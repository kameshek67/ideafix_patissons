"""Оценка помощника на наборе вопросов (B7): `just assistant-eval`.

Прогоняет backend/api/tests/assistant_cases.jsonl через тот же диалог, что и чат: настоящая база и
настоящие инструменты. Диалог ведётся как на сайте: после каждой реплики ответ (текст событий
delta, без оговорки notice) уходит в историю как сообщение помощника.

Набор — данные: вопросы пишут люди (assistant_questions.jsonl), а ожидания — какие факты должны
быть в ответе и каких утверждений быть не должно — выводит из собранной базы `build_cases`
(см. expectations.py). Проверок вида «в ответе есть слово» нет.

Ошибки считаются дважды: в сыром ответе модели (до фактчекера) и в итоговом (после проверки,
повтора и вырезания). Итоговый почти всегда чище по построению, поэтому качество модели
показывает сырой, а работу проверки — разница.

Строка набора — JSON:
- `id`, `kind`, `persona`; `question` (одна реплика) или `turns` (реплики ученика);
- `tools` — нужен вызов любого из них, `max_tools` — не больше N вызовов в последней реплике;
- `expect` — ожидания последней реплики (expectations.Spec).

Время меряется трижды: до первого видимого события (status или delta), до первого delta
(ответ показывается только целиком, после проверки) и до конца ответа.

Флаги: --provider (профиль из OLYMP_LLM_PROFILES или `stub`), --model, --set, --only, --limit,
--pause, --out отчёт.json, --compare старый.json, --price-in/--price-out (за миллион токенов).
Без --provider берутся настройки OLYMP_LLM_*. В CI проверяется только цепочка на подставной
модели.
"""

import argparse
import asyncio
import json
import math
import sys
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from olymp_api.db import data_version, make_engine
from olymp_api.llm import (
    LLMEvent,
    LLMProvider,
    TextDelta,
    ToolCall,
    ToolCalls,
    Usage,
    make_provider,
    provider_name,
)
from olymp_api.settings import Settings

from .claims import Ledger, check_claims
from .context import DialogContext, context_key, decode
from .expectations import Assessment, Spec, assess
from .factcheck import Violation, Vocabulary, check, load_vocabulary
from .prompt import PROMPT_VERSION
from .schemas import ChatMessage
from .service import NO_DATA_ANSWER, Trace, conversation
from .tools import ToolContext

TESTS = Path(__file__).resolve().parents[4] / "tests"
CASES_SET = TESTS / "assistant_cases.jsonl"
QUESTIONS_SET = TESTS / "assistant_questions.jsonl"
DEFAULT_SETS = [CASES_SET]
CASE_FIELDS = {
    "id",
    "kind",
    "persona",
    "question",
    "turns",
    "tools",
    "max_tools",
    "expect",
    "about",
}
# пороги включения помощника (docs/plan.md, «Качество помощника»)
GATE_OTHER_ERRORS = 0.05
GATE_P95_SECONDS = 20.0
ERROR_KINDS = ("entity", "number", "role", "benefit_type", "threshold", "not_listed")


@dataclass
class Case:
    id: str
    turns: list[str]
    kind: str = ""
    persona: str = ""
    tools: list[str] = field(default_factory=list)  # последняя реплика: нужен любой из них
    max_tools: int | None = None  # последняя реплика: не больше N вызовов
    spec: Spec = field(default_factory=Spec)

    @classmethod
    def single(cls, id_: str, question: str, **spec: Any) -> "Case":
        """Случай из одной реплики (для тестов)."""
        return cls(id_, [question], spec=Spec.parse(spec))


@dataclass
class TurnResult:
    question: str
    answer: str = ""  # итоговый, после проверки
    raw_answer: str = ""  # ответ модели до проверки
    tools: list[str] = field(default_factory=list)  # вызовы, которые запросила модель
    tool_results: list[str] = field(default_factory=list)  # ToolResult.content
    rounds: int = 0
    first_visible: float | None = None  # секунд до первого status или delta
    first_delta: float | None = None  # секунд до первого текста ответа
    seconds: float = 0.0  # секунд до конца ответа
    notice: str | None = None  # оговорка под ответом (не часть ответа)
    failure: str | None = None
    retried: bool = False
    model_error: bool = False  # модель вернула разметку вызова инструмента вместо ответа
    reasons: list[str] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)  # итоговый ответ
    raw_violations: list[Violation] = field(default_factory=list)  # сырой ответ
    expected: Assessment | None = None  # итоговый ответ против ожиданий (последняя реплика)
    raw_expected: Assessment | None = None  # сырой ответ против ожиданий
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float | None = None  # цена, которую вернул провайдер


@dataclass
class Outcome:
    case: Case
    turns: list[TurnResult]

    @property
    def reasons(self) -> list[str]:
        many = len(self.case.turns) > 1
        return [
            f"реплика {i + 1}: {reason}" if many else reason
            for i, turn in enumerate(self.turns)
            for reason in [*turn.reasons, *map(str, turn.violations)]
        ]

    @property
    def passed(self) -> bool:
        return len(self.turns) == len(self.case.turns) and not self.reasons

    @property
    def answered(self) -> bool:
        return len(self.turns) == len(self.case.turns) and not any(t.failure for t in self.turns)

    @property
    def last(self) -> TurnResult | None:
        return self.turns[-1] if self.answered else None

    @property
    def violations(self) -> list[Violation]:
        return [v for turn in self.turns for v in turn.violations]

    @property
    def seconds(self) -> float:
        return sum(turn.seconds for turn in self.turns)


def parse_case(row: dict[str, Any]) -> Case:
    unknown = set(row) - CASE_FIELDS
    if unknown:
        raise ValueError(f"{row.get('id')}: неизвестные поля {sorted(unknown)}")
    turns = row.get("turns") or [row["question"]]
    if not isinstance(turns, list) or not all(isinstance(t, str) and t.strip() for t in turns):
        raise ValueError(f"{row.get('id')}: turns — список непустых строк")
    return Case(
        row["id"],
        turns,
        kind=row.get("kind", ""),
        persona=row.get("persona", ""),
        tools=list(row.get("tools") or []),
        max_tools=row.get("max_tools"),
        spec=Spec.parse(row.get("expect") or {}),
    )


def load_cases(*paths: Path) -> list[Case]:
    cases = []
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        cases += [parse_case(row) for row in map(json.loads, filter(str.strip, lines))]
    return cases


class Recorder:
    """Обёртка провайдера на одну реплику: вызовы инструментов, их результаты, раунды и расход.

    Результаты инструментов видны в истории, которую диалог передаёт модели в следующем раунде
    (сообщения role=tool): так не нужно менять service.py. Повтор после фактчекера идёт через
    ту же обёртку, поэтому токены и цена включают его.
    """

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider
        self.used: list[str] = []
        self.rounds = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.cost: float | None = None
        self._results: dict[str, str] = {}

    @property
    def model_label(self) -> str:
        return self.provider.model_label

    @property
    def tool_results(self) -> list[str]:
        return list(self._results.values())

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[LLMEvent]:
        self.rounds += 1
        for message in messages:
            if message["role"] == "tool":
                self._results.setdefault(message["tool_call_id"], message["content"])
        async for event in self.provider.stream(messages, tools):
            if isinstance(event, ToolCalls):
                self.used += [call.name for call in event.calls]
            elif isinstance(event, Usage):
                self.prompt_tokens += event.prompt_tokens
                self.completion_tokens += event.completion_tokens
                if event.cost is not None:
                    self.cost = (self.cost or 0.0) + event.cost
            yield event


class StubProvider:
    """Подставная модель для проверки цепочки без LLM-API: ищет олимпиаду по первому слову
    с прописной буквы и отвечает, что данных нет. Расход токенов считает по длине текста."""

    model_label = "stub"

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[LLMEvent]:
        question = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        searched = any(m["role"] == "tool" for m in messages)
        if tools and not searched:
            word = next(
                (w for w in question.split() if w[:1].isupper() and len(w) > 2), "олимпиада"
            )
            args = json.dumps({"query": word.strip("«»?,.")}, ensure_ascii=False)
            yield ToolCalls((ToolCall("stub1", "find_olympiads", args),))
        else:
            yield TextDelta(NO_DATA_ANSWER)
        yield Usage(len(json.dumps(messages, ensure_ascii=False)) // 4, 40)


def judge(case: Case, turn: TurnResult, final: Assessment | None) -> list[str]:
    """Причины провала последней реплики: инструменты и ожидания; пустой список — засчитана."""
    if turn.failure:
        return [f"ошибка: {turn.failure}"]
    if turn.model_error:
        return ["ошибка модели: сырой вызов инструмента"]
    spec = case.spec
    reasons = []
    if case.tools and not set(case.tools) & set(turn.tools):
        reasons.append(f"нет вызова {case.tools}, были {turn.tools}")
    if case.max_tools is not None and len(turn.tools) > case.max_tools:
        reasons.append(f"вызовов инструментов {len(turn.tools)} > {case.max_tools}: {turn.tools}")
    if spec.refuse and turn.tools:
        reasons.append(f"отказ, но был поиск: {turn.tools}")
    if spec.clarify and "?" not in turn.answer:
        reasons.append("нужен уточняющий вопрос, его нет")
    if final is None:
        return reasons
    reasons += [f"нет факта: {item}" for item in final.missing]
    reasons += [f"запрещённое: {item}" for item in final.hits]
    if spec.data == "absent" and not final.no_data:
        reasons.append("данных нет, а ответ не говорит «в базе нет данных»")
    if spec.refuse and final.asserts:
        reasons.append("отказ, но в ответе есть утверждение о льготе")
    return reasons


async def final_problems(answer: str, trace: Trace, vocab: Vocabulary) -> list[Violation]:
    """Нарушения итогового ответа тем же набором фактов и строк базы, что и в проверке."""
    if trace.facts is None:
        return []
    found = check(answer, trace.facts, vocab)
    if trace.ledger is not None:
        await trace.ledger.ensure(answer, vocab)
        found += check_claims(answer, vocab, trace.ledger)
    return found


async def run_case(
    case: Case,
    provider: LLMProvider,
    session: AsyncSession | None,
    vocab: Vocabulary | None = None,
    ledger: Ledger | None = None,
) -> Outcome:
    """Прогоняет диалог реплика за репликой; после ошибки следующие реплики не задаются.

    ledger — готовые строки базы вместо загрузки (тесты без базы).
    """

    async def spend() -> bool:
        return True

    vocab = vocab or Vocabulary()
    key = context_key(None)
    dialog: DialogContext | None = None  # контекст диалога между репликами, как у клиента
    history: list[ChatMessage] = []
    turns: list[TurnResult] = []
    for number, question in enumerate(case.turns, start=1):
        history.append(ChatMessage(role="user", content=question))
        recorder = Recorder(provider)
        turn = TurnResult(question)
        trace = Trace()
        started = time.perf_counter()
        # session=None — только в тестах с подменёнными инструментами
        ctx = ToolContext(session, [])  # type: ignore[arg-type]
        events = conversation(
            recorder, history, ctx, spend, key=key, dialog=dialog, vocab=vocab, trace=trace,
            ledger=ledger,
        )  # fmt: skip
        async for event, data in events:
            if event in {"status", "delta"} and turn.first_visible is None:
                turn.first_visible = time.perf_counter() - started
            if event == "notice":
                turn.notice = data["text"]
            elif event == "delta":
                if turn.first_delta is None:
                    turn.first_delta = time.perf_counter() - started
                turn.answer += data["text"]
            elif event == "done":
                dialog = decode(data.get("context"), key)
            elif event == "error":
                turn.failure = data["code"]
        turn.seconds = time.perf_counter() - started
        turn.tools, turn.tool_results, turn.rounds = (
            recorder.used,
            recorder.tool_results,
            recorder.rounds,
        )
        turn.prompt_tokens, turn.completion_tokens, turn.cost = (
            recorder.prompt_tokens,
            recorder.completion_tokens,
            recorder.cost,
        )
        turn.raw_answer, turn.retried = trace.raw_answer, trace.retry_answer is not None
        turn.model_error = trace.model_error
        turns.append(turn)
        if turn.failure:
            turn.reasons = [f"ошибка: {turn.failure}"]
            break
        turn.violations = await final_problems(turn.answer, trace, vocab)
        turn.raw_violations = trace.raw_problems
        last = number == len(case.turns)
        if last:
            turn.raw_expected = assess(case.spec, turn.raw_answer, vocab)
            turn.expected = assess(case.spec, turn.answer, vocab)
            turn.reasons = judge(case, turn, turn.expected)
        history.append(ChatMessage(role="assistant", content=turn.answer[:2000]))
    return Outcome(case, turns)


# ---------------------------------------------------------------- отчёт


def percentile(values: list[float], share: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(share * len(ordered)) - 1)]


def share(part: int, whole: int) -> float | None:
    return round(part / whole, 3) if whole else None


def error_kinds(turn: TurnResult, raw: bool) -> set[str]:
    """Виды фактических ошибок реплики (догадки «обычно» — не факты и считаются отдельно)."""
    problems = turn.raw_violations if raw else turn.violations
    found: set[str] = {str(v.kind) for v in problems} & set(ERROR_KINDS)
    expected = turn.raw_expected if raw else turn.expected
    if expected and expected.hits:
        found.add("forbidden")
    return found


def who_type_error(turn: TurnResult, raw: bool) -> bool:
    """Ошибка «кому» или «тип льготы»: нарушение claims или сработавший запрет из базы."""
    problems = turn.raw_violations if raw else turn.violations
    expected = turn.raw_expected if raw else turn.expected
    kinds = {v.kind for v in problems}
    return bool(
        kinds & {"role", "benefit_type"} or (expected and (expected.hits_who or expected.hits_type))
    )


def is_no_data_where_data(turn: TurnResult, raw: bool) -> bool:
    """Ответ «в базе нет данных», хотя нужные факты в базе есть и не названы."""
    expected = turn.raw_expected if raw else turn.expected
    return bool(expected and expected.no_data and expected.missing)


def is_fabrication(turn: TurnResult, raw: bool) -> bool:
    """Данных в базе нет, а ответ их не признаёт или выдумывает утверждения о льготах."""
    expected = turn.raw_expected if raw else turn.expected
    return bool(expected and (not expected.no_data or error_kinds(turn, raw)))


def money(value: float | None) -> float | None:
    return round(value, 4) if value is not None else None


def summary(
    outcomes: list[Outcome], price_in: float | None = None, price_out: float | None = None
) -> dict[str, Any]:
    turns = [turn for o in outcomes for turn in o.turns]
    visible = [t.first_visible for t in turns if t.first_visible is not None]
    first = [t.first_delta for t in turns if t.first_delta is not None]
    full = [t.seconds for t in turns if not t.failure]
    answered = [t for t in turns if not t.failure]
    with_data = [o.last for o in outcomes if o.last and o.case.spec.data == "present"]
    without_data = [o.last for o in outcomes if o.last and o.case.spec.data == "absent"]
    dialogs = [o for o in outcomes if len(o.case.turns) > 1]
    facts_total = sum(len(t.expected.found) for t in with_data if t.expected)
    facts_found = sum(t.expected.facts_found for t in with_data if t.expected)
    prompt = sum(t.prompt_tokens for t in turns)
    completion = sum(t.completion_tokens for t in turns)
    reported = [t.cost for t in turns if t.cost is not None]
    cost = sum(reported) if reported else None
    if cost is None and prompt + completion and (price_in is not None or price_out is not None):
        cost = (prompt * (price_in or 0) + completion * (price_out or 0)) / 1_000_000
    data: dict[str, Any] = {
        "cases": len(outcomes),
        "passed": sum(o.passed for o in outcomes),
        "passed_share": share(sum(o.passed for o in outcomes), len(outcomes)),
        "answered_turns": len(answered),
        "model_errors": sum(t.model_error for t in answered),
        "retried_share": share(sum(t.retried for t in answered), len(answered)),
        "dialogs_passed_share": share(sum(o.passed for o in dialogs), len(dialogs)),
        "facts_found_share": share(facts_found, facts_total),
        "violations": sum(len(o.violations) for o in outcomes),
        "first_visible_p50": percentile(visible, 0.5),
        "first_visible_p95": percentile(visible, 0.95),
        "first_delta_p50": percentile(first, 0.5),
        "first_delta_p95": percentile(first, 0.95),
        "answer_p50": percentile(full, 0.5),
        "answer_p95": percentile(full, 0.95),
        "rounds_mean": round(sum(t.rounds for t in turns) / len(turns), 2) if turns else None,
        "tools_mean": round(sum(len(t.tools) for t in turns) / len(turns), 2) if turns else None,
        "tokens_prompt": prompt or None,
        "tokens_completion": completion or None,
        "cost_total": money(cost),
        "cost_per_answer": money(cost / len(answered)) if cost is not None and answered else None,
        "cost_source": "провайдер" if reported else ("по цене токенов" if cost else None),
    }  # fmt: skip
    for name, raw in (("raw", True), ("final", False)):
        data[f"error_share_{name}"] = share(
            sum(bool(error_kinds(t, raw)) for t in answered), len(answered)
        )
        data[f"who_type_errors_{name}"] = sum(who_type_error(t, raw) for t in answered)
        data[f"hedge_share_{name}"] = share(
            sum(
                any(v.kind == "hedge" for v in (t.raw_violations if raw else t.violations))
                for t in answered
            ),
            len(answered),
        )
        data[f"no_data_where_data_{name}"] = share(
            sum(is_no_data_where_data(t, raw) for t in with_data), len(with_data)
        )
        data[f"fabrication_{name}"] = share(
            sum(is_fabrication(t, raw) for t in without_data), len(without_data)
        )
    data["error_kinds_raw"] = kinds_count(answered, True)
    data["error_kinds_final"] = kinds_count(answered, False)
    return data  # fmt: skip


def kinds_count(turns: list[TurnResult], raw: bool) -> dict[str, int]:
    counts: dict[str, int] = {}
    for turn in turns:
        for kind in error_kinds(turn, raw):
            counts[kind] = counts.get(kind, 0) + 1
    return dict(sorted(counts.items()))


def gate(data: dict[str, Any]) -> dict[str, Any]:
    """Порог включения из плана: ни одной ошибки «кому» и «тип льготы», остальных ≤ 5%, p95 < 20 с.

    Считается по итоговым ответам: ученик видит их, а не сырые.
    """
    errors = data["error_share_final"]
    p95 = data["answer_p95"]
    checks = {
        "who_type_errors": data["who_type_errors_final"] == 0,
        "other_errors": errors is not None and errors <= GATE_OTHER_ERRORS,
        "p95": p95 is not None and p95 < GATE_P95_SECONDS,
    }
    return {**checks, "passed": all(checks.values())}


def report(
    outcomes: list[Outcome],
    model: str,
    *,
    provider: str = "",
    version: str | None = None,
    cases_file: str = "",
    price_in: float | None = None,
    price_out: float | None = None,
) -> dict[str, Any]:
    def turn_json(turn: TurnResult) -> dict[str, Any]:
        data = asdict(turn)
        data["violations"] = [asdict(v) for v in turn.violations]
        data["raw_violations"] = [asdict(v) for v in turn.raw_violations]
        data.pop("tool_results")  # большие и есть в базе; в отчёте — только их число
        data["tool_results_count"] = len(turn.tool_results)
        return data

    stats = summary(outcomes, price_in, price_out)
    return {
        "date": datetime.now(UTC).isoformat(timespec="seconds"),
        "provider": provider,
        "model": model,
        "prompt_version": PROMPT_VERSION,
        "data_version": version,
        "cases_file": cases_file,
        "summary": stats,
        "gate": gate(stats),
        "cases": [
            {
                "id": o.case.id,
                "kind": o.case.kind,
                "passed": o.passed,
                "reasons": o.reasons,
                "violations": len(o.violations),
                "seconds": round(o.seconds, 2),
                "turns": [turn_json(t) for t in o.turns],
            }
            for o in outcomes
        ],
    }


LABELS = {
    "passed_share": "пройдено",
    "model_errors": "ошибки модели (сырой вызов)",
    "error_share_raw": "ответов с ошибкой факта до фактчекера",
    "error_share_final": "ответов с ошибкой факта после фактчекера",
    "who_type_errors_raw": "ошибок «кому»/«тип льготы» до",
    "who_type_errors_final": "ошибок «кому»/«тип льготы» после",
    "hedge_share_raw": "догадок «обычно» до",
    "hedge_share_final": "догадок «обычно» после",
    "no_data_where_data_raw": "«нет данных», а данные есть, до",
    "no_data_where_data_final": "«нет данных», а данные есть, после",
    "fabrication_raw": "выдумок там, где данных нет, до",
    "fabrication_final": "выдумок там, где данных нет, после",
    "facts_found_share": "ожидаемых фактов названо",
    "retried_share": "ответов с повтором",
    "dialogs_passed_share": "диалоги пройдены",
    "first_visible_p50": "первый статус p50, с",
    "first_delta_p50": "начало ответа p50, с",
    "answer_p50": "весь ответ p50 (медиана), с",
    "answer_p95": "весь ответ p95, с",
    "rounds_mean": "раундов на реплику",
    "tools_mean": "инструментов на реплику",
    "tokens_prompt": "токенов запросов",
    "tokens_completion": "токенов ответов",
    "cost_total": "цена всего",
    "cost_per_answer": "цена ответа",
    "violations": "нарушений всего",
}


def fmt(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def print_summary(data: dict[str, Any], model: str) -> None:
    print(f"\n{model}: пройдено {data['summary']['passed']}/{data['summary']['cases']}")
    for key, label in LABELS.items():
        print(f"  {label}: {fmt(data['summary'].get(key))}")
    print(f"  ошибки до: {data['summary']['error_kinds_raw']}")
    print(f"  ошибки после: {data['summary']['error_kinds_final']}")
    print(f"  порог включения: {data['gate']}")


def compare(old: dict[str, Any], new: dict[str, Any]) -> list[str]:
    """Строки сравнения метрик и случаев, у которых изменился результат."""
    lines = [f"Сравнение: {old.get('model')} → {new.get('model')}"]
    for key, label in LABELS.items():
        before, after = old["summary"].get(key), new["summary"].get(key)
        delta = ""
        if isinstance(before, int | float) and isinstance(after, int | float):
            delta = f" ({after - before:+.2f})"
        lines.append(f"  {label}: {fmt(before)} → {fmt(after)}{delta}")
    was = {c["id"]: c["passed"] for c in old["cases"]}
    for case in new["cases"]:
        if case["id"] in was and was[case["id"]] != case["passed"]:
            mark = "стал проходить" if case["passed"] else "перестал проходить"
            lines.append(f"  {case['id']}: {mark}")
    return lines


def select_cases(cases: list[Case], only: str = "", limit: int = 0) -> list[Case]:
    if only:
        wanted = {item.strip() for item in only.split(",") if item.strip()}
        cases = [case for case in cases if case.id in wanted]
    return cases[:limit] if limit else cases


async def run(
    cases: list[Case],
    provider: LLMProvider,
    factory: async_sessionmaker[AsyncSession],
    *,
    provider_label: str = "",
    cases_file: str = "",
    pause: float = 0,
    price_in: float | None = None,
    price_out: float | None = None,
    echo: bool = True,
) -> dict[str, Any]:
    """Прогон набора и отчёт: общий путь для команды и тестов."""
    async with factory() as session:
        vocab = await load_vocabulary(session)
        try:
            version: str | None = await data_version(session)
        except Exception:  # noqa: BLE001 — версия базы нужна только отчёту
            version = None
    outcomes = []
    for case in cases:
        async with factory() as session:
            outcome = await run_case(case, provider, session, vocab)
        outcomes.append(outcome)
        if echo:
            mark = "ок " if outcome.passed else "НЕТ"
            times = " ".join(
                f"{fmt(t.first_visible)}/{fmt(t.first_delta)}/{t.seconds:.1f}с"
                for t in outcome.turns
            )  # первый статус / начало ответа / весь ответ по репликам
            print(f"{mark} {case.id} {times} {'; '.join(outcome.reasons)}", flush=True)
        if pause:
            await asyncio.sleep(pause)
    return report(
        outcomes,
        provider.model_label,
        provider=provider_label,
        version=version,
        cases_file=cases_file,
        price_in=price_in,
        price_out=price_out,
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", type=Path, action="append", help="набор; по умолчанию основной")
    parser.add_argument("--provider", help="профиль из OLYMP_LLM_PROFILES или stub (без LLM-API)")
    parser.add_argument("--model", help="подменить модель профиля или OLYMP_LLM_MODEL")
    parser.add_argument("--only", default="", help="id случаев через запятую")
    parser.add_argument("--limit", type=int, default=0, help="сколько случаев прогнать")
    parser.add_argument("--pause", type=float, default=4, help="пауза между случаями, секунд")
    parser.add_argument("--price-in", type=float, help="цена миллиона токенов запроса")
    parser.add_argument("--price-out", type=float, help="цена миллиона токенов ответа")
    parser.add_argument("--out", type=Path, help="сохранить отчёт в JSON")
    parser.add_argument("--compare", type=Path, help="сравнить с прошлым отчётом")
    args = parser.parse_args()

    settings = Settings()
    provider: LLMProvider | None
    if args.provider == "stub":
        provider, label, pause = StubProvider(), "stub", 0.0
    else:
        provider = make_provider(
            settings, profile=args.provider, model=args.model, include_usage=True
        )
        label, pause = provider_name(settings, args.provider), args.pause
    engine = make_engine(settings)
    if provider is None or engine is None:
        print(
            "Нужны OLYMP_DATABASE_URL и провайдер: OLYMP_LLM_BASE_URL, OLYMP_LLM_API_KEY, "
            "OLYMP_LLM_MODEL или профиль из OLYMP_LLM_PROFILES (--provider имя)"
        )
        return 2
    profile = settings.llm_profiles.get(args.provider or "")
    price_in = args.price_in if args.price_in is not None else profile and profile.price_in
    price_out = args.price_out if args.price_out is not None else profile and profile.price_out

    paths = args.set or DEFAULT_SETS
    cases = select_cases(load_cases(*paths), args.only, args.limit)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    data = await run(
        cases,
        provider,
        factory,
        provider_label=label,
        cases_file=",".join(p.name for p in paths),
        pause=pause,
        price_in=price_in or None,
        price_out=price_out or None,
    )
    await engine.dispose()

    print_summary(data, f"{label} / {provider.model_label} / промпт {PROMPT_VERSION}")
    if args.out:
        args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Отчёт: {args.out}")
    if args.compare:
        old = json.loads(args.compare.read_text(encoding="utf-8"))
        print("\n".join(compare(old, data)))
    return 0 if data["gate"]["passed"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
