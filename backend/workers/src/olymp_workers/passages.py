"""Справочные фрагменты для поиска помощника (таблица passages).

Источники: правила приёма (data/admission_rules.json), карточки олимпиад
(data/olympiad_cards.json), тексты документов вузов из кэша страниц и материалы олимпиад
(data/olympiad_materials.json, если файл есть). Сеть не используется: документ, которого нет
в кэше, пропускается. Текст режется на куски ~800 символов с перекрытием.

Вызывается из olymp-ingest в той же транзакции; отдельно — командой olymp-passages, она
пересобирает только эту таблицу (например, после обновления кэша документов).
"""

import argparse
import json
import os
import re
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
from olymp_db.session import database_url, psycopg_dsn
from olymp_domain.admission_rules import RULES_FILE, load_rules
from olymp_domain.olympiad_cards import load_cards

from .ai.documents import DEFAULT_CACHE, DocumentError, DocumentStore
from .tables import clear_tables

CARDS_FILE = "olympiad_cards.json"
MATERIALS_FILE = "olympiad_materials.json"
DOCUMENTS_FILE = "university_documents.json"

CHUNK_SIZE = 800
OVERLAP = 120
MIN_CHUNK = 60  # короче — шум страницы (номер, колонтитул)
MAX_TITLE = 300

UNIVERSITY_DOCUMENT = "university_document"
OLYMPIAD_CARD = "olympiad_card"
ADMISSION_RULE = "admission_rule"
OLYMPIAD_MATERIAL = "olympiad_material"

RE_SPACES = re.compile(r"[ \t\r\f\v]+")
RE_BREAKS = re.compile(r"\n\s*\n+")
RE_LINK_WORD = re.compile(r"\s*\b(открыть|скачать)\s*$", re.IGNORECASE)


@dataclass(frozen=True)
class Passage:
    source_type: str
    title: str
    url: str
    page: int | None
    chunk: int
    body: str


def clean(text: str) -> str:
    return RE_BREAKS.sub("\n", RE_SPACES.sub(" ", text)).strip()


def split_text(text: str, size: int = CHUNK_SIZE, overlap: int = OVERLAP) -> list[str]:
    """Куски не длиннее size с перекрытием overlap; границу ищем по концу предложения,
    строки или пробелу в последней трети куска, чтобы не рвать слова."""
    text = clean(text)
    if len(text) <= size:
        return [text] if text else []
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            floor = start + size * 2 // 3
            cut = max(text.rfind(mark, floor, end) for mark in (". ", "\n", "; "))
            if cut < 0:
                cut = text.rfind(" ", floor, end)
            if cut >= 0:
                end = cut + 1
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        # перекрытие не должно зациклить: следующий кусок начинается строго правее
        start = max(end - overlap, start + 1)
        space = text.find(" ", start, end)
        if 0 <= space < end:
            start = space + 1
    return chunks


def passages_of(
    source_type: str, title: str, url: str, text: str, page: int | None = None
) -> Iterator[Passage]:
    for number, body in enumerate(split_text(text)):
        yield Passage(source_type, title[:MAX_TITLE], url, page, number, body)


def rule_passages(data_dir: Path) -> Iterator[Passage]:
    path = data_dir / RULES_FILE
    if not path.is_file():
        return
    for rule in load_rules(path):
        text = f"{rule.topic}. {rule.text} Цитата: {rule.quote}"
        yield from passages_of(ADMISSION_RULE, rule.source_title, rule.source_url, text)


def card_passages(data_dir: Path) -> Iterator[Passage]:
    path = data_dir / CARDS_FILE
    if not path.is_file():
        return
    for card in load_cards(path):
        parts = [card.olympiad, card.summary, f"Классы: {card.grades}."]
        if card.formats:
            parts.append("Формат: " + ", ".join(card.formats) + ".")
        if card.stages:
            parts.append("Этапы: " + "; ".join(card.stages) + ".")
        for track in card.tracks:
            topics = f" ({', '.join(track.topics)})" if track.topics else ""
            parts.append(f"Секция «{track.name}», профиль «{track.profile}»{topics}.")
        yield from passages_of(OLYMPIAD_CARD, card.olympiad, card.source_url, " ".join(parts))


MATERIAL_KINDS = {
    "regulations": "положение, регламент олимпиады",
    "tasks": "задания и архив прошлых лет",
    "schedule": "расписание этапов",
}


def material_passages(data_dir: Path) -> Iterator[Passage]:
    """Материалы олимпиад — только ссылки: индексируем олимпиаду, название и тип материала."""
    path = data_dir / MATERIALS_FILE
    if not path.is_file():
        return
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw.get("materials") if isinstance(raw, dict) else raw
    for item in items if isinstance(items, list) else []:
        if not isinstance(item, dict):
            continue
        olympiad = str(item.get("olympiad") or "").strip()
        title = str(item.get("title") or "").strip()
        url = str(item.get("url") or "").strip()
        if not (title and url):
            continue
        kind = str(item.get("kind") or item.get("type") or "").strip()
        kind = MATERIAL_KINDS.get(kind, kind)
        shown = f"{olympiad}: {title}" if olympiad else title
        text = ". ".join(p for p in (olympiad, title, kind) if p)
        yield from passages_of(OLYMPIAD_MATERIAL, shown, url, text)


def document_passages(data_dir: Path, cache_dir: Path) -> Iterator[Passage]:
    """Тексты документов вузов из кэша страниц; нет кэша или документа — пропуск."""
    path = data_dir / DOCUMENTS_FILE
    if not path.is_file() or not cache_dir.is_dir():
        return
    entries: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    store = DocumentStore(cache_dir)
    seen: set[str] = set()
    try:
        for university, entry in entries.items():
            for item in entry.get("documents") or []:
                url = str(item.get("url") or "").strip()
                if not url or url in seen:
                    continue
                seen.add(url)
                try:
                    document = store.cached(url)
                except DocumentError:
                    continue
                if document is None:
                    continue
                name = RE_LINK_WORD.sub("", str(item.get("title") or "")).strip()
                title = f"{university}: {name}" if name else university
                for number, page in enumerate(document.pages, 1):
                    yield from passages_of(UNIVERSITY_DOCUMENT, title, url, page, number)
    finally:
        store.close()


def collect(data_dir: Path, cache_dir: Path) -> list[Passage]:
    found = [
        *rule_passages(data_dir),
        *card_passages(data_dir),
        *document_passages(data_dir, cache_dir),
        *material_passages(data_dir),
    ]
    return [p for p in found if len(p.body) >= MIN_CHUNK or p.source_type != UNIVERSITY_DOCUMENT]


def load_passages(
    conn: psycopg.Connection[Any], data_dir: Path, cache_dir: Path | None = None
) -> dict[str, int]:
    """Заполняет passages. Таблица к этому моменту очищена; статистика — по типам источников."""
    cache = cache_dir or Path(os.environ.get("OLYMP_DOCUMENTS_CACHE", DEFAULT_CACHE))
    found = collect(data_dir, cache)
    with conn.cursor() as cur:
        cur.executemany(
            """INSERT INTO passages (source_type, title, url, page, chunk, body, document)
               VALUES (%s, %s, %s, %s, %s, %s, to_tsvector('russian', %s))""",
            [
                (p.source_type, p.title, p.url, p.page, p.chunk, p.body, f"{p.title}. {p.body}")
                for p in found
            ],
        )
    stats: dict[str, int] = {}
    for p in found:
        stats[p.source_type] = stats.get(p.source_type, 0) + 1
    return stats


def default_data_dir() -> Path:
    return Path(os.environ.get("OLYMP_DATA_DIR", Path(__file__).resolve().parents[4] / "data"))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Пересобрать справочные фрагменты для помощника (только таблицу passages)"
    )
    parser.add_argument("--database-url", default=database_url())
    parser.add_argument("--data-dir", type=Path, default=default_data_dir())
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(os.environ.get("OLYMP_DOCUMENTS_CACHE", DEFAULT_CACHE)),
        help="кэш страниц документов вузов; сеть не используется",
    )
    args = parser.parse_args()
    with psycopg.connect(psycopg_dsn(args.database_url)) as conn:
        clear_tables(conn, ["passages"])
        stats = load_passages(conn, args.data_dir, args.cache_dir)
        conn.commit()
    print(f"фрагментов: {sum(stats.values())} ({', '.join(f'{k} {v}' for k, v in stats.items())})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
