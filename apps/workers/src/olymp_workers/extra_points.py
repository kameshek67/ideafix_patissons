"""Загрузка баллов за индивидуальные достижения (ИД) из data/individual_achievements*.csv.

Вызывается из olymp-ingest в той же транзакции, что и остальная сборка. CSV лежит в
репозитории и проходит ревью, поэтому ошибка в нём (неизвестный вуз, строка без
источника) останавливает сборку, а не молча теряет данные.
"""

import csv
import hashlib
import os
import sys
from pathlib import Path
from typing import Any

import psycopg
from olymp_db.session import psycopg_dsn
from olymp_domain.extra_points import KINDS

from .tables import clear_tables

ACHIEVEMENTS_CSV = "individual_achievements.csv"
LIMITS_CSV = "individual_achievement_limits.csv"


class ExtraPointsDataError(ValueError):
    """Файл ИД содержит строку, которую нельзя загрузить."""


def _split(value: str) -> list[str]:
    return [x for x in value.split("|") if x]


def _int_or_none(value: str) -> int | None:
    return int(value) if value.strip() else None


def _read(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _university_id(universities: dict[str, int], name: str, where: str) -> int:
    try:
        return universities[name]
    except KeyError:
        msg = f"{where}: вуза «{name}» нет в базе (название должно совпадать с XLSX)"
        raise ExtraPointsDataError(msg) from None


def _check_source(row: dict[str, str], where: str) -> None:
    if not (row["source_url"] and row["source_page"] and row["source_quote"]):
        msg = f"{where}: у строки нет источника (адрес, страница и цитата обязательны)"
        raise ExtraPointsDataError(msg)


def load_extra_points(conn: psycopg.Connection[Any], data_dir: Path) -> dict[str, int]:
    """Заполняет individual_achievements и individual_achievement_limits."""
    universities = {
        name: uid for uid, name in conn.execute("SELECT id, name FROM universities").fetchall()
    }
    rules = _read(data_dir / ACHIEVEMENTS_CSV)
    seen: set[str] = set()
    for i, row in enumerate(rules, 2):
        where = f"{ACHIEVEMENTS_CSV}:{i}"
        _check_source(row, where)
        if row["kind"] not in KINDS:
            raise ExtraPointsDataError(f"{where}: неизвестный вид «{row['kind']}»")
        if row["rule_id"] in seen:
            raise ExtraPointsDataError(f"{where}: повтор rule_id «{row['rule_id']}»")
        seen.add(row["rule_id"])
        conn.execute(
            """INSERT INTO individual_achievements
                 (rule_key, university_id, admission_year, kind, variants, points, years,
                  recency_years, exclusive_group, label, notes, source_url, source_page,
                  source_quote, review)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
            (
                row["rule_id"],
                _university_id(universities, row["university"], where),
                int(row["admission_year"]),
                row["kind"],
                _split(row["variants"]),
                int(row["points"]),
                [int(y) for y in _split(row["years"])],
                _int_or_none(row["recency_years"]),
                row["exclusive_group"],
                row["label"],
                row["notes"],
                row["source_url"],
                int(row["source_page"]),
                row["source_quote"],
                row["review"],
            ),
        )
    limits = _read(data_dir / LIMITS_CSV)
    for i, row in enumerate(limits, 2):
        where = f"{LIMITS_CSV}:{i}"
        _check_source(row, where)
        conn.execute(
            """INSERT INTO individual_achievement_limits
                 (university_id, admission_year, max_total, source_url, source_page,
                  source_quote, review)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (
                _university_id(universities, row["university"], where),
                int(row["admission_year"]),
                int(row["max_total"]),
                row["source_url"],
                int(row["source_page"]),
                row["source_quote"],
                row["review"],
            ),
        )
    # версия данных входит в ключи кэша API: после перезагрузки CSV старые ответы не отдаются
    digest = hashlib.sha256(
        (data_dir / ACHIEVEMENTS_CSV).read_bytes() + (data_dir / LIMITS_CSV).read_bytes()
    ).hexdigest()[:16]
    conn.execute(
        """INSERT INTO meta (key, value) VALUES ('extra_points_version', %s)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""",
        (digest,),
    )
    return {"rules": len(rules), "limits": len(limits)}


def reload_extra_points(database_url: str | None, data_dir: Path) -> dict[str, int]:
    """Заменяет баллы за ИД данными из CSV, не пересобирая остальную базу.

    Вызывается при каждом выкате (сервис migrate): olymp-ingest --if-empty на готовой базе
    ничего не делает, и без этого новые строки CSV не попали бы на стенд. Одна транзакция:
    API до коммита видит прежние данные, а при ошибке в CSV прежние данные остаются.
    """
    with psycopg.connect(psycopg_dsn(database_url)) as conn:
        clear_tables(conn, ["individual_achievements", "individual_achievement_limits"])
        stats = load_extra_points(conn, data_dir)
        conn.commit()
    return stats


def main() -> int:
    repo = Path(__file__).resolve().parents[4]
    data_dir = Path(os.environ.get("OLYMP_DATA_DIR", repo / "data"))
    try:
        stats = reload_extra_points(os.environ.get("OLYMP_DATABASE_URL"), data_dir)
    except ExtraPointsDataError as exc:
        print(f"Баллы за ИД не загружены: {exc}", file=sys.stderr)  # noqa: T201
        return 1
    print(f"Баллы за ИД: правил {stats['rules']}, лимитов {stats['limits']}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
