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
from dataclasses import dataclass
from typing import Any

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


@dataclass(frozen=True)
class TableLine:
    """Строка таблицы страницы: kind — columns | section | row; text — как она попадёт в текст."""

    kind: str
    text: str
    cells: tuple[str, ...] = ()
    code: str = ""  # код направления из заголовка раздела, действующий для строки
    filled: tuple[bool, ...] = ()  # ячейки строки, заполненные значением сверху


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

    def page_items(self, tables: Sequence[Table]) -> list[TableLine]:
        items: list[TableLine] = []
        for table in tables:
            width = max((len(row) for row in table), default=0)
            if self.header and width:
                head = self.header[-width:]
                columns = [_short(c) for c in head]
                cells = tuple(c or "" for c in head)
                items.append(TableLine("columns", "Колонки: " + " | ".join(columns), cells))
            for raw in table:
                row = [_clean(cell) for cell in raw]
                filled = [cell for cell in row if cell]
                if not filled:
                    continue
                if self._is_header(row):
                    self.header = row
                    cells = tuple(c or "" for c in row)
                    items.append(
                        TableLine(
                            "columns", "Колонки: " + " | ".join(_short(c) for c in row), cells
                        )
                    )
                    continue
                # заголовок раздела — заполнена только первая ячейка; строка-продолжение
                # с одной ячейкой справа («Право на 100 баллов») — это данные, а не раздел
                if len(filled) == 1 and len(row) >= 3 and row[0]:
                    match = PROGRAM_CODE.search(filled[0])
                    self.code = match.group(0) if match else ""
                    items.append(
                        TableLine("section", f"Раздел: {filled[0]}", (filled[0],), self.code)
                    )
                    continue
                previous = self.previous.get(len(row))
                merged = tuple(cell is None for cell in row)
                if previous:
                    row = [
                        cell if cell is not None else above
                        for cell, above in zip(row, previous, strict=True)
                    ]
                self.previous[len(row)] = row
                prefix = f"[{self.code}] " if self.code else ""
                cells = tuple(cell or "" for cell in row)
                items.append(TableLine("row", prefix + " | ".join(cells), cells, self.code, merged))
        return items

    def page_lines(self, tables: Sequence[Table]) -> list[str]:
        return [item.text for item in self.page_items(tables)]


def page_tables(page: Any) -> list[list[list[Cell]]]:
    """Таблицы страницы pdfplumber; пустое место вместо ячейки без геометрии — «», а не None.

    None у pdfplumber — и «ячейка объединена с верхней», и «ячейки нет вовсе» (линии сетки оборваны
    у края страницы). Заполнять сверху можно только первое: ячейка выше должна доходить до строки."""
    tables = []
    for table in page.find_tables():
        data = [list(row) for row in table.extract()]
        # нижняя граница самой длинной ячейки выше, по каждой колонке
        reach: dict[int, float] = {}
        for r, row in enumerate(table.rows):
            top = min((c[1] for c in row.cells if c is not None), default=None)
            for c, box in enumerate(row.cells):
                if box is not None:
                    reach[c] = max(reach.get(c, 0.0), box[3])
                elif (
                    r < len(data)
                    and c < len(data[r])
                    and data[r][c] is None
                    and (top is None or reach.get(c, 0.0) <= top + 1.0)
                ):
                    data[r][c] = ""  # выше ячейка до этой строки не доходит: объединения нет
        tables.append(data)
    return tables


def page_text(plain: str, table_lines: Sequence[str]) -> str:
    """Текст страницы для поиска и цитат: сначала таблицы по строкам, затем обычный текст."""
    if not table_lines:
        return plain
    return f"{TABLES_TITLE}\n" + "\n".join(table_lines) + f"\n\nТекст страницы:\n{plain}"
