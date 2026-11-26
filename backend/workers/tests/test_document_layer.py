"""Слой document: приём записей документа и чтение их сборкой."""

from pathlib import Path

import psycopg
from olymp_db.session import psycopg_dsn
from olymp_domain.extraction import ExtractionFile
from olymp_workers.document_layer import load_documents
from olymp_workers.document_records import accept_document

URL = "https://example.org/doc.pdf"
SHA = "a" * 64


def extraction(*codes: str, url: str = URL, title: str = "Приложение") -> ExtractionFile:
    return ExtractionFile.model_validate(
        {
            "document": {
                "university": "МАИ",
                "campaign": 2026,
                "url": url,
                "sha256": SHA,
                "title": title,
                "pages": [1],
            },
            "records": [
                {
                    "university": "МАИ",
                    "campaign": 2026,
                    "program_code": code,
                    "benefit_type": "bvi",
                    "olympiad": "Высшая проба",
                    "profile": "математика",
                    "levels": [1],
                    "winner_role": "both",
                    "source": {
                        "url": url,
                        "sha256": SHA,
                        "page": 1,
                        "quote": f"{code} Высшая проба",
                    },
                }
                for code in codes
            ],
        }
    )


def test_accept_replaces_records_of_same_url(built_database_url: str, tmp_path: Path) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        assert (
            accept_document(conn, extraction("01.03.01", "01.03.02"), accepted_by="оператор") == 2
        )
        assert accept_document(conn, extraction("*"), accepted_by="оператор") == 1
        other = extraction("09.03.01", url="https://example.org/other.pdf")
        accept_document(conn, other, origin="file")
        rows = conn.execute(
            "SELECT document_url, record->>'program_code', origin, accepted_by"
            " FROM document_records ORDER BY id"
        ).fetchall()
        assert rows == [
            (URL, "*", "operator", "оператор"),
            ("https://example.org/other.pdf", "09.03.01", "file", ""),
        ]
        records = load_documents(conn, tmp_path)
        assert sorted(r.record.program_code for r in records) == ["*", "09.03.01"]
        assert {r.title for r in records} == {"Приложение"}
        conn.rollback()


def test_accepted_records_override_file_with_same_url(
    built_database_url: str, tmp_path: Path
) -> None:
    (tmp_path / "doc.json").write_text(extraction("01.03.01", "01.03.02").model_dump_json())
    (tmp_path / "file-only.json").write_text(
        extraction("02.03.01", url="https://example.org/file.pdf").model_dump_json()
    )
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        assert len(load_documents(conn, tmp_path)) == 3
        accept_document(conn, extraction("38.03.01", title="Принятый"))
        records = load_documents(conn, tmp_path)
        assert sorted(r.record.program_code for r in records) == ["02.03.01", "38.03.01"]
        assert {r.title for r in records if r.record.program_code == "38.03.01"} == {"Принятый"}
        conn.rollback()
