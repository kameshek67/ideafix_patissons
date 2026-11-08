"""Оценка помощника на наборах вопросов и диалогов (T-020, E1, E2): `just assistant-eval`.

Прогоняет apps/api/tests/assistant_eval.jsonl и assistant_dialogs.jsonl через тот же диалог, что
и чат: настоящая база и настоящие инструменты. Диалог ведётся как на сайте: после каждой реплики
ответ (текст событий delta, без оговорки notice) уходит в историю как сообщение помощника.

Время меряется трижды: до первого видимого события (status или delta — ученик видит, что
помощник работает), до первого delta (начало ответа: он показывается только целиком, после
проверки) и до конца ответа.

Строка набора — JSON:
- `id`; `question` (одна реплика) или `turns` (список реплик ученика);
- проверки последней реплики — поля верхнего уровня: `tools` (нужен вызов любого из них),
  `include` (любой фрагмент), `include_all` (все фрагменты), `exclude`,
  `must_mention_conditions` (фрагменты условий льготы, все обязательны), `max_tools` (не больше
  N вызовов инструментов в этой реплике);
- `checks` — список проверок по репликам с теми же полями (null — реплику не проверять).

Сверх этого каждый ответ проверяет factcheck: вузы, олимпиады и числа не из результатов
инструментов и слов ученика, догадки «обычно…». Любое нарушение — провал случая.

Флаги: --set (можно несколько), --only id1,id2, --out отчёт.json, --compare старый.json.
Бесплатный OpenRouter даёт мало запросов в сутки, поэтому есть --limit и --pause.
В CI проверяется только цепочка на поддельном провайдере.
"""

import argparse
import asyncio
import json
import math
import sys
import time
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from olymp_api.db import make_engine
from olymp_api.llm import LLMEvent, LLMProvider, ToolCalls, make_provider
from olymp_api.settings import Settings

from .context import DialogContext, context_key, decode
from .factcheck import Facts, Violation, Vocabulary, check, load_vocabulary
from .schemas import ChatMessage
from .service import conversation
from .tools import ToolContext

TESTS = Path(__file__).resolve().parents[4] / "tests"
DEFAULT_SET = TESTS / "assistant_eval.jsonl"
DIALOG_SET = TESTS / "assistant_dialogs.jsonl"
DEFAULT_SETS = [DEFAULT_SET, DIALOG_SET]
PASS_SHARE = 0.8
CHECK_FIELDS = ("tools", "include", "include_all", "exclude", "must_mention_conditions")


@dataclass
class Check:
    """Проверки одной реплики."""

    tools: list[str] = field(default_factory=list)  # подойдёт любой
    include: list[str] = field(default_factory=list)  # подойдёт любой фрагмент
    exclude: list[str] = field(default_factory=list)
    include_all: list[str] = field(default_factory=list)  # нужны все фрагменты
    must_mention_conditions: list[str] = field(default_factory=list)  # условия льготы, все
    max_tools: int | None = None  # не больше N вызовов инструментов

    @classmethod
    def parse(cls, row: dict[str, Any]) -> "Check":
        unknown = set(row) - {*CHECK_FIELDS, "max_tools"}
        if unknown:
            raise ValueError(f"неизвестные поля проверки: {sorted(unknown)}")
        return cls(
            **{key: list(row.get(key) or []) for key in CHECK_FIELDS},
            max_tools=row.get("max_tools"),
        )

    def merge(self, other: "Check") -> "Check":
        return Check(
            **{key: getattr(self, key) + getattr(other, key) for key in CHECK_FIELDS},
            max_tools=other.max_tools if other.max_tools is not None else self.max_tools,
        )

    def is_empty(self) -> bool:
        return self == Check()


@dataclass
class Case:
    id: str
    turns: list[str]
    checks: list[Check | None]  # по репликам

    @classmethod
    def single(cls, id_: str, question: str, **check: Any) -> "Case":
        """Случай из одной реплики (для тестов и старого формата)."""
        return cls(id_, [question], [Check(**check)])

    @property
    def conditions(self) -> list[str]:
        return [item for c in self.checks if c for item in c.must_mention_conditions]


@dataclass
class TurnResult:
    question: str
    answer: str = ""
    tools: list[str] = field(default_factory=list)  # вызовы, которые запросила модель
    tool_results: list[str] = field(default_factory=list)  # ToolResult.content
    rounds: int = 0
    first_visible: float | None = None  # секунд до первого status или delta
    first_delta: float | None = None  # секунд до первого текста ответа
    seconds: float = 0.0  # секунд до конца ответа
    notice: str | None = None  # оговорка под ответом (не часть ответа)
    failure: str | None = None
    reasons: list[str] = field(default_factory=list)
    violations: list[Violation] = field(default_factory=list)


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
    def violations(self) -> list[Violation]:
        return [v for turn in self.turns for v in turn.violations]

    @property
    def conditions_named(self) -> bool | None:
        if not self.case.conditions:
            return None
        return not any(
            reason.startswith("не названо условие")
            for turn in self.turns
            for reason in turn.reasons
        )

    @property
    def seconds(self) -> float:
        return sum(turn.seconds for turn in self.turns)


def parse_case(row: dict[str, Any]) -> Case:
    unknown = set(row) - {"id", "question", "turns", "checks", *CHECK_FIELDS, "max_tools"}
    if unknown:
        raise ValueError(f"{row.get('id')}: неизвестные поля {sorted(unknown)}")
    turns = row.get("turns") or [row["question"]]
    if not isinstance(turns, list) or not all(isinstance(t, str) and t.strip() for t in turns):
        raise ValueError(f"{row.get('id')}: turns — список непустых строк")
    top = Check.parse({k: v for k, v in row.items() if k in {*CHECK_FIELDS, "max_tools"}})
    raw_checks = row.get("checks")
    if raw_checks is None:
        checks: list[Check | None] = [None] * (len(turns) - 1) + [top]
    else:
        if len(raw_checks) != len(turns):
            raise ValueError(f"{row['id']}: checks должно быть столько же, сколько реплик")
        checks = [Check.parse(c) if c is not None else None for c in raw_checks]
        if not top.is_empty():
            checks[-1] = (checks[-1] or Check()).merge(top)
    return Case(row["id"], turns, checks)


def load_cases(*paths: Path) -> list[Case]:
    cases = []
    for path in paths:
        lines = path.read_text(encoding="utf-8").splitlines()
        cases += [parse_case(row) for row in map(json.loads, filter(str.strip, lines))]
    return cases


class Recorder:
    """Обёртка провайдера на одну реплику: вызовы инструментов, их результаты и раунды.

    Результаты инструментов видны в истории, которую диалог передаёт модели в следующем раунде
    (сообщения role=tool): так не нужно менять service.py.
    """

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider
        self.used: list[str] = []
        self.rounds = 0
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
            yield event


def judge(check: Check, answer: str, used: list[str], failure: str | None) -> list[str]:
    """Причины провала реплики; пустой список — реплика засчитана."""
    if failure:
        return [f"ошибка: {failure}"]
    text = answer.lower()
    reasons = []
    if check.tools and not set(check.tools) & set(used):
        reasons.append(f"нет вызова {check.tools}, были {used}")
    if check.max_tools is not None and len(used) > check.max_tools:
        reasons.append(f"вызовов инструментов {len(used)} > {check.max_tools}: {used}")
    if check.include and not any(item.lower() in text for item in check.include):
        reasons.append(f"в ответе нет ни одного из {check.include}")
    reasons += [f"в ответе нет «{item}»" for item in check.include_all if item.lower() not in text]
    reasons += [
        f"не названо условие «{item}»"
        for item in check.must_mention_conditions
        if item.lower() not in text
    ]
    reasons += [f"есть запрещённое «{item}»" for item in check.exclude if item.lower() in text]
    return reasons


async def run_case(
    case: Case,
    provider: LLMProvider,
    session: AsyncSession | None,
    vocab: Vocabulary | None = None,
) -> Outcome:
    """Прогоняет диалог реплика за репликой; после ошибки следующие реплики не задаются."""

    async def spend() -> bool:
        return True

    vocab = vocab or Vocabulary()
    key = context_key(None)
    dialog: DialogContext | None = None  # контекст диалога между репликами, как у клиента
    history: list[ChatMessage] = []
    tool_results: list[str] = []
    turns: list[TurnResult] = []
    for question, turn_check in zip(case.turns, case.checks, strict=True):
        history.append(ChatMessage(role="user", content=question))
        recorder = Recorder(provider)
        turn = TurnResult(question)
        started = time.perf_counter()
        # session=None — только в тестах с подменёнными инструментами
        ctx = ToolContext(session, [])  # type: ignore[arg-type]
        events = conversation(recorder, history, ctx, spend, key=key, dialog=dialog, vocab=vocab)
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
        tool_results += turn.tool_results
        turns.append(turn)
        if turn_check is not None:
            turn.reasons = judge(turn_check, turn.answer, turn.tools, turn.failure)
        if turn.failure:
            if turn_check is None:
                turn.reasons = [f"ошибка: {turn.failure}"]
            break
        facts = Facts.collect(tool_results, case.turns[: len(turns)])
        turn.violations = check(turn.answer, facts, vocab)
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


def summary(outcomes: list[Outcome]) -> dict[str, Any]:
    turns = [turn for o in outcomes for turn in o.turns]
    visible = [t.first_visible for t in turns if t.first_visible is not None]
    first = [t.first_delta for t in turns if t.first_delta is not None]
    full = [t.seconds for t in turns if not t.failure]
    answered = [o for o in outcomes if o.answered]
    with_conditions = [o for o in outcomes if o.case.conditions]
    dialogs = [o for o in outcomes if len(o.case.turns) > 1]
    return {
        "cases": len(outcomes),
        "passed": sum(o.passed for o in outcomes),
        "passed_share": share(sum(o.passed for o in outcomes), len(outcomes)),
        "answered": len(answered),
        "no_fabrication_share": share(sum(not o.violations for o in answered), len(answered)),
        "violations": sum(len(o.violations) for o in outcomes),
        "conditions_share": share(sum(bool(o.conditions_named) for o in with_conditions),
                                  len(with_conditions)),
        "dialogs_passed_share": share(sum(o.passed for o in dialogs), len(dialogs)),
        "first_visible_p50": percentile(visible, 0.5),
        "first_visible_p95": percentile(visible, 0.95),
        "first_delta_p50": percentile(first, 0.5),
        "first_delta_p95": percentile(first, 0.95),
        "answer_p50": percentile(full, 0.5),
        "answer_p95": percentile(full, 0.95),
        "rounds_mean": round(sum(t.rounds for t in turns) / len(turns), 2) if turns else None,
        "tools_mean": round(sum(len(t.tools) for t in turns) / len(turns), 2) if turns else None,
    }  # fmt: skip


def report(outcomes: list[Outcome], model: str) -> dict[str, Any]:
    def turn_json(turn: TurnResult) -> dict[str, Any]:
        data = asdict(turn)
        data["violations"] = [asdict(v) for v in turn.violations]
        data.pop("tool_results")  # большие и есть в базе; в отчёте — только их число
        data["tool_results_count"] = len(turn.tool_results)
        return data

    return {
        "model": model,
        "summary": summary(outcomes),
        "cases": [
            {
                "id": o.case.id,
                "passed": o.passed,
                "reasons": o.reasons,
                "violations": len(o.violations),
                "conditions_named": o.conditions_named,
                "seconds": round(o.seconds, 2),
                "turns": [turn_json(t) for t in o.turns],
            }
            for o in outcomes
        ],
    }


LABELS = {
    "passed_share": "пройдено",
    "no_fabrication_share": "без выдумок",
    "conditions_share": "условия названы",
    "dialogs_passed_share": "диалоги пройдены",
    "first_visible_p50": "первый статус p50, с",
    "first_visible_p95": "первый статус p95, с",
    "first_delta_p50": "начало ответа p50, с",
    "first_delta_p95": "начало ответа p95, с",
    "answer_p50": "весь ответ p50, с",
    "answer_p95": "весь ответ p95, с",
    "rounds_mean": "раундов на реплику",
    "tools_mean": "инструментов на реплику",
    "violations": "нарушений всего",
}


def fmt(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def print_summary(data: dict[str, Any], model: str) -> None:
    print(f"\n{model}: пройдено {data['passed']}/{data['cases']}")
    for key, label in LABELS.items():
        print(f"  {label}: {fmt(data.get(key))}")


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


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", type=Path, action="append", help="набор; по умолчанию оба")
    parser.add_argument("--only", default="", help="id случаев через запятую")
    parser.add_argument("--limit", type=int, default=0, help="сколько случаев прогнать")
    parser.add_argument("--pause", type=float, default=4, help="пауза между случаями, секунд")
    parser.add_argument("--out", type=Path, help="сохранить отчёт в JSON")
    parser.add_argument("--compare", type=Path, help="сравнить с прошлым отчётом")
    args = parser.parse_args()

    settings = Settings()
    provider = make_provider(settings)
    engine = make_engine(settings)
    if provider is None or engine is None:
        print("Нужны OLYMP_LLM_BASE_URL, OLYMP_LLM_API_KEY, OLYMP_LLM_MODEL и OLYMP_DATABASE_URL")
        return 2

    cases = load_cases(*(args.set or DEFAULT_SETS))
    if args.only:
        wanted = {item.strip() for item in args.only.split(",") if item.strip()}
        cases = [case for case in cases if case.id in wanted]
    cases = cases[: args.limit] if args.limit else cases
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        vocab = await load_vocabulary(session)
    outcomes = []
    for case in cases:
        async with factory() as session:
            outcome = await run_case(case, provider, session, vocab)
        outcomes.append(outcome)
        mark = "ок " if outcome.passed else "НЕТ"
        times = " ".join(
            f"{fmt(t.first_visible)}/{fmt(t.first_delta)}/{t.seconds:.1f}с" for t in outcome.turns
        )  # первый статус / начало ответа / весь ответ по репликам
        print(f"{mark} {case.id} {times} {'; '.join(outcome.reasons)}", flush=True)
        await asyncio.sleep(args.pause)
    await engine.dispose()

    data = report(outcomes, provider.model_label)
    print_summary(data["summary"], provider.model_label)
    if args.out:
        args.out.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Отчёт: {args.out}")
    if args.compare:
        old = json.loads(args.compare.read_text(encoding="utf-8"))
        print("\n".join(compare(old, data)))
    passed = data["summary"]["passed"]
    return 0 if passed >= PASS_SHARE * len(outcomes) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
