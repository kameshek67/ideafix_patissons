"""Открытый датасет видимых льгот «Олимпа».

    just dataset                 # data/release/olymp-benefits.jsonl.gz и meta.json
    olymp-export-dataset --output путь/к/файлу.jsonl.gz --campaign 2026

Одна строка JSON — строка видимой выдачи (льгота × олимпиада): поля снимка плюс
название направления, источник и год кампании. Файл сжимается gzip, рядом пишется
meta.json с датой сборки, числом строк, версией формата и лицензией.
"""

from __future__ import annotations

import argparse
import gzip
import json
import sys
from datetime import date
from pathlib import Path

import psycopg
from olymp_db.session import database_url, psycopg_dsn
from olymp_domain.diplomas import CAMPAIGN_YEAR

from .ingest import DATA_DIR
from .snapshot import visible_rows

DATASET_FILE = DATA_DIR / "release" / "olymp-benefits.jsonl.gz"
FORMAT_VERSION = "1.0"
LICENSE = "CC BY 4.0"
SOURCE = "База «Олимпа», собранная из data/Olimpiady_BVI_100ballov.xlsx"
NOTICE = "Данные справочные: условия приёма сверяйте с официальными документами вузов."
FIELDS = (
    "row_key",
    "university",
    "program_code",
    "program_name",
    "benefit_type",
    "olympiad",
    "profile",
    "level",
    "role",
    "grade",
    "ege_subjects",
    "ege_min",
    "layer",
    "source_title",
    "source_url",
    "campaign",
)


def build_rows(conn: psycopg.Connection, campaign: int = CAMPAIGN_YEAR) -> list[dict[str, object]]:
    """Строки датасета в порядке снимка."""
    return [{field: row.get(field, campaign) for field in FIELDS} for row in visible_rows(conn)]


def render(rows: list[dict[str, object]]) -> bytes:
    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True) for row in rows]
    return gzip.compress("".join(f"{line}\n" for line in lines).encode("utf-8"), mtime=0)


def make_meta(rows: int, built_at: str) -> dict[str, object]:
    return {
        "built_at": built_at,
        "rows": rows,
        "format_version": FORMAT_VERSION,
        "license": LICENSE,
        "source": SOURCE,
        "notice": NOTICE,
    }


def export_dataset(
    conn: psycopg.Connection,
    output: Path,
    *,
    campaign: int = CAMPAIGN_YEAR,
    built_at: str | None = None,
) -> int:
    """Пишет JSONL.gz и meta.json рядом с ним, возвращает число строк."""
    rows = build_rows(conn, campaign)
    if not rows:
        return 0
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(render(rows))
    meta = make_meta(len(rows), built_at or date.today().isoformat())
    text = json.dumps(meta, ensure_ascii=False, indent=2) + "\n"
    output.with_name("meta.json").write_text(text, encoding="utf-8")
    return len(rows)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--database-url", default=database_url(), help="по умолчанию OLYMP_DATABASE_URL"
    )
    parser.add_argument("--output", type=Path, default=DATASET_FILE, help="файл .jsonl.gz")
    parser.add_argument("--campaign", type=int, default=CAMPAIGN_YEAR, help="год приёмной кампании")
    args = parser.parse_args(argv)

    with psycopg.connect(psycopg_dsn(args.database_url)) as conn:
        conn.read_only = True
        count = export_dataset(conn, args.output, campaign=args.campaign)
    if not count:
        print("В выдаче нет строк: база пустая или не собрана (olymp-ingest)", file=sys.stderr)
        return 1
    print(f"Записано {count} строк в {args.output}, meta.json — рядом")
    return 0


if __name__ == "__main__":
    sys.exit(main())
