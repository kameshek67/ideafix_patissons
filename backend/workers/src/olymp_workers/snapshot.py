"""Снимок видимой выдачи: отсортированный TSV, по которому git diff показывает, что поменялось.

    olymp-snapshot            # выгрузить выдачу из базы в data/snapshot/benefits.tsv
    olymp-snapshot --check    # сверить базу с файлом; расхождение — код выхода 1

Строка снимка — льгота × олимпиада строки (если у льготы нет олимпиад — одна строка с пустой
олимпиадой) плюс стабильный ключ row_key. Слой raw в выдачу не попадает и в снимок тоже.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

import psycopg
from olymp_db.session import database_url, psycopg_dsn

from .ingest import DATA_DIR

SNAPSHOT_FILE = DATA_DIR / "snapshot" / "benefits.tsv"
COLUMNS = (
    "university",
    "program_code",
    "olympiad",
    "profile",
    "benefit_type",
    "role",
    "level",
    "grade",
    "ege_subjects",
    "ege_min",
    "layer",
    "row_key",
)
# поля снимка плюс то, что нужно открытому датасету (направление и источник)
VISIBLE_COLUMNS = COLUMNS + ("program_name", "source_title", "source_url")
SHOWN = 40

# профиль, уровень и роль у связанной олимпиады свои (они могут отличаться от строки льготы)
_SQL = """
SELECT u.name, p.code, COALESCE(o.canonical_name, ''),
       CASE WHEN bo.id IS NULL THEN b.olympiad_profile ELSE bo.profile END,
       b.benefit_type,
       CASE WHEN bo.id IS NULL THEN b.winner_role ELSE bo.winner_role END,
       CASE WHEN bo.id IS NULL THEN b.level ELSE bo.level END,
       b.grade,
       COALESCE(array_to_string(b.confirm_subjects, '+'), b.confirm_subject),
       COALESCE(b.min_ege_score::text, b.min_ege),
       b.layer, b.row_key,
       p.faculty_or_direction, b.source_title, b.source_url
FROM benefits b
JOIN programs p ON p.id = b.program_id
JOIN universities u ON u.id = p.university_id
LEFT JOIN benefit_olympiads bo ON bo.benefit_id = b.id
LEFT JOIN olympiads o ON o.id = bo.olympiad_id
WHERE b.layer <> 'raw'
"""


def _cell(value: object) -> str:
    return " ".join(str(value if value is not None else "").split())


def visible_rows(conn: psycopg.Connection) -> list[dict[str, str]]:
    """Видимые строки выдачи со всеми полями, в стабильном порядке."""
    rows = [
        {name: _cell(value) for name, value in zip(VISIBLE_COLUMNS, values, strict=True)}
        for values in conn.execute(_SQL).fetchall()
    ]
    rows.sort(key=lambda row: "\t".join(row[name] for name in COLUMNS))
    return rows


def build_snapshot(conn: psycopg.Connection) -> list[str]:
    """Строки снимка (без заголовка) в стабильном порядке."""
    return ["\t".join(row[name] for name in COLUMNS) for row in visible_rows(conn)]


def render(lines: list[str]) -> str:
    return "\t".join(COLUMNS) + "\n" + "".join(f"{line}\n" for line in lines)


def read_snapshot(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return text.split("\n")[1:-1] if text.endswith("\n") else text.split("\n")[1:]


def diff_lines(old: list[str], new: list[str]) -> tuple[list[str], list[str]]:
    """(добавлено, удалено) — с учётом повторов, в порядке файла."""
    added = Counter(new) - Counter(old)
    removed = Counter(old) - Counter(new)
    plus = sorted(added.elements())
    minus = sorted(removed.elements())
    return plus, minus


def summary(plus: list[str], minus: list[str]) -> str:
    out = [f"Снимок расходится с базой: +{len(plus)} добавлено, −{len(minus)} удалено"]
    for sign, rows in (("+", plus), ("−", minus)):
        if not rows:
            continue
        out.append(f"\nПервые {min(SHOWN, len(rows))} из {len(rows)} ({sign}):")
        out.extend(f"{sign} {line}" for line in rows[:SHOWN])
    out.append("\nЕсли правка осознанная — обнови файл: just snapshot")
    return "\n".join(out)


def main() -> int:
    parser = argparse.ArgumentParser(description="Снимок видимой выдачи в TSV")
    parser.add_argument(
        "--database-url", default=database_url(), help="по умолчанию OLYMP_DATABASE_URL"
    )
    parser.add_argument("--output", type=Path, default=SNAPSHOT_FILE, help="файл снимка")
    parser.add_argument("--check", action="store_true", help="сверить базу с файлом, не писать")
    args = parser.parse_args()

    with psycopg.connect(psycopg_dsn(args.database_url)) as conn:
        conn.read_only = True
        lines = build_snapshot(conn)
    if not lines:
        print("В выдаче нет строк: база пустая или не собрана (olymp-ingest)", file=sys.stderr)
        return 1

    if args.check:
        if not args.output.exists():
            print(f"Нет файла снимка {args.output}: just snapshot", file=sys.stderr)
            return 1
        plus, minus = diff_lines(read_snapshot(args.output), lines)
        if plus or minus:
            print(summary(plus, minus))
            return 1
        print(f"Снимок совпадает с базой: {len(lines)} строк")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(render(lines), encoding="utf-8", newline="\n")
    print(f"Записано {len(lines)} строк в {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
