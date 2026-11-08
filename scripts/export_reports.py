"""Сообщения «Нашли ошибку в данных» (T-079) в CSV для команды.

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
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--all", action="store_true", help="все сообщения, а не только новые")
    parser.add_argument(
        "--mark-seen", action="store_true", help="отметить выгруженные новые как seen"
    )
    args = parser.parse_args()
    where = "" if args.all else "WHERE status = 'new'"
    with psycopg.connect(psycopg_dsn(database_url())) as conn:
        rows = conn.execute(
            f"SELECT id, created_at, kind, context, message, status FROM data_reports {where} ORDER BY id"  # noqa: S608
        ).fetchall()
        writer = csv.writer(sys.stdout)
        writer.writerow(COLUMNS)
        for report_id, created_at, kind, context, message, status in rows:
            context = context if isinstance(context, dict) else json.loads(context)
            writer.writerow(
                [
                    report_id,
                    created_at.isoformat(timespec="minutes"),
                    kind,
                    context.get("university", ""),
                    context.get("program", ""),
                    context.get("code", ""),
                    context.get("olympiad", ""),
                    message,
                    status,
                ]
            )
        if args.mark_seen and rows:
            conn.execute("UPDATE data_reports SET status = 'seen' WHERE status = 'new'")
            conn.commit()
    print(f"сообщений: {len(rows)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
