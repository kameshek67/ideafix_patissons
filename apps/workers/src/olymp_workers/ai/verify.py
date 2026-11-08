"""ИИ-сверщик строк льгот с документами вузов (F-07, T-087).

    olymp-ai-verify --sample 100 --seed 2026 --out ai-verify.csv
    olymp-ai-verify --university итмо --limit 20
    olymp-ai-verify --sample 30 --dry-run     # без модели: какие страницы нашлись

Модель предлагает вердикт с цитатой, код ищет цитату на странице (olymp_domain.verify), решает
человек по отчёту. Базу сверщик не меняет. Модель — OLYMP_PARSER_MODEL или OLYMP_LLM_MODEL.
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
import re
import sys
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from olymp_db.session import psycopg_dsn
from olymp_domain.verify import (
    DRY_RUN,
    ERROR,
    NO_DOCUMENT,
    NO_MENTION,
    UNVERIFIED,
    AnswerError,
    Page,
    RowKeys,
    Verdict,
    parse_answer,
    reconcile,
    select_pages,
)
from olymp_llm import LLMError, LLMProvider, OpenAICompatibleProvider, complete, provider_from_env
from psycopg.rows import dict_row

from .documents import DEFAULT_CACHE, DocumentError, DocumentStore
from .prompts import RETRY_TEMPLATE, VERIFY_PROMPT_VERSION, VERIFY_SYSTEM

MAX_DOCUMENTS = 8
MAX_ERRORS_IN_ROW = 3  # подряд: провайдер лежит — нет смысла тратить время
DEFAULT_REPORTS = Path(".cache/olymp/reports")

COLUMNS = [
    "university",
    "program_code",
    "program",
    "benefit_type",
    "olympiads",
    "profile",
    "level",
    "winner_role",
    "grade",
    "confirm_subject",
    "min_ege",
    "status",
    "document",
    "page",
    "quote",
    "mismatches",
    "comment",
    "model",
    "prompt_version",
    "checked_at",
]


@dataclass
class Row:
    """Строка льготы с тем, что нужно для поиска и для модели."""

    benefit_id: int
    university: str
    university_id: int
    program_code: str
    program: str
    program_profile: str
    benefit_type: str
    profile: str
    subject: str
    level: str
    winner_role: str
    grade: str
    confirm_subject: str
    min_ege: str
    years: str
    source_url: str
    program_url: str
    olympiads: list[str] = field(default_factory=list)
    aliases: list[str] = field(default_factory=list)
    documents: list[str] = field(default_factory=list)

    def keys(self) -> RowKeys:
        return RowKeys(
            olympiad_names=tuple(self.aliases),
            profile=self.profile or self.subject,
            program_code=self.program_code,
            program_name=self.program,
        )

    def claims(self) -> dict[str, str]:
        """Описание строки для модели: только данные льготы, без служебных id."""
        claims = {
            "вуз": self.university,
            "направление": " ".join(filter(None, [self.program_code, self.program])),
            "профиль направления": self.program_profile,
            "льгота": self.benefit_type,
            "олимпиада": "; ".join(self.olympiads),
            "профиль олимпиады": self.profile or self.subject,
            "уровень олимпиады": self.level,
            "степень диплома": self.winner_role,
            "класс": self.grade,
            "предмет ЕГЭ для подтверждения": self.confirm_subject,
            "минимальный балл ЕГЭ": self.min_ege,
            "годы олимпиады": self.years,
        }
        return {k: v for k, v in claims.items() if v}

    def candidate_documents(self) -> list[str]:
        seen: list[str] = []
        for url in [self.source_url, self.program_url, *self.documents]:
            url = (url or "").strip()
            if url and url not in seen:
                seen.append(url)
        return seen[:MAX_DOCUMENTS]


# ---------------------------------------------------------------- строки из базы

ROW_SQL = """
SELECT b.id AS benefit_id, b.benefit_type, b.olympiad_profile AS profile,
       b.olympiad_subject AS subject, b.level, b.winner_role, b.grade, b.confirm_subject,
       b.min_ege, b.years, b.source_url, p.code AS program_code,
       p.faculty_or_direction AS program, p.profile_name AS program_profile,
       p.source_url AS program_url, u.id AS university_id, u.name AS university
FROM benefits b
JOIN programs p ON p.id = b.program_id
JOIN universities u ON u.id = p.university_id
"""


def candidate_ids(conn: psycopg.Connection[Any], layer: str, university: str | None) -> list[int]:
    """id строк в стабильном порядке: выборка с тем же seed повторяется на тех же данных."""
    rows = conn.execute(
        """SELECT b.id, u.name, u.short_name FROM benefits b
           JOIN programs p ON p.id = b.program_id
           JOIN universities u ON u.id = p.university_id
           WHERE b.layer = %s
             AND EXISTS (SELECT 1 FROM benefit_olympiads bo WHERE bo.benefit_id = b.id)
           ORDER BY u.name, p.code, p.faculty_or_direction, b.benefit_type,
                    b.raw_conditions_text, b.id""",
        (layer,),
    ).fetchall()
    return [row[0] for row in rows if matches_university(university, f"{row[1]} {row[2] or ''}")]


def _words(text: str) -> list[str]:
    return re.findall(r"[a-zа-я0-9]+", text.lower().replace("ё", "е"))


def matches_university(query: str | None, name: str) -> bool:
    """Каждое слово запроса — начало какого-то слова в названии: «мгу» найдёт МГУ, но не
    «им. И.М. Губкина», где склеенный текст тоже содержит «мгу»."""
    words = _words(name)
    return all(any(w.startswith(q) for w in words) for q in _words(query or ""))


def pick(ids: Sequence[int], sample: int | None, limit: int | None, seed: int) -> list[int]:
    if sample:
        return random.Random(seed).sample(list(ids), min(sample, len(ids)))
    return list(ids[:limit] if limit else ids)


def load_rows(conn: psycopg.Connection[Any], ids: Sequence[int]) -> list[Row]:
    if not ids:
        return []
    with conn.cursor(row_factory=dict_row) as cur:
        base = {
            r["benefit_id"]: Row(**r)
            for r in cur.execute(ROW_SQL + " WHERE b.id = ANY(%s)", (list(ids),)).fetchall()
        }
        for r in cur.execute(
            """SELECT bo.benefit_id, o.id AS olympiad_id, o.canonical_name, o.short_name
               FROM benefit_olympiads bo JOIN olympiads o ON o.id = bo.olympiad_id
               WHERE bo.benefit_id = ANY(%s) ORDER BY o.mentions DESC, bo.id""",
            (list(ids),),
        ).fetchall():
            row = base[r["benefit_id"]]
            name = r["canonical_name"] or r["short_name"]
            if name not in row.olympiads:
                row.olympiads.append(name)
        aliases: dict[int, list[str]] = {}
        for r in cur.execute(
            """SELECT bo.benefit_id, a.alias FROM benefit_olympiads bo
               JOIN olympiad_aliases a ON a.olympiad_id = bo.olympiad_id
               WHERE bo.benefit_id = ANY(%s) AND a.is_generic = 0
               ORDER BY length(a.alias) DESC""",
            (list(ids),),
        ).fetchall():
            aliases.setdefault(r["benefit_id"], []).append(r["alias"])
        documents: dict[int, list[str]] = {}
        for r in cur.execute(
            "SELECT university_id, url FROM university_documents ORDER BY id"
        ).fetchall():
            documents.setdefault(r["university_id"], []).append(r["url"])
    rows = []
    for benefit_id in ids:
        found = base.get(benefit_id)
        if found is None:
            continue
        names = [*found.olympiads, *aliases.get(benefit_id, [])]
        found.aliases = list(dict.fromkeys(names))
        found.documents = documents.get(found.university_id, [])
        rows.append(found)
    return rows


# ---------------------------------------------------------------- сверка одной строки


@dataclass
class Outcome:
    row: Row
    verdict: Verdict
    requests: int = 0
    document: str = ""


def gather_pages(row: Row, store: DocumentStore) -> tuple[list[Page], list[str]]:
    """Страницы всех доступных документов строки и причины, по которым остальные недоступны."""
    pages: list[Page] = []
    problems: list[str] = []
    for url in row.candidate_documents():
        try:
            document = store.get(url)
        except DocumentError as exc:
            problems.append(f"{url}: {exc}")
            continue
        pages += [Page(url, n, text) for n, text in enumerate(document.pages, start=1)]
    return pages, problems


def user_message(row: Row, pages: Sequence[Page]) -> str:
    payload = {
        "строка": row.claims(),
        "страницы": [
            {"метка": p.label, "страница документа": p.number, "текст": p.text} for p in pages
        ],
    }
    return json.dumps(payload, ensure_ascii=False, indent=1)


async def ask_model(provider: LLMProvider, row: Row, pages: Sequence[Page]) -> tuple[Verdict, int]:
    """Вердикт по выбранным страницам и число запросов к модели (повтор при ответе не по схеме)."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": VERIFY_SYSTEM},
        {"role": "user", "content": user_message(row, pages)},
    ]
    for attempt in (1, 2):
        text = await complete(provider, messages)
        try:
            return reconcile(parse_answer(text), pages, row.keys()), attempt
        except AnswerError as exc:
            if attempt == 2:
                return Verdict(UNVERIFIED, comment=f"ответ модели не по схеме: {exc}"), attempt
            messages += [
                {"role": "assistant", "content": text[:4000]},
                {"role": "user", "content": RETRY_TEMPLATE.format(error=exc)},
            ]
    raise AssertionError("недостижимо")


async def verify_row(row: Row, store: DocumentStore, provider: LLMProvider | None) -> Outcome:
    pages, problems = gather_pages(row, store)
    if not pages:
        reason = "; ".join(problems) or "у строки и вуза нет ссылок на документы"
        return Outcome(row, Verdict(NO_DOCUMENT, comment=reason[:300]))
    selected = select_pages(row.keys(), pages)
    if not selected:
        checked = sorted({p.document_url for p in pages})
        comment = "олимпиада не упомянута в документах: " + ", ".join(checked)
        return Outcome(row, Verdict(NO_MENTION, comment=comment[:300]))
    if provider is None:
        where = ", ".join(f"{p.document_url} стр. {p.number}" for p in selected)
        return Outcome(row, Verdict(DRY_RUN, comment=f"страницы: {where}"[:300]))
    try:
        verdict, requests = await ask_model(provider, row, selected)
    except LLMError as exc:
        return Outcome(row, Verdict(ERROR, comment=f"провайдер: {exc}"[:300]), requests=1)
    document = verdict.page.document_url if verdict.page else ""
    return Outcome(row, verdict, requests, document)


# ---------------------------------------------------------------- отчёт


def cell(value: object) -> str:
    """Значение для CSV: без переносов и без формул Excel (=, +, -, @ в начале ячейки)."""
    text = " ".join(str(value or "").split())
    return "'" + text if text[:1] in ("=", "+", "-", "@") else text


def report_row(outcome: Outcome, model: str) -> dict[str, str]:
    row, verdict = outcome.row, outcome.verdict
    values: dict[str, object] = {
        "university": row.university,
        "program_code": row.program_code,
        "program": row.program,
        "benefit_type": row.benefit_type,
        "olympiads": "; ".join(row.olympiads),
        "profile": row.profile or row.subject,
        "level": row.level,
        "winner_role": row.winner_role,
        "grade": row.grade,
        "confirm_subject": row.confirm_subject,
        "min_ege": row.min_ege,
        "status": verdict.status,
        "document": outcome.document,
        "page": verdict.page.number if verdict.page else "",
        "quote": verdict.quote,
        "mismatches": "; ".join(f"{m.field}: {m.document}" for m in verdict.mismatches),
        "comment": verdict.comment,
        "model": model,
        "prompt_version": VERIFY_PROMPT_VERSION,
        "checked_at": datetime.now(UTC).date().isoformat(),
    }
    return {key: cell(values[key]) for key in COLUMNS}


# ---------------------------------------------------------------- запуск


@dataclass
class RunResult:
    outcomes: list[Outcome]
    requests: int
    stopped: str = ""


async def run(
    rows: Sequence[Row],
    store: DocumentStore,
    provider: LLMProvider | None,
    *,
    max_requests: int,
    pause: float = 0,
    progress: bool = True,
) -> RunResult:
    result = RunResult([], 0)
    errors_in_row = 0
    for index, row in enumerate(rows, start=1):
        if provider is not None and result.requests + 2 > max_requests:
            result.stopped = f"лимит запросов к модели ({max_requests})"
            break
        outcome = await verify_row(row, store, provider)
        result.outcomes.append(outcome)
        result.requests += outcome.requests
        errors_in_row = errors_in_row + 1 if outcome.verdict.status == ERROR else 0
        if progress:
            print(
                f"[{index}/{len(rows)}] {row.university[:28]} · {row.program_code} · "
                f"{row.benefit_type} · {(row.olympiads or ['?'])[0][:40]} → {outcome.verdict.status}",
                flush=True,
            )
        if errors_in_row >= MAX_ERRORS_IN_ROW:
            result.stopped = "провайдер не отвечает несколько раз подряд"
            break
        if outcome.requests and pause:
            await asyncio.sleep(pause)
    return result


def write_report(path: Path, outcomes: Sequence[Outcome], model: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for outcome in outcomes:
            writer.writerow(report_row(outcome, model))


def parse_args(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="olymp-ai-verify",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--sample", type=int, help="случайная выборка из N строк")
    parser.add_argument("--seed", type=int, default=2026, help="seed выборки (по умолчанию 2026)")
    parser.add_argument("--limit", type=int, help="первые N строк (без --sample)")
    parser.add_argument("--university", help="только вуз, часть названия: «итмо», «вшэ»")
    parser.add_argument("--layer", default="detailed", choices=["detailed", "derived"])
    parser.add_argument("--out", type=Path, help="куда записать CSV-отчёт")
    parser.add_argument("--max-requests", type=int, default=200, help="лимит запросов к модели")
    parser.add_argument("--pause", type=float, default=1.0, help="пауза между запросами, с")
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--dry-run", action="store_true", help="без модели: только поиск страниц")
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="скачивать документы без проверки TLS-сертификата (только если сайт иначе недоступен)",
    )
    args = parser.parse_args(argv)
    if not args.sample and not args.limit:
        args.sample = 20
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    provider: OpenAICompatibleProvider | None = None
    if not args.dry_run:
        provider = provider_from_env(model_var="OLYMP_PARSER_MODEL")
        if provider is None:
            print(
                "Нужны OLYMP_LLM_BASE_URL, OLYMP_LLM_API_KEY и OLYMP_PARSER_MODEL или "
                "OLYMP_LLM_MODEL (или --dry-run).",
                file=sys.stderr,
            )
            return 2
        provider.temperature = 0
    with psycopg.connect(psycopg_dsn()) as conn:
        ids = pick(
            candidate_ids(conn, args.layer, args.university), args.sample, args.limit, args.seed
        )
        rows = load_rows(conn, ids)
    if not rows:
        print("Нет строк под фильтр.", file=sys.stderr)
        return 1

    model = provider.model_label if provider else "—"
    print(f"Строк: {len(rows)}, модель: {model}, лимит запросов: {args.max_requests}", flush=True)
    started = time.perf_counter()
    store = DocumentStore(args.cache_dir, insecure=args.insecure)
    try:
        result = asyncio.run(
            run(rows, store, provider, max_requests=args.max_requests, pause=args.pause)
        )
    finally:
        store.close()

    out = args.out or DEFAULT_REPORTS / f"ai-verify-{datetime.now():%Y%m%d-%H%M%S}.csv"
    write_report(out, result.outcomes, model)
    counts = Counter(o.verdict.status for o in result.outcomes)
    print(
        f"\nГотово за {time.perf_counter() - started:.0f} с: проверено {len(result.outcomes)} "
        f"из {len(rows)}, запросов к модели {result.requests}, скачано документов {store.downloads}"
    )
    for status, count in counts.most_common():
        print(f"  {status:13} {count}")
    if result.stopped:
        print(f"Остановлено: {result.stopped}")
    print(f"Отчёт: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
