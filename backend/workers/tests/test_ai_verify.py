import csv
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from olymp_db.session import psycopg_dsn
from olymp_domain.verify import (
    CONFIRMED,
    CONTRADICTED,
    DRY_RUN,
    NO_DOCUMENT,
    NO_MENTION,
    UNVERIFIED,
)
from olymp_llm import LLMError, TextDelta
from olymp_llm.fake import FakeProvider
from olymp_workers.ai import verify
from olymp_workers.ai.documents import Document, DocumentError, DocumentStore


class FakeStore(DocumentStore):
    """Документы без сети: у каждого адреса одни и те же страницы."""

    def __init__(self, pages: tuple[str, ...] | None) -> None:
        super().__init__(Path("/nonexistent"))
        self.pages = pages
        self.asked: list[str] = []

    def get(self, url: str) -> Document:
        self.asked.append(url)
        if self.pages is None:
            raise DocumentError("HTTP 404")
        return Document(url, url, "pdf", "0" * 64, self.pages)


@pytest.fixture
def rows(built_database_url: str) -> Iterator[list[verify.Row]]:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        ids = verify.candidate_ids(conn, "detailed", "итмо")
        yield verify.load_rows(conn, verify.pick(ids, None, 3, 1))


def page_for(row: verify.Row) -> str:
    return (
        f"Направление {row.program_code} {row.program}. Победителям и призёрам олимпиады "
        f"«{row.olympiads[0]}» предоставляется право {row.benefit_type} при подтверждении ЕГЭ."
    )


def answer(verdict: str, quote: str, mismatches: str = "[]") -> list[Any]:
    return [
        TextDelta(
            f'{{"verdict": "{verdict}", "page": "P1", "quote": "{quote}", '
            f'"mismatches": {mismatches}, "comment": "=SUM(A1)"}}'
        )
    ]


def run(rows: list[verify.Row], store: DocumentStore, provider: Any, **kw: Any) -> verify.RunResult:
    import asyncio

    return asyncio.run(
        verify.run(rows, store, provider, max_requests=kw.get("max_requests", 50), progress=False)
    )


def test_rows_have_what_search_needs(rows: list[verify.Row]) -> None:
    assert len(rows) == 3
    for row in rows:
        assert row.university.startswith("Университет ИТМО")
        assert row.olympiads and row.aliases
        assert row.candidate_documents()
        assert "id" not in " ".join(row.claims())


def test_sample_is_reproducible(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        ids = verify.candidate_ids(conn, "detailed", None)
    assert verify.pick(ids, 5, None, 7) == verify.pick(ids, 5, None, 7)
    assert verify.pick(ids, 5, None, 7) != verify.pick(ids, 5, None, 8)


def test_verdicts_are_checked_by_code(rows: list[verify.Row], tmp_path: Path) -> None:
    pages = tuple(page_for(r) for r in rows)
    first, second, third = rows
    store = FakeStore(("Общие положения",) + pages)
    real_quote = page_for(first).split(". ", 1)[1].rstrip(".")
    provider = FakeProvider(
        [
            answer("confirmed", real_quote),
            answer("confirmed", "Победителям любой олимпиады даётся БВИ на все направления"),
            [TextDelta("не уверен")],
            answer(
                "confirmed",
                page_for(third).split(". ", 1)[1].rstrip("."),
                '[{"field": "min_ege", "document": "80"}]',
            ),
        ]
    )
    result = run(rows, store, provider)
    statuses = [o.verdict.status for o in result.outcomes]
    assert statuses == [CONFIRMED, UNVERIFIED, CONTRADICTED]
    assert result.requests == 4  # третья строка — повтор после ответа не по схеме

    sent = provider.requests[0]["messages"]
    assert sent[0]["role"] == "system"
    assert first.olympiads[0] in sent[1]["content"]
    assert "Общие положения" not in sent[1]["content"]  # страница без олимпиады не ушла модели
    assert provider.requests[0]["tools"] == []

    out = tmp_path / "report.csv"
    verify.write_report(out, result.outcomes, "fake")
    with out.open(encoding="utf-8-sig") as fh:
        report = list(csv.DictReader(fh))
    assert [r["status"] for r in report] == statuses
    assert report[0]["page"] == "2"
    assert report[0]["comment"] == "'=SUM(A1)"  # формула не исполнится в Excel
    assert report[2]["mismatches"] == "min_ege: 80"
    assert report[0]["prompt_version"] == verify.VERIFY_PROMPT_VERSION


def test_no_document_and_no_mention_skip_model(rows: list[verify.Row]) -> None:
    provider = FakeProvider([])
    missing = run(rows[:1], FakeStore(None), provider)
    unrelated = run(rows[:1], FakeStore(("Правила приёма без олимпиад",)), provider)
    assert missing.outcomes[0].verdict.status == NO_DOCUMENT
    assert "HTTP 404" in missing.outcomes[0].verdict.comment
    assert unrelated.outcomes[0].verdict.status == NO_MENTION
    assert provider.requests == []


def test_dry_run_lists_pages(rows: list[verify.Row]) -> None:
    result = run(rows[:1], FakeStore((page_for(rows[0]),)), None)
    assert result.outcomes[0].verdict.status == DRY_RUN
    assert "стр. 1" in result.outcomes[0].verdict.comment


def test_stops_at_request_limit(rows: list[verify.Row]) -> None:
    store = FakeStore(tuple(page_for(r) for r in rows))
    provider = FakeProvider([answer("not_found", "")] * 3)
    result = run(rows, store, provider, max_requests=3)
    # перед строкой нужен запас на повтор (2 запроса): после двух строк по запросу третья
    # могла бы превысить лимит, поэтому прогон останавливается, не превысив его
    assert len(result.outcomes) == 2
    assert result.requests <= 3
    assert "лимит" in result.stopped


def test_stops_when_provider_is_down(rows: list[verify.Row]) -> None:
    store = FakeStore(tuple(page_for(r) for r in rows))
    provider = FakeProvider([[LLMError("x")]] * 3)
    result = run(rows * 2, store, provider)
    assert len(result.outcomes) == verify.MAX_ERRORS_IN_ROW
    assert "провайдер" in result.stopped


def test_cli_requires_model_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("OLYMP_LLM_BASE_URL", "OLYMP_LLM_API_KEY", "OLYMP_LLM_MODEL"):
        monkeypatch.delenv(name, raising=False)
    assert verify.main(["--limit", "1"]) == 2


@pytest.mark.parametrize(
    ("query", "name", "expected"),
    [
        ("мгу", "МГУ им. М.В. Ломоносова", True),
        ("мгу", "РГУ нефти и газа им. И.М. Губкина", False),
        ("итмо", "Университет ИТМО", True),
        ("вшэ пермь", "НИУ ВШЭ — Пермь", True),
        ("вшэ пермь", "НИУ ВШЭ (Москва)", False),
        (None, "любой", True),
    ],
)
def test_university_filter(query: str | None, name: str, expected: bool) -> None:
    assert verify.matches_university(query, name) is expected
