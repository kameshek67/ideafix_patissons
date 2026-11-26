"""Документ как страницы со строками таблиц: PDF — через TableReader, xlsx — по листам."""

from __future__ import annotations

import hashlib
import io
from dataclasses import dataclass, field

import pdfplumber

from olymp_workers.ai.documents import MAX_PAGES, DocumentError
from olymp_workers.ai.tables import TableReader, page_tables, page_text


@dataclass(frozen=True)
class Line:
    """Строка таблицы страницы: columns — заголовок, section — раздел, row — данные."""

    kind: str
    text: str
    cells: tuple[str, ...] = ()
    code: str = ""  # код направления из заголовка раздела
    row: int | None = None  # строка листа xlsx
    filled: tuple[bool, ...] = ()  # ячейки, заполненные значением сверху (объединённые)


@dataclass
class Page:
    number: int  # у xlsx — номер листа
    plain: str = ""
    lines: list[Line] = field(default_factory=list)
    name: str = ""  # название листа xlsx

    @property
    def text(self) -> str:
        """Текст страницы в том виде, в котором его ищет проверка цитат."""
        return page_text(self.plain, [line.text for line in self.lines])


@dataclass
class Loaded:
    url: str
    sha256: str
    kind: str  # pdf | xlsx
    pages: list[Page]


def detect(data: bytes) -> str:
    head = data[:8]
    if head.startswith(b"%PDF-"):
        return "pdf"
    if head.startswith(b"PK"):
        return "xlsx"
    raise DocumentError("формат не поддерживается: нужен PDF или xlsx")


def load_pdf(data: bytes) -> list[Page]:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise DocumentError(f"слишком много страниц: {len(pdf.pages)}")
            reader = TableReader()
            pages = []
            for number, page in enumerate(pdf.pages, 1):
                items = reader.page_items(page_tables(page))
                lines = [Line(i.kind, i.text, i.cells, i.code, filled=i.filled) for i in items]
                pages.append(Page(number, page.extract_text() or "", lines))
            return pages
    except DocumentError:
        raise
    except Exception as exc:  # noqa: BLE001 - битый PDF не должен ронять прогон
        raise DocumentError(f"PDF не разбирается: {type(exc).__name__}") from None


def load_xlsx(data: bytes) -> list[Page]:
    import openpyxl  # type: ignore[import-untyped]

    try:
        book = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        raise DocumentError(f"xlsx не разбирается: {type(exc).__name__}") from None
    pages = []
    for number, sheet in enumerate(book.worksheets, 1):
        page = Page(number, name=sheet.title)
        for index, values in enumerate(sheet.iter_rows(values_only=True), 1):
            cells = tuple(" ".join(str(v).split()) if v is not None else "" for v in values)
            if any(cells):
                page.lines.append(Line("row", " | ".join(cells), cells, row=index))
        pages.append(page)
    book.close()
    return pages


def load(url: str, data: bytes) -> Loaded:
    kind = detect(data)
    pages = load_pdf(data) if kind == "pdf" else load_xlsx(data)
    return Loaded(url, hashlib.sha256(data).hexdigest(), kind, pages)
