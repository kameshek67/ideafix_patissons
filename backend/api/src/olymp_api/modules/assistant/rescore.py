"""Пересчёт сохранённых прогонов помощника без вызова модели: `just assistant-rescore`.

В отчёте уже есть ответы до и после проверки, вызовы инструментов и расход. Заново считаются
ожидания, причины провала, метрики и порог включения. Словарь имён строится из ожиданий набора,
поэтому база и провайдер не нужны.
"""

import argparse
import json
import sys
from collections.abc import Sequence
from dataclasses import fields
from pathlib import Path
from typing import Any

from olymp_llm import is_tool_markup

from .evaluate import (
    TESTS,
    Case,
    Outcome,
    TurnResult,
    judge,
    load_cases,
    report,
)
from .expectations import Assessment, assess
from .factcheck import Entity, Violation, Vocabulary, university_names

METRICS = (
    "cases",
    "passed_share",
    "error_share_raw",
    "error_share_final",
    "answer_p95",
    "cost_per_answer",
)


def pick[T](cls: type[T], row: dict[str, Any]) -> T:
    """Собрать dataclass из сохранённого JSON: лишние и новые поля не мешают."""
    names = {field.name for field in fields(cls)}  # type: ignore[arg-type]
    return cls(**{key: value for key, value in row.items() if key in names})


def vocabulary(cases: Sequence[Case]) -> Vocabulary:
    """Названия из ожиданий набора: по ним сверяются факты в сохранённых ответах."""
    vocab = Vocabulary()
    seen: set[tuple[str, str]] = set()
    number = 0
    for case in cases:
        for fact in [*case.spec.facts, *case.spec.forbidden]:
            for kind, labels in (("university", fact.universities), ("olympiad", fact.olympiads)):
                for label in labels:
                    if (kind, label) in seen:
                        continue
                    seen.add((kind, label))
                    number += 1
                    entity = Entity(kind, number, label)  # type: ignore[arg-type]
                    if kind == "university":
                        vocab.add(entity, label, *university_names(label), full=False)
                    else:
                        vocab.add(entity, label, label.strip("«»"))
    return vocab


def turn_of(row: dict[str, Any]) -> TurnResult:
    data = dict(row)
    for key in ("violations", "raw_violations"):
        data[key] = [pick(Violation, item) for item in row.get(key) or []]
    for key in ("expected", "raw_expected"):
        value = row.get(key)
        data[key] = pick(Assessment, value) if value else None
    data["tool_results"] = []
    data["model_error"] = bool(row.get("model_error")) or is_tool_markup(
        row.get("raw_answer") or ""
    )
    return pick(TurnResult, data)


def rescore(data: dict[str, Any], cases: Sequence[Case]) -> dict[str, Any]:
    """Заново сверить сохранённые ответы с ожиданиями и пересчитать метрики отчёта."""
    by_id = {case.id: case for case in cases}
    vocab = vocabulary(cases)
    outcomes: list[Outcome] = []
    for saved in data["cases"]:
        case = by_id.get(saved["id"])
        if case is None:
            raise ValueError(f"нет ожиданий для случая {saved['id']}")
        turns = [turn_of(row) for row in saved["turns"]]
        if turns:
            last = turns[-1]
            last.raw_expected = assess(case.spec, last.raw_answer or last.answer, vocab)
            last.expected = assess(case.spec, last.answer, vocab)
            last.reasons = judge(case, last, last.expected)
        for turn in turns:
            if not turn.failure and not turn.model_error:
                continue
            turn.reasons = [
                f"ошибка: {turn.failure}"
                if turn.failure
                else "ошибка модели: сырой вызов инструмента"
            ]
        outcomes.append(Outcome(case, turns))

    fresh = report(
        outcomes,
        data["model"],
        provider=data.get("provider") or "",
        version=data.get("data_version"),
        cases_file=data.get("cases_file") or "",
    )
    fresh["date"] = data.get("date", fresh["date"])
    # цену из токенов без профиля не восстановить: оставляем ту, что была в прогоне
    for key in ("cost_total", "cost_per_answer", "cost_source"):
        if fresh["summary"].get(key) is None:
            fresh["summary"][key] = data.get("summary", {}).get(key)
    return fresh


def quality_summary(paths: Sequence[Path]) -> dict[str, Any]:
    """Сводка прогонов в формате, который читает modules/quality."""
    models: list[dict[str, Any]] = []
    dates: list[str] = []
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        stats = data["summary"]
        if isinstance(data.get("date"), str):
            dates.append(data["date"])
        models.append(
            {
                "model": data["model"],
                **{key: stats.get(key) for key in METRICS},
                "gate_passed": bool(data.get("gate", {}).get("passed")),
            }
        )
    # выбираем только из прогонов на полном наборе: пять вопросов ничего не говорят о модели
    full = max((m["cases"] or 0 for m in models), default=0)
    complete = [m for m in models if (m["cases"] or 0) == full and m["cost_per_answer"] is not None]
    passed = [m for m in complete if m["gate_passed"]]
    chosen = min(passed, key=lambda m: m["cost_per_answer"], default=None)
    note = (
        f"прошла порог включения на полном наборе ({full} вопросов) и дешевле остальных"
        if chosen
        else f"на полном наборе ({full} вопросов) порог включения не прошла ни одна модель"
    )
    date = max(dates, default="")
    return {
        "date": date,
        "models": models,
        "selected": chosen["model"] if chosen else None,
        "summary": {key: chosen[key] for key in METRICS} if chosen else None,
        "note": note,
    }


def cases_from(data: dict[str, Any]) -> list[Case]:
    names = [name.strip() for name in (data.get("cases_file") or "").split(",") if name.strip()]
    paths = [Path(name) if Path(name).is_absolute() else TESTS / name for name in names]
    return load_cases(*(paths or [TESTS / "assistant_cases.jsonl"]))


def rescore_file(path: Path, out: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    fresh = rescore(data, cases_from(data))
    out.write_text(json.dumps(fresh, ensure_ascii=False, indent=1), encoding="utf-8")
    return fresh


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="сохранённый отчёт прогона")
    parser.add_argument("--out", type=Path, required=True, help="новый отчёт")
    parser.add_argument(
        "--summary", type=Path, help="собрать сводку из всех *-rescored.json рядом с --out"
    )
    args = parser.parse_args()
    fresh = rescore_file(args.report, args.out)
    print(f"{args.out}: пройдено {fresh['summary']['passed']}/{fresh['summary']['cases']}")
    if args.summary:
        paths = sorted(args.out.parent.glob("*-rescored.json"))
        data = quality_summary(paths)
        args.summary.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"Сводка: {args.summary}, выбрана {data['selected']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
