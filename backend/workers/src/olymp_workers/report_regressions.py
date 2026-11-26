"""Подтверждённые жалобы как регрессии: выгрузка в файл сценариев и проверка по базе.

    olymp-report-regressions export   — жалобы со статусом «исправлено» в data/regressions/reports.json
    olymp-report-regressions check    — каждая исправленная строка не должна вернуться в выдачу

Формат файла:

    {"version": 1, "scenarios": [
      {"report_id": 12, "row_key": "9f2c…", "reason": "winners_only", "expect": "absent",
       "fixed_at": "2026-11-26T10:00:00+00:00", "context": {"university": "…", "olympiad": "…"}}
    ]}

Ключ строки считается от смысловых полей (вуз, направление, тип, олимпиада, профиль, уровень,
кому, класс, ЕГЭ, источник), поэтому исправленная строка получает другой ключ, а старая должна
исчезнуть из базы (expect = absent). Если правка не меняет ключ (например, только примечание),
в файле вручную ставят expect = present и добавляют поле note. Сценарий живёт в репозитории
после пересборок базы: жалоба не вернётся, пока кто-то не сломает разбор заново.
"""

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import psycopg
from olymp_db.session import database_url, psycopg_dsn

DEFAULT_PATH = Path(__file__).resolve().parents[4] / "data" / "regressions" / "reports.json"
VERSION = 1


def fixed_scenarios(conn: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT id, row_key, reason, resolved_at, context FROM data_reports
           WHERE kind = 'benefit' AND status = 'fixed' AND row_key <> '' ORDER BY id"""
    ).fetchall()
    return [
        {
            "report_id": report_id,
            "row_key": row_key,
            "reason": reason,
            "expect": "absent",
            "fixed_at": resolved_at.isoformat(timespec="seconds") if resolved_at else None,
            "context": context,
        }
        for report_id, row_key, reason, resolved_at, context in rows
    ]


def merge(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Новые сценарии добавляются, ручные правки (expect, note) уже записанных сохраняются."""
    known = {s["report_id"]: s for s in old}
    for scenario in new:
        known.setdefault(scenario["report_id"], scenario)
    return [known[key] for key in sorted(known)]


def load(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("version") != VERSION:
        raise ValueError(f"{path}: неизвестная версия файла сценариев")
    return list(data["scenarios"])


def save(path: Path, scenarios: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps({"version": VERSION, "scenarios": scenarios}, ensure_ascii=False, indent=2)
    path.write_text(text + "\n", encoding="utf-8")


def export(conn: psycopg.Connection[Any], path: Path = DEFAULT_PATH) -> int:
    """Дописывает исправленные жалобы в файл; возвращает число сценариев в файле."""
    scenarios = merge(load(path), fixed_scenarios(conn))
    save(path, scenarios)
    return len(scenarios)


def check(conn: psycopg.Connection[Any], scenarios: list[dict[str, Any]]) -> list[str]:
    """Что из сценариев нарушено в собранной базе: пустой список — всё в порядке."""
    problems = []
    for scenario in scenarios:
        exists = conn.execute(
            "SELECT EXISTS (SELECT 1 FROM benefits WHERE row_key = %s AND layer <> 'raw')",
            (scenario["row_key"],),
        ).fetchone()
        present = bool(exists and exists[0])
        expect = scenario.get("expect", "absent")
        if expect not in {"absent", "present"}:
            problems.append(f"№{scenario['report_id']}: неизвестное ожидание «{expect}»")
        elif present != (expect == "present"):
            where = (scenario.get("context") or {}).get("university", "")
            state = "снова в выдаче" if present else "пропала из выдачи"
            problems.append(
                f"№{scenario['report_id']} ({where}): строка {scenario['row_key']} {state}"
            )
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("command", choices=["export", "check"])
    parser.add_argument("--file", type=Path, default=DEFAULT_PATH)
    args = parser.parse_args(argv)
    with psycopg.connect(psycopg_dsn(database_url())) as conn:
        if args.command == "export":
            print(f"сценариев в {args.file}: {export(conn, args.file)}")
            return 0
        problems = check(conn, load(args.file))
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
