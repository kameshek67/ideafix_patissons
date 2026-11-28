"""Оценка справочного поиска помощника (таблица passages) по набору вопросов.

    olymp-eval-rag                                   # data/eval/rag/questions.jsonl -> summary.json
    olymp-eval-rag --questions другой.jsonl --out /tmp/summary.json

Вопросы идут через тот же код поиска, что и инструмент search_references помощника
(olymp_api.modules.assistant.references.search_passages), без LLM. У вопроса есть список
ожиданий: фрагмент подходит, если совпали тип источника, подстрока адреса или заголовка и
обязательная фраза из текста. Ожидание — элемент списка; если ответить может любой из нескольких
источников, на месте ожидания стоит вложенный список вариантов. Идентификаторы фрагментов
не используются: они меняются при пересборке. Вопрос с пустым списком ожиданий — «ответа
в справочнике нет»: смотрим, не выдаёт ли поиск уверенно посторонние фрагменты.

Метрики по первым K выдачи: hit@1/3/5 (есть ли подходящий фрагмент), recall@5 (доля найденных
ожиданий), MRR, nDCG@5; по типам вопросов и типам источников; задержка p50/p95; охват таблицы.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import sys
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
from olymp_api.db import make_engine
from olymp_api.modules.assistant.references import MAX_LIMIT, Reference, search_passages
from olymp_api.settings import Settings
from olymp_db.session import database_url, psycopg_dsn
from sqlalchemy.ext.asyncio import AsyncSession

from .passages import default_data_dir

K = MAX_LIMIT  # столько фрагментов получает помощник
CUTOFFS = (1, 3, 5)
NO_ANSWER = "нет_ответа"
QUESTIONS_FILE = Path("eval/rag/questions.jsonl")
SUMMARY_FILE = Path("eval/rag/summary.json")


class QuestionError(ValueError):
    pass


@dataclass(frozen=True)
class Spec:
    """Признаки нужного фрагмента: тип источника, подстроки адреса и заголовка, фраза из текста."""

    source_type: str
    phrase: str
    url: str = ""
    title: str = ""


# ожидание — один или несколько вариантов; достаточно найти любой
Need = tuple[Spec, ...]


@dataclass(frozen=True)
class Question:
    id: str
    type: str
    text: str
    needs: tuple[Need, ...]

    @property
    def no_answer(self) -> bool:
        return not self.needs


def norm(text: str) -> str:
    return " ".join(text.split()).casefold()


def spec_matches(spec: Spec, ref: Reference) -> bool:
    return (
        ref.source_type == spec.source_type
        and norm(spec.url) in norm(ref.url)
        and norm(spec.title) in norm(ref.title)
        and norm(spec.phrase) in norm(ref.text)
    )


def need_matches(need: Need, ref: Reference) -> bool:
    return any(spec_matches(spec, ref) for spec in need)


def parse_spec(raw: Any, where: str) -> Spec:
    if not isinstance(raw, dict) or not raw.get("source_type") or not raw.get("phrase"):
        raise QuestionError(f"{where}: у ожидания нужны source_type и phrase")
    return Spec(
        str(raw["source_type"]),
        str(raw["phrase"]),
        url=str(raw.get("url") or ""),
        title=str(raw.get("title") or ""),
    )


def parse_question(raw: dict[str, Any], line: int) -> Question:
    where = f"строка {line}"
    for key in ("id", "type", "question"):
        if not raw.get(key):
            raise QuestionError(f"{where}: нет поля {key}")
    needs: list[Need] = []
    for item in raw.get("expect") or []:
        variants = item if isinstance(item, list) else [item]
        if not variants:
            raise QuestionError(f"{where}: пустой список вариантов")
        needs.append(tuple(parse_spec(v, where) for v in variants))
    question = Question(str(raw["id"]), str(raw["type"]), str(raw["question"]), tuple(needs))
    if bool(raw.get("no_answer")) != question.no_answer:
        raise QuestionError(f"{where}: no_answer и список expect не согласуются")
    return question


def load_questions(path: Path) -> list[Question]:
    questions: list[Question] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            questions.append(parse_question(json.loads(line), number))
    ids = [q.id for q in questions]
    if len(set(ids)) != len(ids):
        raise QuestionError("повторяются id вопросов")
    return questions


def gains(needs: Sequence[Need], found: Sequence[Reference], k: int = K) -> list[int]:
    """Выигрыш по позициям выдачи: 1, если фрагмент впервые закрывает очередное ожидание.
    Соседние куски с перекрытием закрывают одно и то же ожидание — повторно не считаются."""
    open_needs = set(range(len(needs)))
    result: list[int] = []
    for ref in found[:k]:
        hit = next((i for i in sorted(open_needs) if need_matches(needs[i], ref)), None)
        if hit is None:
            result.append(0)
        else:
            open_needs.discard(hit)
            result.append(1)
    return result


def first_hit_rank(needs: Sequence[Need], found: Sequence[Reference], k: int = K) -> int | None:
    """Позиция (с 1) первого фрагмента, подходящего под любое ожидание."""
    for position, ref in enumerate(found[:k], 1):
        if any(need_matches(need, ref) for need in needs):
            return position
    return None


def hit_at(rank: int | None, k: int) -> float:
    return 1.0 if rank is not None and rank <= k else 0.0


def recall_at(needs: Sequence[Need], found: Sequence[Reference], k: int = K) -> float:
    return sum(gains(needs, found, k)) / len(needs) if needs else 0.0


def reciprocal_rank(rank: int | None) -> float:
    return 1.0 / rank if rank else 0.0


def ndcg_at(needs: Sequence[Need], found: Sequence[Reference], k: int = K) -> float:
    """nDCG@k с бинарным выигрышем; идеал — все ожидания (не больше k) в начале выдачи."""
    if not needs:
        return 0.0
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains(needs, found, k)))
    ideal = sum(1 / math.log2(i + 2) for i in range(min(len(needs), k)))
    return dcg / ideal


def percentile(values: Sequence[float], share: float) -> float:
    """Перцентиль с линейной интерполяцией; пустой набор — 0."""
    if not values:
        return 0.0
    ordered = sorted(values)
    position = (len(ordered) - 1) * share
    low = math.floor(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


@dataclass
class Outcome:
    question: Question
    found: list[Reference]
    seconds: float
    rank: int | None = field(init=False)

    def __post_init__(self) -> None:
        self.rank = first_hit_rank(self.question.needs, self.found)


def question_metrics(outcome: Outcome) -> dict[str, float]:
    needs, found = outcome.question.needs, outcome.found
    return {
        **{f"hit@{k}": hit_at(outcome.rank, k) for k in CUTOFFS},
        "recall@5": recall_at(needs, found),
        "mrr": reciprocal_rank(outcome.rank),
        "ndcg@5": ndcg_at(needs, found),
    }


def average(outcomes: Sequence[Outcome]) -> dict[str, Any]:
    rows = [question_metrics(o) for o in outcomes]
    result: dict[str, Any] = {"questions": len(outcomes)}
    for key in ("hit@1", "hit@3", "hit@5", "recall@5", "mrr", "ndcg@5"):
        result[key] = round(mean([row[key] for row in rows]), 3)
    return result


def by_source_type(outcomes: Sequence[Outcome]) -> dict[str, dict[str, Any]]:
    """Какие источники находятся: ожидания по типу источника и доля найденных в первых K."""
    total: dict[str, int] = defaultdict(int)
    found_count: dict[str, int] = defaultdict(int)
    for outcome in outcomes:
        needs = outcome.question.needs
        closed = _closed_needs(needs, outcome.found)
        for index, need in enumerate(needs):
            kind = need[0].source_type
            total[kind] += 1
            found_count[kind] += index in closed
    return {
        kind: {
            "expectations": total[kind],
            "found@5": found_count[kind],
            "recall@5": round(found_count[kind] / total[kind], 3),
        }
        for kind in sorted(total)
    }


def _closed_needs(needs: Sequence[Need], found: Sequence[Reference]) -> set[int]:
    return {i for i, need in enumerate(needs) if any(need_matches(need, ref) for ref in found[:K])}


def no_answer_report(outcomes: Sequence[Outcome], answered: Sequence[Outcome]) -> dict[str, Any]:
    """Вопросы без ответа: пустая выдача — правильный исход. Остальное — фрагменты-«мусор»;
    для выбора порога сравниваем ранг лучшего фрагмента с рангом первого верного у вопросов с ответом."""
    empty = sum(1 for o in outcomes if not o.found)
    top = [o.found[0].rank for o in outcomes if o.found]
    good = [o.found[o.rank - 1].rank for o in answered if o.rank is not None]
    return {
        "questions": len(outcomes),
        "empty_share": round(empty / len(outcomes), 3) if outcomes else 0.0,
        "top_rank_median": round(percentile(top, 0.5), 3),
        "top_rank_max": round(max(top, default=0.0), 3),
        "right_rank_median": round(percentile(good, 0.5), 3),
        "right_rank_p10": round(percentile(good, 0.1), 3),
    }


def latency(outcomes: Sequence[Outcome]) -> dict[str, float]:
    millis = [o.seconds * 1000 for o in outcomes]
    return {
        "p50_ms": round(percentile(millis, 0.5), 1),
        "p95_ms": round(percentile(millis, 0.95), 1),
        "max_ms": round(max(millis, default=0.0), 1),
    }


def summarize(outcomes: Sequence[Outcome]) -> dict[str, Any]:
    answered = [o for o in outcomes if not o.question.no_answer]
    empty = [o for o in outcomes if o.question.no_answer]
    types: dict[str, list[Outcome]] = defaultdict(list)
    for o in answered:
        types[o.question.type].append(o)
    return {
        "k": K,
        "questions": len(outcomes),
        "with_answer": average(answered),
        "by_question_type": {name: average(items) for name, items in sorted(types.items())},
        "by_source_type": by_source_type(answered),
        "no_answer": no_answer_report(empty, answered),
        "latency": latency(outcomes),
        "misses": [o.question.id for o in answered if o.rank is None],
    }


Search = Callable[[str], Awaitable[list[Reference]]]


async def run_questions(
    questions: Sequence[Question], search: Search, repeats: int = 1
) -> list[Outcome]:
    """Каждый вопрос — один поиск; для задержки берём лучшую из repeats попыток (без разогрева кэша
    базы она завышена), выдача — от последней."""
    outcomes: list[Outcome] = []
    for question in questions:
        best = math.inf
        found: list[Reference] = []
        for _ in range(max(1, repeats)):
            started = time.perf_counter()
            found = await search(question.text)
            best = min(best, time.perf_counter() - started)
        outcomes.append(Outcome(question, found, best))
    return outcomes


def unresolved(questions: Sequence[Question], passages: Sequence[Reference]) -> list[str]:
    """Ожидания, которым не отвечает ни один фрагмент таблицы: данные разошлись с набором."""
    bad: list[str] = []
    for question in questions:
        for index, need in enumerate(question.needs, 1):
            if not any(need_matches(need, p) for p in passages):
                bad.append(f"{question.id}#{index}")
    return bad


def coverage(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    """Что лежит в справочнике: фрагменты и документы по типам, вузы, длина, страницы."""
    with conn.cursor() as cur:
        cur.execute(
            """SELECT source_type, count(*), count(DISTINCT url), round(avg(length(body))),
                      count(page)
               FROM passages GROUP BY source_type ORDER BY source_type"""
        )
        kinds = cur.fetchall()
        cur.execute("SELECT count(*) FROM universities")
        universities = cur.fetchone()
        cur.execute(
            """SELECT count(DISTINCT d.university_id) FROM university_documents d
               WHERE EXISTS (SELECT 1 FROM passages p WHERE p.url = d.url)"""
        )
        with_documents = cur.fetchone()
        cur.execute("SELECT count(DISTINCT url) FROM university_documents")
        listed = cur.fetchone()
        cur.execute(
            """SELECT count(DISTINCT d.url) FROM university_documents d
               WHERE EXISTS (SELECT 1 FROM passages p WHERE p.url = d.url)"""
        )
        indexed = cur.fetchone()
    total = sum(int(row[1]) for row in kinds)
    pages = sum(int(row[4]) for row in kinds)
    weighted = sum(int(row[1]) * int(row[3]) for row in kinds)
    return {
        "passages": total,
        "by_source_type": {
            str(row[0]): {"passages": int(row[1]), "documents": int(row[2])} for row in kinds
        },
        "documents": sum(int(row[2]) for row in kinds),
        "universities_in_base": int(universities[0]) if universities else 0,
        "universities_with_documents": int(with_documents[0]) if with_documents else 0,
        "university_documents_listed": int(listed[0]) if listed else 0,
        "university_documents_indexed": int(indexed[0]) if indexed else 0,
        "avg_passage_chars": round(weighted / total) if total else 0,
        "page_share": round(pages / total, 3) if total else 0.0,
    }


def all_passages(conn: psycopg.Connection[Any]) -> list[Reference]:
    with conn.cursor() as cur:
        cur.execute("SELECT source_type, title, url, page, body FROM passages")
        return [Reference(r[0], r[1], r[2], r[3], r[4], 0.0) for r in cur.fetchall()]


async def evaluate(
    questions: Sequence[Question], db_url: str, repeats: int
) -> tuple[list[Outcome], list[Reference]]:
    engine = make_engine(Settings(database_url=db_url))
    if engine is None:
        raise SystemExit("нужен адрес базы: OLYMP_DATABASE_URL или --database-url")
    try:
        async with AsyncSession(engine) as session:

            async def search(text: str) -> list[Reference]:
                return await search_passages(session, text, K)

            await search("разогрев")  # соединение и кэш страниц базы не должны попасть в задержку
            outcomes = await run_questions(questions, search, repeats)
    finally:
        await engine.dispose()
    with psycopg.connect(psycopg_dsn(db_url), connect_timeout=5) as conn:
        return outcomes, all_passages(conn)


def format_report(summary: dict[str, Any]) -> str:
    with_answer = summary["with_answer"]
    lines = [
        f"вопросов {summary['questions']} (с ответом {with_answer['questions']}), выдача по {summary['k']}",
        f"{'':28} hit@1  hit@3  hit@5  recall@5   MRR  nDCG@5",
    ]

    def row(name: str, data: dict[str, Any]) -> str:
        return (
            f"{name:28} {data['hit@1']:5.2f}  {data['hit@3']:5.2f}  {data['hit@5']:5.2f}"
            f"  {data['recall@5']:8.2f}  {data['mrr']:4.2f}  {data['ndcg@5']:6.2f}"
        )

    lines.append(row("все с ответом", with_answer))
    lines += [row(name, data) for name, data in summary["by_question_type"].items()]
    lines.append("источники (найдено в первых 5 от ожидавшихся):")
    for name, data in summary["by_source_type"].items():
        lines.append(
            f"  {name:22} {data['found@5']}/{data['expectations']} = {data['recall@5']:.2f}"
        )
    none = summary["no_answer"]
    lines.append(
        f"без ответа: пустых выдач {none['empty_share']:.0%} из {none['questions']}; "
        f"ранг лучшего фрагмента: медиана {none['top_rank_median']}, максимум {none['top_rank_max']}; "
        f"у верных ответов медиана {none['right_rank_median']}, p10 {none['right_rank_p10']}"
    )
    lat = summary["latency"]
    lines.append(f"задержка: p50 {lat['p50_ms']} мс, p95 {lat['p95_ms']} мс")
    cov = summary["coverage"]
    lines.append(
        f"охват: {cov['passages']} фрагментов, {cov['documents']} документов, вузов с документами "
        f"{cov['universities_with_documents']} из {cov['universities_in_base']}, "
        f"средняя длина {cov['avg_passage_chars']}, доля с номером страницы {cov['page_share']:.0%}"
    )
    if summary["misses"]:
        lines.append("не найдены в первых 5: " + ", ".join(summary["misses"]))
    return "\n".join(lines)


def main() -> int:
    data_dir = default_data_dir()
    parser = argparse.ArgumentParser(description="Оценка справочного поиска помощника без LLM")
    parser.add_argument("--database-url", default=database_url())
    parser.add_argument("--questions", type=Path, default=data_dir / QUESTIONS_FILE)
    parser.add_argument("--out", type=Path, default=data_dir / SUMMARY_FILE)
    parser.add_argument("--repeats", type=int, default=3, help="поисков на вопрос для задержки")
    args = parser.parse_args()
    try:
        questions = load_questions(args.questions)
    except (OSError, ValueError) as exc:
        print(f"не удалось прочитать вопросы: {exc}", file=sys.stderr)
        return 2
    outcomes, passages = asyncio.run(evaluate(questions, args.database_url, args.repeats))
    summary = summarize(outcomes)
    missing = unresolved(questions, passages)
    with psycopg.connect(psycopg_dsn(args.database_url), connect_timeout=5) as conn:
        summary["coverage"] = coverage(conn)
    summary["unresolved_expectations"] = missing
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    print(format_report(summary))
    if missing:
        print("ожиданий без фрагментов в таблице: " + ", ".join(missing), file=sys.stderr)
    print(f"сводка: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
