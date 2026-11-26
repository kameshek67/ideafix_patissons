"""
Перечень олимпиад РСОШ на 2026/27 учебный год.

    olymp-rsosh             # скачать https://rsr-olymp.ru/ и обновить data/rsosh_2026_27.json
    olymp-rsosh --dry-run   # только показать, что разобралось
    olymp-rsosh --html f.html  # разобрать сохранённую страницу (без сети)

Файл лежит в репозитории: сборка базы (olymp-ingest) сеть не использует, а скрипт нужен раз в
сезон. Таблица на сайте с rowspan: номер и название олимпиады стоят в первой строке блока
и действуют на все строки профилей до следующего блока.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request as request
from collections.abc import Callable
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import psycopg
from olymp_domain.textutils import clean_profile, clean_text, norm_level, squash

from .tls import is_tls_error, web_context

DATA_DIR = Path(os.environ.get("OLYMP_DATA_DIR", Path(__file__).resolve().parents[4] / "data"))
RSOSH_FILE = "rsosh_2026_27.json"
SOURCE_URL = "https://rsr-olymp.ru/"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122 Safari/537.36"
)
# в перечне около 270 строк; меньше — значит, вёрстка сайта изменилась и разбор надо проверить
MIN_ROWS = 100


# международные по справочнику (лист «ВШЭ международные»), но входившие и в перечень РСОШ:
# для них признак «в перечне» применим. Настоящие международные (IMO, IOI…) перечнем не
# определяются: у них признак пустой, и сайт ничего не говорит.
LISTED_INTERNATIONAL = (
    "формулаединства",
    "научныхработшкольниковюниор",
    "менделеевскаяолимпиада",
    "санктпетербургскаяастрономическая",
)


class RsoshError(Exception):
    """Страница не похожа на перечень или файл перечня повреждён."""


class _TableParser(HTMLParser):
    """Собирает строки таблицы `mainTableInfo`: [(текст ячейки, rowspan), …]."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.rows: list[list[tuple[str, int]]] = []
        self._in_table = False
        self._depth = 0
        self._row: list[tuple[str, int]] | None = None
        self._cell: list[str] | None = None
        self._span = 1

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "table":
            if self._in_table:
                self._depth += 1
            elif "mainTableInfo" in (attributes.get("class") or "").split():
                self._in_table = True
                self._depth = 1
        elif not self._in_table:
            return
        elif tag == "tr":
            self._row = []
        elif tag == "td" and self._row is not None:
            self._cell = []
            try:
                self._span = max(1, int(attributes.get("rowspan") or 1))
            except ValueError:
                self._span = 1

    def handle_endtag(self, tag: str) -> None:
        if not self._in_table:
            return
        if tag == "td" and self._cell is not None and self._row is not None:
            self._row.append((clean_text(" ".join(self._cell)), self._span))
            self._cell = None
        elif tag == "tr" and self._row is not None:
            if self._row:
                self.rows.append(self._row)
            self._row = None
        elif tag == "table":
            self._depth -= 1
            if self._depth == 0:
                self._in_table = False

    def handle_data(self, data: str) -> None:
        if self._cell is not None:
            self._cell.append(data)


def parse_table(html: str) -> list[dict[str, Any]]:
    """-> [{number, olympiad, profile, subjects, level}]; level — 'I'/'II'/'III'."""
    parser = _TableParser()
    parser.feed(html)
    # ячейки, растянутые на несколько строк: колонка -> (осталось строк, текст)
    carried: dict[int, list[Any]] = {}
    rows: list[dict[str, Any]] = []
    for cells in parser.rows:
        if cells[0][0].startswith("№"):
            continue  # заголовок
        values: list[str] = []
        queue = iter(cells)
        for column in range(5):
            if column in carried and carried[column][0] > 0:
                carried[column][0] -= 1
                values.append(carried[column][1])
                continue
            item = next(queue, None)
            if item is None:
                raise RsoshError(f"в строке перечня не хватает ячеек: {cells}")
            text, span = item
            values.append(text)
            if span > 1:
                carried[column] = [span - 1, text]
        if next(queue, None) is not None:
            raise RsoshError(f"в строке перечня лишние ячейки: {cells}")
        number, olympiad, profile, subjects, level = values
        if not number.isdigit() or not olympiad:
            raise RsoshError(f"строка перечня не разобрана: {values}")
        rows.append(
            {
                "number": int(number),
                "olympiad": olympiad,
                "profile": profile,
                "subjects": subjects,
                "level": norm_level(level),
            }
        )
    bad = [r for r in rows if not r["level"]]
    if bad:
        raise RsoshError(f"не распознан уровень: {bad[0]}")
    return rows


def fetch(url: str = SOURCE_URL, timeout: int = 30, insecure: bool = False) -> str:
    req = request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*"})
    try:
        with request.urlopen(req, timeout=timeout, context=web_context(insecure)) as resp:
            html: str = resp.read(5_000_000).decode("utf-8", "ignore")
            return html
    except Exception as exc:
        if is_tls_error(exc):
            raise RsoshError(
                "сертификат сайта не проходит проверку (см. infra/certs; крайний случай — --insecure)"
            ) from exc
        raise


def build(html: str, source_url: str = SOURCE_URL) -> dict[str, Any]:
    rows = parse_table(html)
    if len(rows) < MIN_ROWS:
        raise RsoshError(f"в таблице {len(rows)} строк, ожидалось не меньше {MIN_ROWS}")
    return {
        "source_url": source_url,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "rows": rows,
    }


def load(path: Path | None = None) -> list[dict[str, Any]]:
    """Строки перечня из data/rsosh_2026_27.json; пустой список, если файла нет."""
    path = path or DATA_DIR / RSOSH_FILE
    if not path.exists():
        return []
    try:
        rows: list[dict[str, Any]] = json.loads(path.read_text(encoding="utf-8"))["rows"]
        for row in rows:
            row["olympiad"], row["profile"], row["level"]  # noqa: B018
    except (ValueError, KeyError, TypeError) as exc:
        raise RsoshError(f"{path.name}: файл перечня повреждён ({exc!r})") from exc
    return rows


def apply_list(
    conn: psycopg.Connection[Any],
    rows: list[dict[str, Any]],
    resolve: Callable[[str], int | None],
    log: Callable[[str], None] = print,
) -> dict[str, int]:
    """Переносит перечень в базу: признак у олимпиады, уровень у пары «олимпиада + профиль».

    `resolve` — сопоставление названия со справочником (алиасы и squash, как для льгот).
    Всё, что не сопоставилось, выводится списком в лог: такие строки стоит проверить глазами.
    """
    olympiads = {
        oid: (canonical, kind)
        for oid, canonical, kind in conn.execute("SELECT id, canonical_name, kind FROM olympiads")
    }
    by_name: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        by_name.setdefault(row["olympiad"], []).append(row)

    names_of: dict[int, list[str]] = {}
    unmatched: list[str] = []
    for name in by_name:
        oid = resolve(name)
        if oid is None or oid not in olympiads:
            unmatched.append(name)
        else:
            names_of.setdefault(oid, []).append(name)

    # два названия перечня на одну олимпиаду справочника: берём то, что совпало с её названием
    listed: dict[int, list[dict[str, Any]]] = {}
    for oid, names in names_of.items():
        key = squash(olympiads[oid][0])
        own = [n for n in names if squash(n) == key]
        for name in names:
            if own and name not in own:
                log(f"      перечень: «{name}» слита с «{olympiads[oid][0]}», профили не учтены")
            else:
                listed.setdefault(oid, []).extend(by_name[name])

    for name in unmatched:
        log(f"      перечень: нет в справочнике: «{name}»")

    applicable = [
        oid
        for oid, (canonical, kind) in olympiads.items()
        if kind == "rsosh" or any(part in squash(canonical) for part in LISTED_INTERNATIONAL)
    ]
    conn.execute("UPDATE olympiads SET in_rsosh_2026_27 = NULL")
    conn.execute(
        "UPDATE olympiads SET in_rsosh_2026_27 = (id = ANY(%s)) WHERE id = ANY(%s)",
        (list(listed), applicable),
    )

    profiles: dict[tuple[int, str], int] = {
        (oid, key): pid
        for pid, oid, key in conn.execute(
            "SELECT id, olympiad_id, squash_key FROM olympiad_profiles"
        )
    }
    levels = missing = 0
    for oid, items in listed.items():
        for item in items:
            pid = profiles.get((oid, squash(clean_profile(item["profile"]))))
            if pid is None:
                missing += 1
                log(
                    f"      перечень: нет профиля в базе: «{olympiads[oid][0]}» / {item['profile']}"
                )
                continue
            conn.execute(
                "UPDATE olympiad_profiles SET level_2026_27 = %s WHERE id = %s",
                (item["level"], pid),
            )
            levels += 1
    return {
        "rows": len(rows),
        "olympiads": len(by_name),
        "matched_olympiads": len(listed),
        "unmatched_olympiads": len(unmatched),
        "levels": levels,
        "missing_profiles": missing,
        "not_listed": sum(1 for oid in applicable if oid not in listed),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Обновить перечень олимпиад РСОШ на 2026/27")
    parser.add_argument("--dry-run", action="store_true", help="ничего не записывать")
    parser.add_argument("--html", help="разобрать сохранённую страницу вместо скачивания")
    parser.add_argument("--insecure", action="store_true", help="не проверять TLS-сертификат")
    args = parser.parse_args()
    try:
        html = (
            Path(args.html).read_text(encoding="utf-8")
            if args.html
            else fetch(insecure=args.insecure)
        )
        data = build(html)
    except RsoshError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    rows = data["rows"]
    olympiads = {r["olympiad"] for r in rows}
    print(f"Олимпиад: {len(olympiads)}, строк профилей: {len(rows)}")
    if args.dry_run:
        return 0
    path = DATA_DIR / RSOSH_FILE
    path.write_text(json.dumps(data, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"Записано: {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
