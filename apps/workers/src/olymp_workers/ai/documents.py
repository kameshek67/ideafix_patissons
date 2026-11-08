"""Документы вузов для ИИ-парсеров: скачивание с ограничениями, кэш на диске, текст страниц.

- Только http(s), таймаут, не больше MAX_BYTES, честный User-Agent, без обхода защиты от ботов.
- Тип файла определяется по содержимому: сервер может отдать HTML под видом PDF.
- Проверка TLS включена; без неё — только явным флагом (insecure).
- Кэш: файл и его текст по страницам хранятся в cache_dir, повторный запуск не ходит в сеть.
  Ошибки не кэшируются на диске: ссылка может ожить.
"""

from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import urllib.parse as up
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path

import httpx
import pdfplumber

from .tables import TableReader, page_text

MAX_BYTES = 25 * 1024 * 1024
MAX_PAGES = 800
TIMEOUT = 30.0
# только ASCII: заголовки HTTP не принимают кириллицу
USER_AGENT = "OlympBot/1.0 (+https://ideafix.patissons.tech; admission documents check)"
DEFAULT_CACHE = Path(".cache/olymp/documents")
# меняется вместе со способом извлечения текста: старый кэш страниц перестаёт использоваться
EXTRACTOR_VERSION = "v2-tables"

# pdfminer шумно предупреждает о каждом нестандартном шрифте
logging.getLogger("pdfminer").setLevel(logging.ERROR)


class DocumentError(Exception):
    """Документ недоступен или не разбирается; текст — короткая причина для отчёта."""


@dataclass(frozen=True)
class Document:
    url: str
    final_url: str
    kind: str  # pdf | html
    sha256: str
    pages: tuple[str, ...]


def safe_url(url: str) -> str:
    """Проверяет схему и кодирует кириллицу и пробелы в адресе, не трогая уже закодированное."""
    url = url.strip()
    parts = up.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.netloc:
        raise DocumentError("адрес не http(s)")
    return up.urlunsplit(
        (
            parts.scheme,
            parts.netloc.encode("idna").decode("ascii")
            if not parts.netloc.isascii()
            else parts.netloc,
            up.quote(parts.path, safe="/%:@!$&'()*+,;=-._~"),
            up.quote(parts.query, safe="=&%:@!$'()*+,;/?-._~"),
            "",
        )
    )


def detect_kind(data: bytes, content_type: str) -> str:
    head = data[:1024].lstrip()
    if head.startswith(b"%PDF-"):
        return "pdf"
    if "html" in content_type.lower() or re.match(rb"(?i)<(!doctype|html|head|body|div|p)\b", head):
        return "html"
    raise DocumentError(f"формат не поддерживается ({content_type or 'неизвестен'})")


def pdf_pages(data: bytes) -> tuple[str, ...]:
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if len(pdf.pages) > MAX_PAGES:
                raise DocumentError(f"слишком много страниц: {len(pdf.pages)}")
            reader = TableReader()  # таблица продолжается со страницы на страницу
            return tuple(
                page_text(page.extract_text() or "", reader.page_lines(page.extract_tables()))
                for page in pdf.pages
            )
    except DocumentError:
        raise
    except Exception as exc:  # noqa: BLE001 - битый PDF не должен ронять прогон
        raise DocumentError(f"PDF не разбирается: {type(exc).__name__}") from None


class _TextParser(HTMLParser):
    SKIP = {"script", "style", "noscript", "svg", "template"}
    BREAK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6", "table", "section"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skipping = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self.SKIP:
            self.skipping += 1
        elif tag in self.BREAK:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self.SKIP and self.skipping:
            self.skipping -= 1

    def handle_data(self, data: str) -> None:
        if not self.skipping:
            self.parts.append(data)


def html_text(data: bytes, encoding: str | None) -> str:
    """Видимый текст HTML-страницы; кодировка из заголовка, иначе UTF-8, иначе cp1251."""
    for candidate in (encoding, "utf-8", "cp1251"):
        if not candidate:
            continue
        try:
            raw = data.decode(candidate)
            break
        except (LookupError, UnicodeDecodeError):
            continue
    else:
        raw = data.decode("utf-8", "replace")
    parser = _TextParser()
    parser.feed(raw)
    text = "".join(parser.parts)
    return re.sub(r"\n\s*\n+", "\n", re.sub(r"[ \t\r\f\v]+", " ", text)).strip()


class DocumentStore:
    """Скачивает и разбирает документы; внутри одного запуска ошибки запоминаются."""

    def __init__(
        self,
        cache_dir: Path = DEFAULT_CACHE,
        *,
        insecure: bool = False,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.cache_dir = cache_dir
        self.client = httpx.Client(
            timeout=TIMEOUT,
            follow_redirects=True,
            verify=not insecure,
            headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,text/html,*/*"},
            transport=transport,
        )
        self.failed: dict[str, str] = {}
        self.memory: dict[str, Document] = {}
        self.downloads = 0

    def close(self) -> None:
        self.client.close()

    def _paths(self, url: str) -> tuple[Path, Path]:
        key = hashlib.sha256(url.encode()).hexdigest()
        return (
            self.cache_dir / f"{key}.json",
            self.cache_dir / f"{key}.{EXTRACTOR_VERSION}.pages.json",
        )

    def get(self, url: str) -> Document:
        url = safe_url(url)
        if url in self.memory:
            return self.memory[url]
        if url in self.failed:
            raise DocumentError(self.failed[url])
        try:
            document = self._cached(url) or self._download(url)
        except DocumentError as exc:
            self.failed[url] = str(exc)
            raise
        self.memory[url] = document
        return document

    def _cached(self, url: str) -> Document | None:
        meta_path, pages_path = self._paths(url)
        if not (meta_path.is_file() and pages_path.is_file()):
            return None
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            pages = json.loads(pages_path.read_text(encoding="utf-8"))
            return Document(url, meta["final_url"], meta["kind"], meta["sha256"], tuple(pages))
        except (OSError, ValueError, KeyError):
            return None  # повреждённый кэш — скачаем заново

    def _download(self, url: str) -> Document:
        self.downloads += 1
        try:
            with self.client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise DocumentError(f"HTTP {response.status_code}")
                declared = int(response.headers.get("content-length") or 0)
                if declared > MAX_BYTES:
                    raise DocumentError("файл больше 25 МБ")
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > MAX_BYTES:
                        raise DocumentError("файл больше 25 МБ")
                    chunks.append(chunk)
                data = b"".join(chunks)
                content_type = response.headers.get("content-type", "")
                encoding = response.charset_encoding
                final_url = str(response.url)
        except httpx.ConnectError as exc:
            if "CERTIFICATE" in str(exc).upper() or "SSL" in str(exc).upper():
                raise DocumentError(
                    "сертификат сайта не прошёл проверку (флаг --insecure)"
                ) from None
            raise DocumentError("сайт недоступен") from None
        except httpx.TimeoutException:
            raise DocumentError("таймаут") from None
        except httpx.HTTPError as exc:
            raise DocumentError(f"сеть: {type(exc).__name__}") from None

        kind = detect_kind(data, content_type)
        pages = pdf_pages(data) if kind == "pdf" else (html_text(data, encoding),)
        if not any(page.strip() for page in pages):
            raise DocumentError("в документе нет текстового слоя (скан?)")
        document = Document(url, final_url, kind, hashlib.sha256(data).hexdigest(), pages)
        self._store(document)
        return document

    def _store(self, document: Document) -> None:
        meta_path, pages_path = self._paths(document.url)
        meta = {
            "url": document.url,
            "final_url": document.final_url,
            "kind": document.kind,
            "sha256": document.sha256,
        }
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            pages_path.write_text(json.dumps(document.pages, ensure_ascii=False), encoding="utf-8")
            meta_path.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass  # без кэша работаем, просто медленнее
