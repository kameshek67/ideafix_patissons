"""Справочные фрагменты: нарезка, источники сборки и загрузка в таблицу passages."""

import json
from pathlib import Path

import psycopg
from olymp_db.session import psycopg_dsn
from olymp_workers.ai.documents import Document, DocumentError, DocumentStore
from olymp_workers.passages import (
    CHUNK_SIZE,
    OVERLAP,
    FetchResult,
    collect,
    document_urls,
    fetch_documents,
    load_passages,
    split_text,
)
from olymp_workers.tables import clear_tables

REPO_DATA = Path(__file__).resolve().parents[3] / "data"
DOC_URL = "https://example.org/rules.pdf"


def test_split_keeps_short_text_whole() -> None:
    assert split_text("  Коротко.\n\n\nДва  абзаца. ") == ["Коротко.\nДва абзаца."]
    assert split_text("   ") == []


def test_split_overlaps_and_does_not_cut_words() -> None:
    words = [f"слово{i}" for i in range(400)]
    chunks = split_text(" ".join(words))
    assert len(chunks) > 3
    assert all(len(c) <= CHUNK_SIZE for c in chunks)
    for left, right in zip(chunks, chunks[1:], strict=False):
        tail = left[-OVERLAP:]
        assert right.split()[0] in tail.split()  # перекрытие: следующий кусок начинается внутри
    assert {w for c in chunks for w in c.split()} == set(words)  # ни одно слово не потеряно


def make_data(tmp_path: Path) -> tuple[Path, Path]:
    data, cache = tmp_path / "data", tmp_path / "cache"
    data.mkdir()
    rules = json.loads((REPO_DATA / "admission_rules.json").read_text(encoding="utf-8"))
    (data / "admission_rules.json").write_text(
        json.dumps({"rules": rules["rules"][:1]}, ensure_ascii=False), encoding="utf-8"
    )
    cards = json.loads((REPO_DATA / "olympiad_cards.json").read_text(encoding="utf-8"))
    (data / "olympiad_cards.json").write_text(
        json.dumps({"olympiads": cards["olympiads"][:1]}, ensure_ascii=False), encoding="utf-8"
    )
    (data / "university_documents.json").write_text(
        json.dumps(
            {
                "МАИ": {
                    "documents": [
                        {"title": "Правила приёма открыть", "url": DOC_URL},
                        {"title": "Нет в кэше", "url": "https://example.org/none.pdf"},
                    ]
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data / "olympiad_materials.json").write_text(
        json.dumps(
            {
                "materials": [
                    {
                        "olympiad": "Ломоносов",
                        "title": "Архив заданий прошлых лет",
                        "kind": "tasks",
                        "url": "https://example.org/archive",
                    },
                    {"title": "Без ссылки"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    store = DocumentStore(cache)
    page = "Приём по олимпиадам проходит в июле. " * 30
    store._store(Document(DOC_URL, DOC_URL, "pdf", "0" * 64, (page, "мало")))
    store.close()
    return data, cache


def test_collect_reads_every_source(tmp_path: Path) -> None:
    data, cache = make_data(tmp_path)
    found = collect(data, cache)
    kinds = {p.source_type for p in found}
    assert kinds == {"admission_rule", "olympiad_card", "university_document", "olympiad_material"}
    documents = [p for p in found if p.source_type == "university_document"]
    assert {p.page for p in documents} == {1}  # страница «мало» — шум, в индекс не идёт
    assert all(p.title == "МАИ: Правила приёма" and p.url == DOC_URL for p in documents)
    assert len(documents) == 2  # страница в 1100 символов даёт два куска
    material = next(p for p in found if p.source_type == "olympiad_material")
    assert "Ломоносов" in material.body and "задания" in material.body
    assert material.title == "Ломоносов: Архив заданий прошлых лет"
    assert material.url == "https://example.org/archive"
    assert all(p.url.startswith("https://") for p in found)


def test_missing_cache_and_files_are_skipped(tmp_path: Path) -> None:
    data, _ = make_data(tmp_path)
    (data / "olympiad_materials.json").unlink()
    found = collect(data, tmp_path / "no-such-cache")
    assert {p.source_type for p in found} == {"admission_rule", "olympiad_card"}
    assert collect(tmp_path / "empty", tmp_path / "no-such-cache") == []


def test_load_passages_makes_searchable_rows(empty_database_url: str, tmp_path: Path) -> None:
    data, cache = make_data(tmp_path)
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        try:
            stats = load_passages(conn, data, cache)
            assert stats["university_document"] == 2
            rows = conn.execute(
                """SELECT source_type, page FROM passages
                   WHERE document @@ websearch_to_tsquery('russian', 'олимпиадам приёмы июль')"""
            ).fetchall()
            assert ("university_document", 1) in rows
            count = conn.execute("SELECT count(*) FROM passages").fetchone()[0]
            assert count == sum(stats.values())
        finally:
            conn.rollback()
            clear_tables(conn, ["passages"])
            conn.commit()


def test_real_materials_file_is_indexed() -> None:
    from olymp_workers.passages import material_passages

    found = list(material_passages(REPO_DATA))
    raw = json.loads((REPO_DATA / "olympiad_materials.json").read_text(encoding="utf-8"))
    assert len(found) >= len(raw["materials"])
    assert all(p.url.startswith("http") and p.title for p in found)


class FakeLoader:
    """Подменённый загрузчик: в кэше один адрес, один недоступен, остальные «скачиваются»."""

    def __init__(self, cached: set[str], broken: set[str]) -> None:
        self.cache, self.broken, self.asked = set(cached), broken, []

    def cached(self, url: str) -> Document | None:
        return Document(url, url, "html", "0" * 64, ("текст",)) if url in self.cache else None

    def get(self, url: str) -> Document:
        self.asked.append(url)
        if url in self.broken:
            raise DocumentError("HTTP 404")
        return Document(url, url, "html", "0" * 64, ("текст",))


def test_document_urls_merge_files_and_skip_duplicates(tmp_path: Path) -> None:
    data, _ = make_data(tmp_path)
    (data / "extracted").mkdir()
    (data / "extracted" / "a.json").write_text(
        json.dumps(
            {"document": {"title": "Приложение", "url": "https://example.org/extra.pdf"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (data / "extracted" / "b.json").write_text(
        json.dumps({"document": {"title": "Дубль", "url": DOC_URL}}), encoding="utf-8"
    )
    urls = document_urls(data)
    assert set(urls) == {DOC_URL, "https://example.org/none.pdf", "https://example.org/extra.pdf"}
    assert urls[DOC_URL] == "Правила приёма открыть"  # первое название остаётся


def test_fetch_counts_downloaded_cached_failed_and_skips_people_lists() -> None:
    urls = {
        "https://example.org/a.pdf": "Правила приёма",
        "https://example.org/b.pdf": "Положение",
        "https://example.org/c.pdf": "Приложение",
        "https://example.org/list.pdf": "Список поступающих, рекомендованных к зачислению",
    }
    loader = FakeLoader(cached={"https://example.org/a.pdf"}, broken={"https://example.org/c.pdf"})
    result = fetch_documents(urls, loader, workers=3)
    assert result == FetchResult(
        downloaded=1,
        from_cache=1,
        skipped=1,
        failed={"https://example.org/c.pdf": "HTTP 404"},
    )
    assert sorted(loader.asked) == ["https://example.org/b.pdf", "https://example.org/c.pdf"]
