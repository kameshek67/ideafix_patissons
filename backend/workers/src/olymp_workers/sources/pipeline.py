"""Конвейер одной задачи: скачать → найти документы → извлечь → проверить цитаты → разница.

Сеть и база приходят снаружи (DocumentStore, соединение psycopg), поэтому тесты идут без сети.
Результат — JobResult: его записывает в таблицу source_jobs jobs.py.
"""

from __future__ import annotations

import hashlib
import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

import psycopg
from olymp_domain.extraction import ExtractionFile, Record, quote_found

from olymp_workers.ai.documents import DocumentError, DocumentStore, safe_url
from olymp_workers.eval_extract import Row, db_rows, match_rows, row_of
from olymp_workers.extract.adapters import pick
from olymp_workers.extract.build import extract
from olymp_workers.extract.layout import load
from olymp_workers.refresh_sources import documents_on_page, is_personal_list

EXAMPLES = 5
RE_PDF_XLSX = re.compile(r"\.(pdf|xlsx)($|[?#])", re.IGNORECASE)
FIELD_NAMES = {
    "winner_role": "кому",
    "levels": "уровни",
    "grades": "классы",
    "ege_min": "мин. балл ЕГЭ",
    "ege_subjects": "предметы ЕГЭ",
}


class JobError(Exception):
    """Задача не может быть выполнена; текст — причина простыми словами."""


@dataclass
class JobResult:
    kind: str = "page"
    sha256: str = ""
    documents: list[dict[str, Any]] = field(default_factory=list)
    files: list[ExtractionFile] = field(default_factory=list)
    quotes_checked: int = 0
    quotes_found: int = 0
    diff: dict[str, Any] = field(default_factory=dict)

    @property
    def records(self) -> int:
        return sum(len(f.records) for f in self.files)


def fetch_error(exc: DocumentError) -> str:
    text = str(exc)
    if "скан" in text:
        return "документ — скан без текста"
    if text.startswith(("HTTP", "сайт", "таймаут", "сеть", "сертификат")):
        return f"сайт не ответил ({text})"
    return text


def decode_html(data: bytes) -> str:
    for encoding in ("utf-8", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", "replace")


def is_file(data: bytes) -> bool:
    return data.startswith((b"%PDF-", b"PK"))


def extract_document(
    store: DocumentStore, url: str, university: str, title: str, data: bytes | None = None
) -> tuple[ExtractionFile | None, dict[str, Any], tuple[int, int]]:
    """Один документ → (записи с проверенными цитатами, сведения о нём, (проверено, найдено))."""
    try:
        url = safe_url(url)  # один документ — один адрес, как бы он ни был записан на странице
    except DocumentError as exc:
        return None, {"url": url, "title": title, "records": 0, "error": fetch_error(exc)}, (0, 0)
    info: dict[str, Any] = {"url": url, "title": title}
    try:
        data = data if data is not None else store.raw(url)
        info["sha256"] = hashlib.sha256(data).hexdigest()
        loaded = load(url, data)
        if loaded.kind == "pdf" and not any(p.plain.strip() for p in loaded.pages):
            raise DocumentError("в документе нет текстового слоя (скан?)")
        adapter = pick(loaded, lambda link: store.get(link).pages)
        result = extract(loaded, university=university, title=title, adapter=adapter)
    except DocumentError as exc:
        info.update(records=0, error=fetch_error(exc))
        return None, info, (0, 0)
    except Exception:  # noqa: BLE001 - один плохой документ не должен ронять задачу
        info.update(records=0, error="документ не удалось разобрать")
        return None, info, (0, 0)
    good: list[Record] = []
    for rec in result.file.records:
        page = (
            loaded.pages[rec.source.page - 1] if 0 < rec.source.page <= len(loaded.pages) else None
        )
        if page is not None and quote_found(rec.source.quote, page.text):
            good.append(rec)
    checked, found = len(result.file.records), len(good)
    info.update(
        records=found,
        campaign=result.file.document.campaign,
        quotes_checked=checked,
        quotes_found=found,
        dropped=checked - found,
    )
    if not good:
        info["error"] = "не нашёл льгот"
        return None, info, (checked, found)
    file = result.file.model_copy(update={"records": good})
    file.document.pages = sorted({r.source.page for r in good})
    return file, info, (checked, found)


def find_documents(html: str, url: str) -> list[tuple[str, str]]:
    return documents_on_page(html, url)


def collect(store: DocumentStore, url: str, university: str, on_stage: Any = None) -> JobResult:
    """Скачивает ссылку оператора и разбирает документы; ошибки — JobError."""
    if is_personal_list("", url):
        raise JobError("это список людей, такие документы не разбираем")
    try:
        data = store.raw(url)
    except DocumentError as exc:
        raise JobError(fetch_error(exc)) from None
    result = JobResult(sha256=hashlib.sha256(data).hexdigest())
    if on_stage:
        on_stage("extracting")
    targets: list[tuple[str, str, bytes | None]]
    if is_file(data):
        result.kind = "document"
        targets = [(url, "", data)]
    else:
        targets = [
            (u, t, None) for t, u in find_documents(decode_html(data), url) if RE_PDF_XLSX.search(u)
        ]
        if not targets:
            raise JobError("на странице нет документов про олимпиады")
    for doc_url, title, doc_data in targets:
        file, info, (checked, found) = extract_document(store, doc_url, university, title, doc_data)
        result.documents.append(info)
        result.quotes_checked += checked
        result.quotes_found += found
        if file is not None:
            result.files.append(file)
    if not result.files:
        errors = [d["error"] for d in result.documents if d.get("error")]
        raise JobError(errors[0] if len(set(errors)) == 1 else "не нашёл льгот")
    return result


# ---------------------------------------------------------------- разница с базой


def _example(kind: str, record: Record | None, row: Row, **extra: Any) -> dict[str, Any]:
    ex: dict[str, Any] = {
        "kind": kind,
        "program": row.key[1],
        "olympiad": record.olympiad if record else row.key[2],
        "profile": record.profile if record else row.key[3],
        "benefit": row.key[4],
        "quote": row.quote,
        "page": row.page,
        "url": row.url,
    }
    ex.update(extra)
    return ex


def _show(value: Any) -> Any:
    return sorted(value) if isinstance(value, frozenset) else value


def compute_diff(conn: psycopg.Connection[Any], files: list[ExtractionFile]) -> dict[str, Any]:
    """Новые записи против текущих строк вуза по ключу (вуз, направление, олимпиада, профиль, тип).

    removed — строки, которые принесла эта же ссылка раньше и которых в новом разборе нет: другие
    строки вуза документ не убирает, он их только дополняет и заменяет по ключу."""
    added: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    changed: list[dict[str, Any]] = []
    same = 0
    counts: dict[str, int] = defaultdict(int)
    for file in files:
        new_rows = [row_of(rec) for rec in file.records]
        records = {id(row): rec for row, rec in zip(new_rows, file.records, strict=True)}
        current, _ = db_rows(conn, file)
        pairs = match_rows(new_rows, current, loose_profile=True)
        paired_new = {id(n) for n, _ in pairs}
        paired_old = {id(o) for _, o in pairs}
        for new, old in pairs:
            diffs = {
                name: [_show(getattr(old, name)), _show(getattr(new, name))]
                for name in FIELD_NAMES
                if getattr(old, name) != getattr(new, name)
            }
            if diffs:
                counts["changed"] += 1
                changed.append(_example("changed", records[id(new)], new, changes=_labelled(diffs)))
            else:
                same += 1
        for row in new_rows:
            if id(row) not in paired_new:
                counts["added"] += 1
                added.append(_example("added", records[id(row)], row))
        for old in current:
            if id(old) not in paired_old and old.url == file.document.url:
                counts["removed"] += 1
                removed.append(_example("removed", None, old))
    return {
        "added": counts["added"],
        "removed": counts["removed"],
        "changed": counts["changed"],
        "same": same,
        "examples": {
            "added": added[:EXAMPLES],
            "removed": removed[:EXAMPLES],
            "changed": changed[:EXAMPLES],
        },
    }


def _labelled(diffs: dict[str, list[Any]]) -> dict[str, list[Any]]:
    return {FIELD_NAMES[name]: pair for name, pair in diffs.items()}


def run_pipeline(
    conn: psycopg.Connection[Any],
    store: DocumentStore,
    url: str,
    university: str,
    on_stage: Any = None,
) -> JobResult:
    result = collect(store, url, university, on_stage)
    result.diff = compute_diff(conn, result.files)
    return result
