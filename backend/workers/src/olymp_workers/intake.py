"""Загрузка olympiad_intake.csv: сколько олимпиадников принимают вузы базы.

Файл строится из сводной панели «Мониторинг эффективности вузов» (monitoring.py) и лежит в
репозитории. Вызывается из olymp-ingest в той же транзакции, что и остальная сборка: вуз, которого
нет в базе, останавливает сборку, а не теряется молча.
"""

import csv
from pathlib import Path
from typing import Any

import psycopg

INTAKE_CSV = "monitoring/olympiad_intake.csv"


class IntakeDataError(ValueError):
    """Файл содержит строку, которую нельзя загрузить."""


def _int_or_none(value: str) -> int | None:
    return int(value) if value.strip() else None


def _float_or_none(value: str) -> float | None:
    return float(value) if value.strip() else None


def load_intake(conn: psycopg.Connection[Any], data_dir: Path) -> dict[str, int]:
    """Заполняет university_intake. Нет файла — ничего не грузим (панель необязательна)."""
    path = data_dir / INTAKE_CSV
    if not path.exists():
        return {"rows": 0, "universities": 0}
    universities = {
        name: uid for uid, name in conn.execute("SELECT id, name FROM universities").fetchall()
    }
    with path.open(encoding="utf-8", newline="") as fh:
        rows = list(csv.DictReader(fh))
    seen: set[tuple[str, str]] = set()
    for i, row in enumerate(rows, 2):
        where = f"{INTAKE_CSV}:{i}"
        key = (row["university"], row["year"])
        if key in seen:
            raise IntakeDataError(f"{where}: повтор «{row['university']}», {row['year']}")
        seen.add(key)
        if row["university"] not in universities:
            msg = (
                f"{where}: вуза «{row['university']}» нет в базе (название должно совпадать с XLSX)"
            )
            raise IntakeDataError(msg)
        conn.execute(
            """INSERT INTO university_intake
                 (university_id, year, olympiad_students, olympiad_share, avg_score_budget)
               VALUES (%s, %s, %s, %s, %s)""",
            (
                universities[row["university"]],
                int(row["year"]),
                _int_or_none(row["olympiad_students"]),
                _float_or_none(row["olympiad_share"]),
                _float_or_none(row["avg_score_budget"]),
            ),
        )
    return {"rows": len(rows), "universities": len({r["university"] for r in rows})}
