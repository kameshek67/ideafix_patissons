"""Оценка модели на наборе вопросов (T-020): `just assistant-eval`.

Прогоняет apps/api/tests/assistant_eval.jsonl через тот же диалог, что и чат: настоящая база и
настоящие инструменты. Вопрос засчитан, если вызван ожидаемый инструмент, в ответе есть один из
ожидаемых фрагментов и нет запрещённых. В CI проверяется только цепочка на поддельном провайдере.

Бесплатный OpenRouter даёт мало запросов в сутки, поэтому есть --limit и --pause.
"""

import argparse
import asyncio
import json
import sys
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from olymp_api.db import make_engine
from olymp_api.llm import LLMEvent, LLMProvider, ToolCalls, make_provider
from olymp_api.settings import Settings

from .schemas import ChatMessage
from .service import conversation
from .tools import ToolContext

DEFAULT_SET = Path(__file__).resolve().parents[4] / "tests" / "assistant_eval.jsonl"
PASS_SHARE = 0.8


@dataclass
class Case:
    id: str
    question: str
    tools: list[str]  # подойдёт любой; пусто — инструменты не обязательны
    include: list[str]  # подойдёт любой фрагмент; пусто — без проверки
    exclude: list[str]
    include_all: list[str] = field(default_factory=list)  # нужны все фрагменты


@dataclass
class Outcome:
    case: Case
    passed: bool
    reasons: list[str]
    seconds: float


def load_cases(path: Path) -> list[Case]:
    lines = path.read_text(encoding="utf-8").splitlines()
    return [
        Case(
            row["id"],
            row["question"],
            row.get("tools", []),
            row.get("include", []),
            row.get("exclude", []),
            row.get("include_all", []),
        )
        for row in map(json.loads, filter(str.strip, lines))
    ]


class Recorder:
    """Обёртка провайдера: запоминает, какие инструменты вызвала модель."""

    def __init__(self, provider: LLMProvider) -> None:
        self.provider = provider
        self.used: list[str] = []

    @property
    def model_label(self) -> str:
        return self.provider.model_label

    async def stream(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> AsyncIterator[LLMEvent]:
        async for event in self.provider.stream(messages, tools):
            if isinstance(event, ToolCalls):
                self.used += [call.name for call in event.calls]
            yield event


def judge(case: Case, answer: str, used: list[str], failure: str | None) -> list[str]:
    """Причины провала; пустой список — вопрос засчитан."""
    if failure:
        return [f"ошибка: {failure}"]
    text = answer.lower()
    reasons = []
    if case.tools and not set(case.tools) & set(used):
        reasons.append(f"нет вызова {case.tools}, были {used}")
    if case.include and not any(item.lower() in text for item in case.include):
        reasons.append(f"в ответе нет ни одного из {case.include}")
    reasons += [f"в ответе нет «{item}»" for item in case.include_all if item.lower() not in text]
    reasons += [f"есть запрещённое «{item}»" for item in case.exclude if item.lower() in text]
    return reasons


async def run_case(case: Case, provider: LLMProvider, session: AsyncSession) -> Outcome:
    async def spend() -> bool:
        return True

    recorder = Recorder(provider)
    started = time.perf_counter()
    answer = ""
    failure = None
    messages = [ChatMessage(role="user", content=case.question)]
    async for event, data in conversation(recorder, messages, ToolContext(session, []), spend):
        if event == "delta":
            answer += data["text"]
        elif event == "error":
            failure = data["code"]
    reasons = judge(case, answer, recorder.used, failure)
    return Outcome(case, not reasons, reasons, time.perf_counter() - started)


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--set", type=Path, default=DEFAULT_SET)
    parser.add_argument("--limit", type=int, default=0, help="сколько вопросов прогнать")
    parser.add_argument("--pause", type=float, default=4, help="пауза между вопросами, секунд")
    args = parser.parse_args()

    settings = Settings()
    provider = make_provider(settings)
    engine = make_engine(settings)
    if provider is None or engine is None:
        print("Нужны OLYMP_LLM_BASE_URL, OLYMP_LLM_API_KEY, OLYMP_LLM_MODEL и OLYMP_DATABASE_URL")
        return 2

    cases = load_cases(args.set)
    cases = cases[: args.limit] if args.limit else cases
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    outcomes = []
    for case in cases:
        async with factory() as session:
            outcome = await run_case(case, provider, session)
        outcomes.append(outcome)
        mark = "ок " if outcome.passed else "НЕТ"
        print(f"{mark} {case.id} {outcome.seconds:.1f} с {'; '.join(outcome.reasons)}", flush=True)
        await asyncio.sleep(args.pause)
    await engine.dispose()

    passed = sum(o.passed for o in outcomes)
    average = sum(o.seconds for o in outcomes) / max(len(outcomes), 1)
    print(f"{provider.model_label}: {passed}/{len(outcomes)}, в среднем {average:.1f} с")
    return 0 if passed >= PASS_SHARE * len(outcomes) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
