"""Сообщения «Нашли ошибку в данных» в CSV для команды.

    uv run python scripts/export_reports.py > reports.csv            # новые
    uv run python scripts/export_reports.py --all > reports.csv      # все
    uv run python scripts/export_reports.py --mark-seen              # новые → seen после выгрузки

На стенде (scripts/ в образ не входит — скрипт идёт через stdin):
    ideafix exec -T api python - --all < scripts/export_reports.py > reports.csv
"""

import argparse
import csv
import json
import sys
from typing import TextIO

import psycopg
from olymp_db.session import database_url, psycopg_dsn

COLUMNS = [
    "id",
    "created_at",
    "kind",
    "university",
    "program",
    "code",
    "olympiad",
    "message",
    "status",
    "source",
    "reason",
    "row_key",
    "link",
    "quote",
]


# Excel и LibreOffice считают формулой любую ячейку, начинающуюся с этих знаков
FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def safe_cell(value: object) -> object:
    """Текст, который начинается как формула, получает впереди апостроф: в таблице он виден как текст."""
    if isinstance(value, str) and value.startswith(FORMULA_PREFIXES):
        return "'" + value
    return value


def export(conn: psycopg.Connection, out: TextIO, *, include_all: bool, mark_seen: bool) -> int:
    """Пишет CSV в out, возвращает число выгруженных сообщений."""
    where = "" if include_all else "WHERE status = 'new'"
    rows = conn.execute(
        f"SELECT id, created_at, kind, context, message, status, source, reason, row_key, link, quote "
        f"FROM data_reports {where} ORDER BY id"  # noqa: S608
    ).fetchall()
    writer = csv.writer(out)
    writer.writerow(COLUMNS)
    for report_id, created_at, kind, context, message, status, *extra in rows:
        context = context if isinstance(context, dict) else json.loads(context)
        cells = [
            report_id,
            created_at.isoformat(timespec="minutes"),
            kind,
            context.get("university", ""),
            context.get("program", ""),
            context.get("code", ""),
            context.get("olympiad", ""),
            message,
            status,
            *extra,
        ]
        writer.writerow([safe_cell(cell) for cell in cells])
    if mark_seen and rows:
        # только выгруженные id: сообщения, пришедшие во время выгрузки, остаются новыми
        conn.execute(
            "UPDATE data_reports SET status = 'seen' WHERE status = 'new' AND id = ANY(%s)",
            ([row[0] for row in rows],),
        )
        conn.commit()
    return len(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--all", action="store_true", help="все сообщения, а не только новые")
    parser.add_argument(
        "--mark-seen", action="store_true", help="отметить выгруженные новые как seen"
    )
    args = parser.parse_args()
    with psycopg.connect(psycopg_dsn(database_url())) as conn:
        count = export(conn, sys.stdout, include_all=args.all, mark_seen=args.mark_seen)
    print(f"сообщений: {count}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
