"""Разбор ссылки оператора: страница → документы → записи → разница → приём; без сети."""

import hashlib
import io
import json
import logging
from collections.abc import Iterator
from typing import Any

import httpx
import openpyxl
import psycopg
import pytest
from olymp_db.session import psycopg_dsn
from olymp_workers.ai.documents import DocumentStore, safe_url
from olymp_workers.eval_extract import Row
from olymp_workers.sources import cli, grade, jobs, pipeline
from olymp_workers.sources.cli import main as cli_main
from olymp_workers.sources.cli import recheck_sources

PAGE = "https://example.edu/olymp/"
XLSX = "https://example.edu/files/Олимпиады_БВИ.xlsx"
UNIVERSITY = "Вуз Тестовый"


def xlsx_bytes() -> bytes:
    book = openpyxl.Workbook()
    sheet = book.active
    sheet.append(["Код и наименование специальности", "Олимпиада", "Профиль олимпиады"])
    sheet.append(["37.03.01 Психология", "Олимпиада А", "право"])
    sheet.append(["37.03.01 Психология", "Олимпиада А", "экономика"])
    sheet.append(["38.03.01 Экономика", "Олимпиада Б", "математика"])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


def blank_pdf() -> bytes:
    """PDF без текстового слоя: страница без единой строки."""
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 200 200] >>",
    ]
    out = b"%PDF-1.4\n"
    offsets = []
    for number, obj in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n{obj}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def site(pages: dict[str, tuple[int, bytes, str]]) -> Any:
    known = {safe_url(url): page for url, page in pages.items()}

    def handle(request: httpx.Request) -> httpx.Response:
        status, body, ctype = known.get(str(request.url), (404, b"", "text/html"))
        return httpx.Response(status, content=body, headers={"content-type": ctype})

    return handle


def store_for(tmp_path: Any, pages: dict[str, tuple[int, bytes, str]]) -> DocumentStore:
    return DocumentStore(tmp_path, transport=httpx.MockTransport(site(pages)))


def html(*links: tuple[str, str]) -> tuple[int, bytes, str]:
    body = "".join(f'<a href="{url}">{label}</a>' for url, label in links)
    return 200, f"<html><body>{body}</body></html>".encode(), "text/html; charset=utf-8"


def empty_book() -> bytes:
    book = openpyxl.Workbook()
    book.active.append(["Что-то", "не то"])
    buffer = io.BytesIO()
    book.save(buffer)
    return buffer.getvalue()


XLSX_PAGE = (200, xlsx_bytes(), "application/octet-stream")


@pytest.fixture
def conn(empty_database_url: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(psycopg_dsn(empty_database_url)) as c:
        yield c
        c.rollback()
        c.execute("DELETE FROM sources")
        c.execute("DELETE FROM document_records")
        c.commit()


def status_of(conn: psycopg.Connection[Any], job_id: int) -> tuple[str, str]:
    return conn.execute("SELECT status, error FROM source_jobs WHERE id = %s", (job_id,)).fetchone()


def test_page_with_document_goes_to_review_with_diff_and_webhook(
    conn: psycopg.Connection[Any], tmp_path: Any
) -> None:
    pages = {
        PAGE: html(
            (XLSX, "Олимпиады школьников: перечень"),
            ("https://example.edu/spisok.xlsx", "Список поступающих"),
        ),
        XLSX: XLSX_PAGE,
    }
    sent: list[dict[str, Any]] = []

    def hook(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        return httpx.Response(200)

    notify = jobs.webhook_notifier("https://hooks.test/ops", httpx.MockTransport(hook))
    _, job_id, new = jobs.enqueue(conn, PAGE, UNIVERSITY, "test")
    assert new
    assert jobs.enqueue(conn, PAGE, UNIVERSITY)[1:] == (job_id, False)
    assert jobs.claim_next(conn) == job_id and jobs.claim_next(conn) is None

    st = jobs.run_job(conn, job_id, store_for(tmp_path, pages), notify)
    assert st == "review", status_of(conn, job_id)
    row = conn.execute(
        "SELECT records_count, quotes_checked, quotes_found, documents, diff FROM source_jobs"
        " WHERE id = %s",
        (job_id,),
    ).fetchone()
    assert row[:3] == (3, 3, 3)
    assert [d["url"] for d in row[3]] == [safe_url(XLSX)]  # список поступающих отброшен
    diff = row[4]
    assert (diff["added"], diff["removed"], diff["changed"]) == (3, 0, 0)
    example = diff["examples"]["added"][0]
    assert example["quote"] and example["program"] == "37.03.01"
    assert len(diff["examples"]["added"]) == 3
    assert sent == [
        {
            "job_id": job_id,
            "status": "review",
            "university": UNIVERSITY,
            "url": PAGE,
            "records": 3,
            "error": "",
        }
    ]
    assert conn.execute("SELECT kind, last_sha256 <> '' FROM sources").fetchone() == (
        "page",
        True,
    )


def test_accept_writes_records_and_marks_rebuild(
    conn: psycopg.Connection[Any], tmp_path: Any
) -> None:
    _, job_id, _ = jobs.enqueue(conn, XLSX, UNIVERSITY)
    jobs.run_job(conn, job_id, store_for(tmp_path, {XLSX: XLSX_PAGE}))
    assert conn.execute("SELECT kind FROM sources").fetchone() == ("document",)
    assert jobs.accept_job(conn, job_id, "оператор") == 3
    assert conn.execute(
        "SELECT count(*), min(accepted_by), min(document_url) FROM document_records"
    ).fetchone() == (3, "оператор", safe_url(XLSX))
    assert conn.execute("SELECT status, rebuild_needed FROM source_jobs").fetchone() == (
        "accepted",
        True,
    )
    with pytest.raises(ValueError):
        jobs.accept_job(conn, job_id)

    calls: list[int] = []
    assert jobs.rebuild_pending(conn, lambda: calls.append(1) or False) is False
    assert jobs.rebuild_pending(conn, lambda: calls.append(1) or True) is True
    assert jobs.rebuild_pending(conn, lambda: calls.append(1) or True) is None
    assert calls == [1, 1]
    assert conn.execute(
        "SELECT rebuild_needed, rebuilt_at IS NOT NULL FROM source_jobs"
    ).fetchone() == (
        False,
        True,
    )


def test_reject_leaves_database_untouched(conn: psycopg.Connection[Any], tmp_path: Any) -> None:
    _, job_id, _ = jobs.enqueue(conn, XLSX, UNIVERSITY)
    jobs.run_job(conn, job_id, store_for(tmp_path, {XLSX: XLSX_PAGE}))
    jobs.reject_job(conn, job_id)
    assert status_of(conn, job_id)[0] == "rejected"
    assert conn.execute("SELECT count(*) FROM document_records").fetchone() == (0,)
    with pytest.raises(ValueError):
        jobs.reject_job(conn, job_id)


@pytest.mark.parametrize(
    ("url", "pages", "reason"),
    [
        (PAGE, {}, "сайт не ответил"),
        (PAGE, {PAGE: html(("https://example.edu/about", "О вузе"))}, "нет документов"),
        (
            "https://example.edu/doc.pdf",
            {"https://example.edu/doc.pdf": (200, blank_pdf(), "application/pdf")},
            "скан без текста",
        ),
        (
            "https://example.edu/f.xlsx",
            {"https://example.edu/f.xlsx": (200, empty_book(), "application/x")},
            "не нашёл льгот",
        ),
        ("https://example.edu/spisok_postupayushchih.xlsx", {}, "список людей"),
    ],
)
def test_failures_have_plain_reasons(
    conn: psycopg.Connection[Any],
    tmp_path: Any,
    url: str,
    pages: dict[str, tuple[int, bytes, str]],
    reason: str,
) -> None:
    _, job_id, _ = jobs.enqueue(conn, url, UNIVERSITY)
    assert jobs.run_job(conn, job_id, store_for(tmp_path, pages)) == "failed"
    assert reason in status_of(conn, job_id)[1]


def test_diff_marks_changed_and_removed(
    conn: psycopg.Connection[Any], tmp_path: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = store_for(tmp_path, {XLSX: XLSX_PAGE})
    file = pipeline.collect(store, XLSX, UNIVERSITY).files[0]
    first = pipeline.row_of(file.records[0])
    changed = Row(**{**first.__dict__, "winner_role": "winner", "page": None, "quote": ""})
    gone = Row(
        **{
            **first.__dict__,
            "key": (*first.key[:2], "старая", *first.key[3:]),
            "url": safe_url(XLSX),
        }
    )
    monkeypatch.setattr(pipeline, "db_rows", lambda c, f: ([changed, gone], "база"))
    diff = pipeline.compute_diff(conn, [file])
    assert (diff["added"], diff["removed"], diff["changed"]) == (2, 1, 1)
    assert diff["examples"]["changed"][0]["changes"] == {"кому": ["winner", None]}


def test_cli_add_run_accept(
    empty_database_url: str,
    conn: psycopg.Connection[Any],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Any,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "olymp_workers.sources.cli.make_store", lambda cache: store_for(cache, {XLSX: XLSX_PAGE})
    )
    base = ["--database-url", empty_database_url]
    assert cli_main([*base, "add", XLSX, "--university", UNIVERSITY]) == 0
    job_id = conn.execute("SELECT max(id) FROM source_jobs").fetchone()[0]
    assert cli_main([*base, "run", str(job_id)]) == 0
    assert "review" in capsys.readouterr().out
    assert cli_main([*base, "accept", str(job_id)]) == 0
    assert cli_main([*base, "list"]) == 0
    assert "accepted" in capsys.readouterr().out
    assert cli_main([*base, "accept", str(job_id)]) == 1


def checked_source(
    conn: psycopg.Connection[Any], tmp_path: Any, pages: dict[str, tuple[int, bytes, str]]
) -> str:
    _, job_id, _ = jobs.enqueue(conn, XLSX, UNIVERSITY, "test")
    assert jobs.run_job(conn, job_id, store_for(tmp_path, pages)) == "review"
    old_hash = conn.execute("SELECT last_sha256 FROM sources").fetchone()[0]
    conn.execute("UPDATE sources SET last_checked_at = now() - interval '8 days'")
    conn.commit()
    return old_hash


def test_worker_recreates_job_when_source_changed(
    conn: psycopg.Connection[Any],
    empty_database_url: str,
    tmp_path: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked_source(conn, tmp_path, {XLSX: XLSX_PAGE})
    changed = xlsx_bytes() + b"!"
    page = (200, changed, "application/octet-stream")
    monkeypatch.setattr(cli, "make_store", lambda cache: store_for(cache, {XLSX: page}))
    monkeypatch.setenv("OLYMP_SOURCES_RECHECK_DAYS", "0")

    assert cli_main(["--database-url", empty_database_url, "worker", "--once"]) == 0
    assert conn.execute(
        "SELECT status, error FROM source_jobs ORDER BY id DESC LIMIT 1"
    ).fetchone() == (
        "queued",
        "документ изменился",
    )
    assert conn.execute(
        "SELECT last_sha256, last_checked_at IS NOT NULL FROM sources"
    ).fetchone() == (hashlib.sha256(changed).hexdigest(), True)


def test_recheck_unchanged_updates_last_checked(
    conn: psycopg.Connection[Any], tmp_path: Any
) -> None:
    old_hash = checked_source(conn, tmp_path, {XLSX: XLSX_PAGE})
    assert recheck_sources(conn, lambda cache: store_for(cache, {XLSX: XLSX_PAGE}), days=0) is False
    assert conn.execute("SELECT count(*) FROM source_jobs").fetchone() == (1,)
    assert conn.execute(
        "SELECT last_sha256, last_checked_at > now() - interval '1 day' FROM sources"
    ).fetchone() == (old_hash, True)


def test_recheck_site_unavailable_only_logs(
    conn: psycopg.Connection[Any], tmp_path: Any, caplog: pytest.LogCaptureFixture
) -> None:
    old_hash = checked_source(conn, tmp_path, {XLSX: XLSX_PAGE})
    with caplog.at_level(logging.WARNING, logger="olymp.sources"):
        assert recheck_sources(conn, lambda cache: store_for(cache, {}), days=0) is False
    assert "проверка источника" in caplog.text
    assert "HTTP 404" in caplog.text
    assert conn.execute("SELECT count(*), max(error) FROM source_jobs").fetchone() == (1, "")
    assert conn.execute("SELECT last_sha256 FROM sources").fetchone() == (old_hash,)


def grade_of(conn: psycopg.Connection[Any], job_id: int) -> tuple[str, list[str]]:
    return conn.execute(
        "SELECT grade, grade_reasons FROM source_jobs WHERE id = %s", (job_id,)
    ).fetchone()


def test_job_gets_grade_with_reasons(conn: psycopg.Connection[Any], tmp_path: Any) -> None:
    _, job_id, _ = jobs.enqueue(conn, XLSX, UNIVERSITY)
    assert jobs.run_job(conn, job_id, store_for(tmp_path, {XLSX: XLSX_PAGE})) == "review"
    mark, reasons = grade_of(conn, job_id)
    # цитаты на месте, но записей три, а вуза и олимпиад в пустой базе нет
    assert mark == "yellow"
    assert any("записей мало: 3" in r for r in reasons)
    assert any("вуза нет в базе" in r for r in reasons)
    assert any("олимпиад сопоставлено 0%" in r for r in reasons)


def test_failed_job_is_red_with_error_as_reason(
    conn: psycopg.Connection[Any], tmp_path: Any
) -> None:
    _, job_id, _ = jobs.enqueue(conn, XLSX, UNIVERSITY)
    assert jobs.run_job(conn, job_id, store_for(tmp_path, {})) == "failed"
    mark, reasons = grade_of(conn, job_id)
    assert mark == "red" and reasons == [status_of(conn, job_id)[1]]


def result_of(found: int, checked: int, records: int = 12, removed: int = 0) -> pipeline.JobResult:
    file = pipeline.ExtractionFile.model_construct(records=[object()] * records)
    return pipeline.JobResult(
        files=[file], quotes_checked=checked, quotes_found=found, diff={"removed": removed}
    )


@pytest.mark.parametrize(
    ("result", "olympiads", "codes", "expected"),
    [
        (result_of(100, 100), (12, 12), (12, 12, True), "green"),
        (result_of(98, 100), (12, 12), (12, 12, True), "green"),
        (result_of(97, 100), (12, 12), (12, 12, True), "yellow"),  # цитаты слабее 98%
        (result_of(100, 100), (10, 12), (12, 12, True), "yellow"),  # олимпиады 83%
        (result_of(100, 100), (12, 12), (9, 12, True), "yellow"),  # кодов нет у вуза
        (result_of(100, 100, removed=2), (12, 12), (12, 12, True), "yellow"),
        (result_of(100, 100, records=9), (9, 9), (9, 9, True), "yellow"),  # мало записей
        (result_of(89, 100), (12, 12), (12, 12, True), "red"),
    ],
)
def test_grade_thresholds(
    monkeypatch: pytest.MonkeyPatch,
    conn: psycopg.Connection[Any],
    result: pipeline.JobResult,
    olympiads: tuple[int, int],
    codes: tuple[int, int, bool],
    expected: str,
) -> None:
    monkeypatch.setattr(grade, "olympiads_matched", lambda c, f: olympiads)
    monkeypatch.setattr(grade, "codes_existing", lambda c, f: codes)
    graded = grade.grade_job(conn, result)
    assert graded.grade == expected
    assert bool(graded.reasons) == (expected != "green")
