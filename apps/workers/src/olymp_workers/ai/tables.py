"""Таблицы из PDF вузов в строки, понятные модели и проверяемые кодом.

Обычное извлечение текста перемешивает колонки больших таблиц (ВШЭ: «Прикладная 6 математика …»),
и модель не может процитировать строку дословно. Здесь таблица читается по ячейкам:

- объединённая по вертикали ячейка (pdfplumber отдаёт None) заполняется значением сверху, в том
  числе через границу страницы — у каждой строки своя олимпиада;
- строка, где заполнена только первая ячейка («Направление подготовки 09.03.04 …»), — заголовок раздела;
  код направления из него ставится в начало следующих строк: «[09.03.04] …»;
- заголовок колонок с первой страницы выравнивается по правому краю: на следующих страницах в
  таблице нет колонок «№» и «программа».

Всё это текст документа, только разложенный по строкам; цитату из него код проверяет как обычно.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

Cell = str | None
Table = Sequence[Sequence[Cell]]

PROGRAM_CODE = re.compile(r"(?<![0-9.])\d{2}\.\d{2}\.\d{2}(?![0-9])")
HEADER_WORDS = re.compile(r"олимпиад|наименован|профил|предмет", re.I)
HEADER_CELL_WORDS = 5

TABLES_TITLE = (
    "Таблицы страницы: строки по порядку, ячейки через «|», объединённые ячейки заполнены "
    "значением сверху, в квадратных скобках — код направления из заголовка раздела."
)


def _clean(cell: Cell) -> Cell:
    return None if cell is None else " ".join(str(cell).split())


def _short(cell: Cell) -> str:
    words = (cell or "").split()
    return " ".join(words[:HEADER_CELL_WORDS]) + ("…" if len(words) > HEADER_CELL_WORDS else "")


class TableReader:
    """Читает таблицы документа страница за страницей; состояние переходит между страницами."""

    def __init__(self) -> None:
        self.header: list[Cell] | None = None
        self.code = ""
        self.previous: dict[int, list[Cell]] = {}  # последняя строка по ширине таблицы

    def _is_header(self, row: list[Cell]) -> bool:
        return (
            self.header is None
            and all(cell for cell in row)
            and sum(bool(HEADER_WORDS.search(cell or "")) for cell in row) >= 2
        )

    def page_lines(self, tables: Sequence[Table]) -> list[str]:
        lines: list[str] = []
        for table in tables:
            width = max((len(row) for row in table), default=0)
            if self.header and width:
                columns = [_short(c) for c in self.header[-width:]]
                lines.append("Колонки: " + " | ".join(columns))
            for raw in table:
                row = [_clean(cell) for cell in raw]
                filled = [cell for cell in row if cell]
                if not filled:
                    continue
                if self._is_header(row):
                    self.header = row
                    lines.append("Колонки: " + " | ".join(_short(c) for c in row))
                    continue
                # заголовок раздела — заполнена только первая ячейка; строка-продолжение
                # с одной ячейкой справа («Право на 100 баллов») — это данные, а не раздел
                if len(filled) == 1 and len(row) >= 3 and row[0]:
                    match = PROGRAM_CODE.search(filled[0])
                    self.code = match.group(0) if match else ""
                    lines.append(f"Раздел: {filled[0]}")
                    continue
                previous = self.previous.get(len(row))
                if previous:
                    row = [
                        cell if cell is not None else above
                        for cell, above in zip(row, previous, strict=True)
                    ]
                self.previous[len(row)] = row
                prefix = f"[{self.code}] " if self.code else ""
                lines.append(prefix + " | ".join(cell or "" for cell in row))
        return lines


def page_text(plain: str, table_lines: Sequence[str]) -> str:
    """Текст страницы для поиска и цитат: сначала таблицы по строкам, затем обычный текст."""
    if not table_lines:
        return plain
    return f"{TABLES_TITLE}\n" + "\n".join(table_lines) + f"\n\nТекст страницы:\n{plain}"
