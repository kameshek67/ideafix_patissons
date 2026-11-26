"""Оценка извлечения льгот из документов по эталону (docs/plan.md, «Метрики»).

    olymp-eval-extract --gold data/eval/extraction --pred data/extracted
    olymp-eval-extract --gold data/eval/extraction --pred db          # то, что сейчас в базе (XLSX и слой document)
    olymp-eval-extract --gold data/eval/extraction --pred data/extracted --check-quotes --json out.json

Считается только то, что лежит на размеченных страницах документа (document.pages эталона)
и, у таблиц, в размеченных строках (document.rows): предсказания вне них не штрафуются.
Записи совпадают по ключу (вуз, код направления, олимпиада, профиль, тип льготы); поля
сравниваются у совпавших. Код «*» в эталоне — любое направление вуза: ему отвечает любая запись
с тем же остальным ключом, а остальные такие записи при других кодах не считаются лишними.
Без --check-quotes сеть не нужна.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from olymp_domain.extraction import (
    ExtractionError,
    ExtractionFile,
    Record,
    load_dir,
    olympiad_key,
    profile_key,
    quote_found,
    record_key,
)
from olymp_domain.textutils import clean_text, norm_role, squash

from .ai.documents import DEFAULT_CACHE, DocumentError, DocumentStore

Key = tuple[str, str, str, str, str]
FIELDS = ("winner_role", "levels", "grades", "ege_min", "ege_subjects")
# пороги из плана: ниже — вуз разбираем, но каждую запись смотрит человек
MIN_PRECISION = 0.95
MIN_RECALL = 0.90


@dataclass
class Row:
    """Запись в виде, удобном для сравнения (из файла или из базы)."""

    key: Key
    winner_role: str | None
    levels: frozenset[int]
    grades: frozenset[int]
    ege_min: int | None
    ege_subjects: frozenset[str]
    page: int | None = None  # None — у выгрузки из базы страниц нет
    row: int | None = None
    url: str = ""
    quote: str = ""

    def values(self) -> dict[str, Any]:
        return {f: getattr(self, f) for f in FIELDS}

    def empty_fields(self) -> int:
        return sum(1 for v in self.values().values() if v in (None, frozenset()))


def row_of(record: Record) -> Row:
    ege = record.ege
    return Row(
        key=record_key(record),
        winner_role=record.winner_role,
        levels=frozenset(record.levels),
        grades=frozenset(record.grades),
        ege_min=ege.min if ege else None,
        ege_subjects=frozenset(ege.subjects) if ege else frozenset(),
        page=record.source.page,
        row=record.source.row,
        url=record.source.url,
        quote=record.source.quote,
    )


# ---------------------------------------------------------------- сопоставление


def _agreement(a: Row, b: Row) -> int:
    return sum(1 for f in FIELDS if getattr(a, f) == getattr(b, f))


ANY_CODE = "*"


def _tail(key: Key) -> tuple[str, ...]:
    """Ключ без кода направления."""
    return key[0], *key[2:]


def _no_profile(key: Key) -> tuple[str, ...]:
    """Ключ без кода и профиля: старая база профиль не хранит."""
    return key[0], key[1], key[2], key[4]


def match_rows(
    gold: Sequence[Row], pred: Sequence[Row], *, loose_profile: bool = False
) -> list[tuple[Row, Row]]:
    """Пары «эталон — предсказание» по ключу; при повторах ключа первыми берутся лучшие по полям.

    У эталона с кодом «*» кандидаты — записи с любым кодом. С loose_profile оставшиеся записи
    без профиля (выгрузка из старой базы) подходят эталону с любым профилем."""
    by_key: dict[Key, list[int]] = defaultdict(list)
    by_tail: dict[tuple[str, ...], list[int]] = defaultdict(list)
    by_bare: dict[tuple[str, ...], list[int]] = defaultdict(list)
    for j, p in enumerate(pred):
        by_key[p.key].append(j)
        by_tail[_tail(p.key)].append(j)
        if loose_profile and not p.key[3]:
            by_bare[_no_profile(p.key)].append(j)
    used_gold: set[int] = set()
    used_pred: set[int] = set()
    pairs: list[tuple[Row, Row]] = []

    def take(candidates: list[tuple[int, int, int]]) -> None:
        candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
        for _, i, j in candidates:
            if i in used_gold or j in used_pred:
                continue
            used_gold.add(i)
            used_pred.add(j)
            pairs.append((gold[i], pred[j]))

    take(
        [
            (_agreement(g, pred[j]), i, j)
            for i, g in enumerate(gold)
            for j in (by_tail[_tail(g.key)] if g.key[1] == ANY_CODE else by_key.get(g.key, ()))
        ]
    )
    if loose_profile:
        take(
            [
                (_agreement(g, pred[j]), i, j)
                for i, g in enumerate(gold)
                if i not in used_gold and g.key[3]
                for j in by_bare.get(_no_profile(g.key), ())
                if j not in used_pred
            ]
        )
    return pairs


# ---------------------------------------------------------------- цитаты


class QuoteChecker:
    """Ищет цитаты на страницах документов; документ скачивается один раз и кэшируется."""

    def __init__(self, store: DocumentStore) -> None:
        self.store = store
        self.problems: dict[str, str] = {}

    def check(self, rows: Sequence[Row]) -> tuple[int, int, int]:
        """(найдено, не найдено, не проверено) по записям с цитатой."""
        found = missing = unchecked = 0
        for row in rows:
            if not row.quote or row.page is None:
                continue
            try:
                document = self.store.get(row.url)
            except DocumentError as exc:
                self.problems[row.url] = str(exc)
                unchecked += 1
                continue
            if not 1 <= row.page <= len(document.pages):
                missing += 1
            elif quote_found(row.quote, document.pages[row.page - 1]):
                found += 1
            else:
                missing += 1
        return found, missing, unchecked


# ---------------------------------------------------------------- метрики


@dataclass
class DocResult:
    name: str
    university: str
    gold: int = 0
    pred: int = 0
    matched: int = 0
    field_ok: dict[str, int] = field(default_factory=lambda: dict.fromkeys(FIELDS, 0))
    role_wrong: int = 0  # «кому» названо, но неверно: хуже, чем честное «не сказано»
    empty: int = 0
    pred_fields: int = 0
    quotes: tuple[int, int, int] | None = None
    gold_quotes: tuple[int, int, int] | None = None
    note: str = ""

    @property
    def precision(self) -> float | None:
        return self.matched / self.pred if self.pred else None

    @property
    def recall(self) -> float | None:
        return self.matched / self.gold if self.gold else None

    def field_accuracy(self, name: str) -> float | None:
        return self.field_ok[name] / self.matched if self.matched else None

    @property
    def quote_rate(self) -> float | None:
        return _rate(self.quotes)

    @property
    def gold_quote_rate(self) -> float | None:
        return _rate(self.gold_quotes)

    @property
    def empty_rate(self) -> float | None:
        return self.empty / self.pred_fields if self.pred_fields else None

    @property
    def passes(self) -> bool:
        """Порог плана для автоматического разбора вуза."""
        return (
            self.precision is not None
            and self.recall is not None
            and self.precision >= MIN_PRECISION
            and self.recall >= MIN_RECALL
            and self.role_wrong == 0
        )

    def add(self, other: DocResult) -> None:
        for name in ("gold", "pred", "matched", "role_wrong", "empty", "pred_fields"):
            setattr(self, name, getattr(self, name) + getattr(other, name))
        for name in FIELDS:
            self.field_ok[name] += other.field_ok[name]
        self.quotes = _add3(self.quotes, other.quotes)
        self.gold_quotes = _add3(self.gold_quotes, other.gold_quotes)

    def as_json(self) -> dict[str, Any]:
        return {
            "document": self.name,
            "university": self.university,
            "gold": self.gold,
            "pred": self.pred,
            "matched": self.matched,
            "precision": self.precision,
            "recall": self.recall,
            "fields": {f: self.field_accuracy(f) for f in FIELDS},
            "role_wrong": self.role_wrong,
            "quotes": _quotes_json(self.quotes),
            "gold_quotes": _quotes_json(self.gold_quotes),
            "empty_rate": self.empty_rate,
            "passes": self.passes,
            "note": self.note,
        }


def _rate(q: tuple[int, int, int] | None) -> float | None:
    if q is None or q[0] + q[1] == 0:
        return None
    return q[0] / (q[0] + q[1])


def _add3(
    a: tuple[int, int, int] | None, b: tuple[int, int, int] | None
) -> tuple[int, int, int] | None:
    if a is None or b is None:
        return a or b
    return a[0] + b[0], a[1] + b[1], a[2] + b[2]


def _quotes_json(q: tuple[int, int, int] | None) -> dict[str, Any] | None:
    if q is None:
        return None
    return {"found": q[0], "not_found": q[1], "unchecked": q[2], "rate": _rate(q)}


def evaluate_document(
    name: str,
    gold: ExtractionFile,
    pred_rows: Sequence[Row],
    *,
    checker: QuoteChecker | None = None,
    note: str = "",
    loose_profile: bool = False,
) -> DocResult:
    """Метрики одного документа; pred_rows уже сужены до страниц эталона."""
    gold_rows = [row_of(r) for r in gold.records]
    pairs = match_rows(gold_rows, pred_rows, loose_profile=loose_profile)
    # записи с другими кодами при эталоне «*» — тот же случай, а не лишние
    any_code = {_tail(g.key) for g in gold_rows if g.key[1] == ANY_CODE}
    used = {id(p) for _, p in pairs}
    spread = sum(1 for p in pred_rows if _tail(p.key) in any_code and id(p) not in used)
    result = DocResult(
        name, gold.document.university, gold=len(gold_rows), pred=len(pred_rows) - spread
    )
    result.note = note
    result.matched = len(pairs)
    for g, p in pairs:
        for f in FIELDS:
            if getattr(g, f) == getattr(p, f):
                result.field_ok[f] += 1
        if p.winner_role is not None and p.winner_role != g.winner_role:
            result.role_wrong += 1
    result.pred_fields = result.pred * len(FIELDS)
    result.empty = sum(r.empty_fields() for r in pred_rows)
    if checker is not None:
        result.gold_quotes = checker.check(gold_rows)
        if any(r.quote for r in pred_rows):
            result.quotes = checker.check(pred_rows)
    return result


def in_scope(
    rows: Sequence[Row], pages: Sequence[int], span: tuple[int, int] | None = None
) -> list[Row]:
    """Записи на размеченных страницах и строках; где страница или строка неизвестны — остаются."""
    wanted = set(pages)
    return [
        r
        for r in rows
        if (r.page is None or r.page in wanted)
        and (span is None or r.row is None or span[0] <= r.row <= span[1])
    ]


def find_pred(
    name: str, gold: ExtractionFile, preds: dict[str, ExtractionFile]
) -> ExtractionFile | None:
    """Файл предсказаний для документа: по адресу, потом по хэшу, потом по имени файла."""
    doc = gold.document
    for p in preds.values():
        if p.document.url == doc.url:
            return p
    for p in preds.values():
        if p.document.sha256 == doc.sha256:
            return p
    return preds.get(name)


# ---------------------------------------------------------------- выгрузка из базы

RE_CODE = re.compile(r"\d{2}\.\d{2}\.\d{2}")
DB_TYPES = {"БВИ": "bvi", "100 баллов": "100", "ИД (доп. баллы)": "extra_points"}
DB_SQL = """
SELECT u.name AS university, p.code, p.faculty_or_direction AS direction,
       b.benefit_type, b.source_url,
       COALESCE(NULLIF(bo.winner_role, ''), b.winner_role) AS winner_role,
       COALESCE(NULLIF(bo.level, ''), b.level) AS level,
       COALESCE(NULLIF(bo.profile, ''), b.olympiad_profile) AS profile,
       b.grade, b.confirm_subjects, b.min_ege_score, o.canonical_name AS olympiad
FROM benefits b
JOIN programs p ON p.id = b.program_id
JOIN universities u ON u.id = p.university_id
JOIN benefit_olympiads bo ON bo.benefit_id = b.id
JOIN olympiads o ON o.id = bo.olympiad_id
WHERE b.layer IN ('detailed', 'derived', 'document') AND u.id = %s
ORDER BY b.id, bo.id
"""
RE_IMENI = re.compile(r"\bимени\b", re.IGNORECASE)
ROMAN_LEVELS = {"I": 1, "II": 2, "III": 3}


def db_role(value: str) -> str | None:
    role = norm_role(value)
    return {
        "победители": "winner",
        "только победители": "winner",
        "призёры": "prizewinner",
        "победители и призёры": "both",
    }.get(role)


def db_levels(value: str) -> frozenset[int]:
    return frozenset(ROMAN_LEVELS[t] for t in re.findall(r"\bIII\b|\bII\b|\bI\b", value or ""))


def db_grades(value: str) -> frozenset[int]:
    text = clean_text(value)
    grades: set[int] = set()
    for a, b in re.findall(r"\b(9|10|11)\s*[-–—]\s*(9|10|11)\b", text):
        grades.update(range(int(a), int(b) + 1))
    grades.update(int(n) for n in re.findall(r"\b(9|10|11)\b", text))
    return frozenset(grades)


def db_rows_of(
    db_row: dict[str, Any],
    codes: set[str] | None,
    university: str,
    types: set[str] | None = None,
    units: dict[str, set[str]] | None = None,
) -> list[Row]:
    """Строки базы в виде для сравнения; codes и types сужают до того, что есть в документе.

    codes=None — эталон с кодом «*»: подходят любые направления. units — коды эталона по
    подразделениям: старая база у части вузов (МГУ) держит льготы по факультетам, без кодов."""
    btype = DB_TYPES.get(db_row["benefit_type"])
    if btype is None or not db_row["olympiad"] or (types is not None and btype not in types):
        return []
    program_codes = set(RE_CODE.findall(f"{db_row['code'] or ''} {db_row['direction'] or ''}"))
    if not program_codes and units:
        program_codes = units.get(squash(db_row["direction"] or ""), set())
    rows = []
    for code in sorted(program_codes if codes is None else program_codes & codes):
        rows.append(
            Row(
                key=(
                    squash(university),
                    code,
                    olympiad_key(db_row["olympiad"]),
                    profile_key(db_row["profile"] or ""),
                    btype,
                ),
                winner_role=db_role(db_row["winner_role"] or ""),
                levels=db_levels(db_row["level"] or ""),
                grades=db_grades(db_row["grade"] or ""),
                ege_min=db_row["min_ege_score"],
                ege_subjects=frozenset(db_row["confirm_subjects"] or ()),
                url=db_row["source_url"] or "",
            )
        )
    return rows


def pick_university(conn: Any, name: str) -> tuple[int, str] | None:
    """Вуз базы для названия из эталона: точное совпадение, иначе самый большой по числу направлений."""
    key = squash(RE_IMENI.sub("им.", name))
    rows = conn.execute(
        """SELECT u.id, u.name, u.short_name, count(p.id) FROM universities u
           LEFT JOIN programs p ON p.university_id = u.id GROUP BY u.id"""
    ).fetchall()
    names = [(r, squash(RE_IMENI.sub("им.", r[1])), squash(r[2] or "")) for r in rows]
    exact = [r for r, full, short in names if key in (full, short)]
    near = [r for r, full, _ in names if key and key in full]
    for group in (exact, near):
        if group:
            best = max(group, key=lambda r: r[3])
            return best[0], best[1]
    return None


def db_rows(conn: Any, gold: ExtractionFile) -> tuple[list[Row], str]:
    from psycopg.rows import dict_row

    found = pick_university(conn, gold.document.university)
    if found is None:
        return [], "вуза нет в базе"
    codes: set[str] | None = {r.program_code for r in gold.records}
    if ANY_CODE in (codes or ()):
        codes = None
    types: set[str] = {r.benefit_type for r in gold.records}
    units: dict[str, set[str]] = defaultdict(set)
    for r in gold.records:
        if r.division:
            units[squash(r.division)].add(r.program_code)
    with conn.cursor(row_factory=dict_row) as cur:
        raw = cur.execute(DB_SQL, (found[0],)).fetchall()
    rows = [
        row for r in raw for row in db_rows_of(r, codes, gold.document.university, types, units)
    ]
    return rows, f"база: {found[1]}"


# ---------------------------------------------------------------- прогон и вывод


def run(
    gold_files: dict[str, ExtractionFile],
    pred_files: dict[str, ExtractionFile] | None,
    *,
    conn: Any = None,
    checker: QuoteChecker | None = None,
) -> tuple[list[DocResult], DocResult]:
    results: list[DocResult] = []
    for name, gold in gold_files.items():
        if conn is not None:
            rows, note = db_rows(conn, gold)
            rows = in_scope(rows, gold.document.pages, gold.document.rows)
            results.append(evaluate_document(name, gold, rows, note=note, loose_profile=True))
            continue
        assert pred_files is not None
        pred = find_pred(name, gold, pred_files)
        if pred is None:
            results.append(evaluate_document(name, gold, [], checker=checker, note="нет файла"))
            continue
        rows = in_scope([row_of(r) for r in pred.records], gold.document.pages, gold.document.rows)
        results.append(evaluate_document(name, gold, rows, checker=checker))
    total = DocResult("ИТОГО", "")
    for r in results:
        total.add(r)
    return results, total


def _pct(value: float | None) -> str:
    return "—" if value is None else f"{value * 100:.0f}%"


def render_table(results: Sequence[DocResult], total: DocResult, *, quotes: bool) -> str:
    head = ["документ", "эталон", "извл.", "совп.", "точн.", "полн.", *FIELDS]
    if quotes:
        head += ["цитаты", "цит.эт."]
    head += ["пустые", "порог"]
    lines = [head]
    for r in [*results, total]:
        line = [
            r.name,
            str(r.gold),
            str(r.pred),
            str(r.matched),
            _pct(r.precision),
            _pct(r.recall),
            *(_pct(r.field_accuracy(f)) for f in FIELDS),
        ]
        if quotes:
            line += [_pct(r.quote_rate), _pct(r.gold_quote_rate)]
        line += [_pct(r.empty_rate), ("да" if r.passes else "нет") if r.name != "ИТОГО" else ""]
        lines.append(line)
    widths = [max(len(row[i]) for row in lines) for i in range(len(head))]
    out = []
    for n, row in enumerate(lines):
        out.append(
            "  ".join(
                c.ljust(widths[i]) if i == 0 else c.rjust(widths[i]) for i, c in enumerate(row)
            )
        )
        if n == 0:
            out.append("  ".join("-" * w for w in widths))
    notes = [f"{r.name}: {r.note}" for r in results if r.note]
    wrong = [f"{r.name}: неверное «кому» у {r.role_wrong}" for r in results if r.role_wrong]
    return "\n".join([*out, *([""] + notes if notes else []), *wrong])


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="olymp-eval-extract", description=__doc__.split("\n")[0])
    ap.add_argument("--gold", type=Path, default=Path("data/eval/extraction"))
    ap.add_argument("--pred", required=True, help='каталог с результатами или "db"')
    ap.add_argument("--json", type=Path, help="сохранить метрики в файл")
    ap.add_argument("--check-quotes", action="store_true", help="искать цитаты на страницах (сеть)")
    ap.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--insecure", action="store_true", help="не проверять TLS при скачивании")
    ap.add_argument("--db-url", help="по умолчанию OLYMP_DATABASE_URL")
    return ap.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        gold_files = load_dir(args.gold)
        missing = [n for n, f in gold_files.items() if not f.document.pages]
        if missing:
            raise ExtractionError(f"в эталоне нет document.pages: {', '.join(missing)}")
        pred_files = None if args.pred == "db" else load_dir(Path(args.pred))
    except ExtractionError as exc:
        print(exc, file=sys.stderr)
        return 2
    if not gold_files:
        print(f"В {args.gold} нет эталонных файлов.", file=sys.stderr)
        return 1

    conn = None
    store = None
    checker = None
    if args.pred == "db":
        import psycopg
        from olymp_db.session import psycopg_dsn

        conn = psycopg.connect(psycopg_dsn(args.db_url))
    elif args.check_quotes:
        store = DocumentStore(args.cache_dir, insecure=args.insecure)
        checker = QuoteChecker(store)
    try:
        results, total = run(gold_files, pred_files, conn=conn, checker=checker)
    finally:
        if conn is not None:
            conn.close()
        if store is not None:
            store.close()

    print(render_table(results, total, quotes=checker is not None))
    if checker is not None and checker.problems:
        print("\nЦитаты не проверены, документы недоступны:", file=sys.stderr)
        for url, why in checker.problems.items():
            print(f"  {url}: {why}", file=sys.stderr)
    if args.json:
        payload = {
            "pred": args.pred,
            "documents": [r.as_json() for r in results],
            "total": total.as_json(),
        }
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
