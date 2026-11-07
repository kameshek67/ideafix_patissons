"""Задачи проекта: docs/tasks/T-NNN-*.md с YAML-шапкой.

    uv run python scripts/tasks.py board             # доска по статусам (just tasks)
    uv run python scripts/tasks.py next              # свободные задачи, у которых готовы зависимости
    uv run python scripts/tasks.py check             # проверка шапок и зависимостей (CI)
    uv run python scripts/tasks.py claim T-012 --owner nick [--branch feat/T-012-…]
    uv run python scripts/tasks.py status T-012 review [--pr 41]

Шапка — простой YAML: «ключ: значение» и списки в квадратных скобках. Своего парсера
хватает, чтобы скрипт работал без зависимостей (и без uv-окружения: python3 scripts/tasks.py).
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = ROOT / "docs" / "tasks"

STATUSES = ["todo", "in-progress", "review", "blocked", "done", "dropped"]
PRIORITIES = ["P0", "P1", "P2", "P3"]
AREAS = ["api", "web", "workers", "domain", "db", "infra", "docs", "data", "design", "product"]
ESTIMATES = ["S", "M", "L"]
REQUIRED = ["id", "title", "status", "priority", "area", "estimate"]
KEY_ORDER = [
    "id",
    "title",
    "status",
    "priority",
    "area",
    "estimate",
    "spec",
    "depends",
    "owner",
    "branch",
    "pr",
    "updated",
]
ID_RE = re.compile(r"^T-\d{3}$")
FILE_RE = re.compile(r"^(T-\d{3})-[a-z0-9-]+\.md$")


@dataclass
class Task:
    path: Path
    meta: dict[str, str | list[str]]
    body: str
    errors: list[str] = field(default_factory=list)

    def get(self, key: str) -> str:
        value = self.meta.get(key, "")
        return value if isinstance(value, str) else ", ".join(value)

    def deps(self) -> list[str]:
        value = self.meta.get("depends", [])
        return value if isinstance(value, list) else [v for v in [value] if v]


def parse_value(raw: str) -> str | list[str]:
    raw = raw.strip()
    if raw.startswith("[") and raw.endswith("]"):
        return [item.strip().strip("\"'") for item in raw[1:-1].split(",") if item.strip()]
    if len(raw) >= 2 and raw[0] == raw[-1] and raw[0] in "\"'":
        return raw[1:-1]
    return raw


def load(path: Path) -> Task:
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---\n"):
        return Task(path, {}, text, [f"{path.name}: нет YAML-шапки (--- в начале файла)"])
    end = text.find("\n---\n", 4)
    if end < 0:
        return Task(path, {}, text, [f"{path.name}: шапка не закрыта строкой ---"])
    meta: dict[str, str | list[str]] = {}
    for line in text[4:end].splitlines():
        line = line.split(" #", 1)[0].rstrip()
        if not line.strip():
            continue
        if ":" not in line:
            return Task(path, meta, text, [f"{path.name}: строка шапки без «:» — {line!r}"])
        key, raw = line.split(":", 1)
        meta[key.strip()] = parse_value(raw)
    return Task(path, meta, text[end + 5 :])


def dump(task: Task) -> None:
    keys = [k for k in KEY_ORDER if k in task.meta] + [k for k in task.meta if k not in KEY_ORDER]
    lines = ["---"]
    for key in keys:
        value = task.meta[key]
        if isinstance(value, list):
            lines.append(f"{key}: [{', '.join(value)}]")
        else:
            needs_quotes = not value or value[0] in "[{\"'" or ": " in value or " #" in value
            lines.append(f'{key}: "{value}"' if needs_quotes else f"{key}: {value}")
    lines.append("---")
    task.path.write_text("\n".join(lines) + "\n" + task.body, encoding="utf-8", newline="\n")


def load_all() -> list[Task]:
    return [load(p) for p in sorted(TASKS_DIR.glob("T-*.md"))]


def validate(tasks: list[Task]) -> list[str]:
    errors: list[str] = []
    ids: dict[str, Path] = {}
    for t in tasks:
        errors += t.errors
        if t.errors:
            continue
        name = t.path.name
        for key in REQUIRED:
            if not t.get(key):
                errors.append(f"{name}: не заполнено поле {key}")
        tid = t.get("id")
        match = FILE_RE.match(name)
        if not ID_RE.match(tid):
            errors.append(f"{name}: id должен быть вида T-012, а не {tid!r}")
        elif not match or match.group(1) != tid:
            errors.append(f"{name}: имя файла должно начинаться с id ({tid}-коротко.md)")
        if tid in ids:
            errors.append(f"{name}: id {tid} уже занят файлом {ids[tid].name}")
        ids[tid] = t.path
        checks = [
            ("status", STATUSES),
            ("priority", PRIORITIES),
            ("area", AREAS),
            ("estimate", ESTIMATES),
        ]
        for key, allowed in checks:
            if t.get(key) not in allowed:
                errors.append(f"{name}: {key}={t.get(key)!r}, допустимо: {', '.join(allowed)}")
        if t.get("status") in ("in-progress", "review"):
            for key in ("owner", "branch"):
                if not t.get(key):
                    errors.append(f"{name}: статус {t.get('status')} требует поле {key}")
        spec = t.get("spec")
        if spec and not (ROOT / spec).exists():
            errors.append(f"{name}: нет файла ТЗ {spec}")
    for t in tasks:
        for dep in t.deps():
            if dep not in ids:
                errors.append(f"{t.path.name}: зависимость {dep} не найдена")
    return errors


def by_id(tasks: list[Task]) -> dict[str, Task]:
    return {t.get("id"): t for t in tasks}


def ready(task: Task, index: dict[str, Task]) -> bool:
    return all(index[d].get("status") in ("done", "dropped") for d in task.deps() if d in index)


def sort_key(t: Task) -> tuple[int, str]:
    return (
        PRIORITIES.index(t.get("priority")) if t.get("priority") in PRIORITIES else 9,
        t.get("id"),
    )


def row(t: Task, extra: str = "") -> str:
    who = t.get("owner")
    return (
        f"  {t.get('id')}  {t.get('priority')}  {t.get('area'):<8} {t.get('title')}"
        + (f"  [{who}]" if who else "")
        + extra
    )


def open_prs() -> dict[str, str]:
    """Открытые PR с ID задачи в заголовке (если есть gh) — это «замки» на задачи."""
    try:
        out = subprocess.run(
            [
                "gh",
                "pr",
                "list",
                "--state",
                "open",
                "--json",
                "number,title,author,isDraft",
                "--jq",
                '.[] | "\\(.number)\\t\\(.title)\\t\\(.author.login)"',
            ],
            capture_output=True,
            text=True,
            timeout=15,
            cwd=ROOT,
            encoding="utf-8",
        )
    except (OSError, subprocess.TimeoutExpired):
        return {}
    if out.returncode != 0:
        return {}
    locks: dict[str, str] = {}
    for line in out.stdout.splitlines():
        number, title, author = (line.split("\t") + ["", ""])[:3]
        for tid in re.findall(r"T-\d{3}", title):
            locks[tid] = f"PR #{number} ({author})"
    return locks


def cmd_board(_: argparse.Namespace) -> int:
    tasks = load_all()
    locks = open_prs()
    titles = {
        "in-progress": "В работе",
        "review": "На ревью",
        "blocked": "Заблокировано",
        "todo": "К работе",
        "done": "Сделано",
    }
    for status, title in titles.items():
        group = sorted((t for t in tasks if t.get("status") == status), key=sort_key)
        if not group:
            continue
        print(f"\n{title} ({len(group)})")
        for t in group:
            lock = f"  ← {locks[t.get('id')]}" if t.get("id") in locks and status == "todo" else ""
            print(row(t, lock))
    if not locks:
        print("\n(открытые PR не проверены: нет gh или нет авторизации — смотрите PR на GitHub)")
    return 0


def cmd_next(_: argparse.Namespace) -> int:
    tasks = load_all()
    index = by_id(tasks)
    locks = open_prs()
    free = sorted(
        (
            t
            for t in tasks
            if t.get("status") == "todo" and ready(t, index) and t.get("id") not in locks
        ),
        key=sort_key,
    )
    if not free:
        print("Свободных задач с готовыми зависимостями нет.")
        return 0
    print("Можно брать (зависимости готовы, открытых PR нет):")
    for t in free:
        print(row(t, f"  ({t.get('estimate')}) {t.path.relative_to(ROOT).as_posix()}"))
    return 0


def cmd_check(_: argparse.Namespace) -> int:
    errors = validate(load_all())
    for e in errors:
        print(f"ОШИБКА: {e}", file=sys.stderr)
    if not errors:
        print(f"Задачи в порядке: {len(load_all())} файлов.")
    return 1 if errors else 0


def find(tid: str) -> Task:
    for t in load_all():
        if t.get("id") == tid:
            return t
    sys.exit(f"Задача {tid} не найдена в docs/tasks")


def current_branch() -> str:
    out = subprocess.run(
        ["git", "branch", "--show-current"], capture_output=True, text=True, cwd=ROOT
    )
    return out.stdout.strip()


def cmd_claim(args: argparse.Namespace) -> int:
    t = find(args.id)
    if t.get("status") not in ("todo", "blocked") and not args.force:
        sys.exit(
            f"{args.id} в статусе {t.get('status')} (владелец {t.get('owner')}). --force, если точно ваша."
        )
    index = by_id(load_all())
    not_ready = [d for d in t.deps() if d in index and index[d].get("status") != "done"]
    if not_ready:
        print(
            f"Внимание: не готовы зависимости {', '.join(not_ready)} — договоритесь с их владельцами."
        )
    branch = args.branch or current_branch()
    if branch in ("main", "dev", ""):
        sys.exit(
            "Сначала создайте ветку от dev: git switch -c feat/T-012-коротко (или передайте --branch)"
        )
    t.meta.update(
        status="in-progress",
        owner=args.owner,
        branch=branch,
        updated=date.today().isoformat(),
    )
    dump(t)
    print(f"{args.id} взята: {args.owner}, ветка {branch}.")
    print(f"Дальше: git commit -am 'chore(tasks): взять {args.id}' && git push -u origin {branch}")
    print(
        f"        и сразу draft PR в dev: gh pr create --draft --base dev --title '{args.id}: {t.get('title')}'"
    )
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    if args.status not in STATUSES:
        sys.exit(f"Статус {args.status!r} не из {', '.join(STATUSES)}")
    t = find(args.id)
    t.meta["status"] = args.status
    if args.pr:
        t.meta["pr"] = args.pr
    t.meta["updated"] = date.today().isoformat()
    dump(t)
    print(f"{args.id}: {args.status}")
    return 0


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("board", help="доска по статусам").set_defaults(fn=cmd_board)
    sub.add_parser("next", help="что можно брать").set_defaults(fn=cmd_next)
    sub.add_parser("check", help="проверка файлов задач").set_defaults(fn=cmd_check)
    claim = sub.add_parser("claim", help="взять задачу")
    claim.add_argument("id")
    claim.add_argument("--owner", required=True, help="ник на GitHub")
    claim.add_argument("--branch")
    claim.add_argument("--force", action="store_true")
    claim.set_defaults(fn=cmd_claim)
    status = sub.add_parser("status", help="сменить статус")
    status.add_argument("id")
    status.add_argument("status")
    status.add_argument("--pr")
    status.set_defaults(fn=cmd_status)
    args = parser.parse_args()
    return int(args.fn(args))


if __name__ == "__main__":
    raise SystemExit(main())
