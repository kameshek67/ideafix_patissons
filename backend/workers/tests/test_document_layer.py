"""Слой document: приём записей документа и чтение их сборкой."""

from collections import Counter
from pathlib import Path
from typing import Any

import psycopg
from olymp_db.session import psycopg_dsn
from olymp_domain.extraction import ExtractionFile, Record
from olymp_workers.document_layer import (
    DOC_SHEET,
    RE_UMBRELLA,
    DocRecord,
    _apply_umbrella,
    _apply_university,
    load_documents,
)
from olymp_workers.document_records import accept_document
from olymp_workers.ingest import Ingestor

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


# -- записи «все олимпиады перечня» ------------------------------------------------------


def umbrella_record(profile: str, levels: list[int], quote: str = "Все из перечня") -> DocRecord:
    record = Record.model_validate(
        {
            "university": "ИТМО",
            "campaign": 2026,
            "program_code": "*",
            "benefit_type": "bvi",
            "olympiad": "Все из перечня олимпиад школьников",
            "profile": profile,
            "levels": levels,
            "winner_role": "both",
            "source": {"url": URL, "sha256": SHA, "page": 3, "quote": quote},
        }
    )
    return DocRecord(record, "Приложение 5")


NEW_PROGRAM = -1  # направления с таким id нет: в базе у него нет льгот


class FakeIngestor:
    """Достаточно от Ingestor для раскрытия: справочник из базы и запись вставок в список."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn
        self.olympiad_kinds = dict(conn.execute("SELECT id, kind FROM olympiads").fetchall())
        self.olympiad_names = dict(
            conn.execute(
                "SELECT id, COALESCE(NULLIF(short_name, ''), canonical_name) FROM olympiads"
            )
        )
        self.inserted: list[tuple[Any, int, str, str]] = []

    def profile_index(self) -> Any:
        return Ingestor.profile_index(self)  # type: ignore[arg-type]

    def insert_benefit(self, detail: Any, program_id: int, layer: str, source_sheet: str) -> int:
        self.inserted.append((detail, program_id, layer, source_sheet))
        return len(self.inserted)


def expand(conn: psycopg.Connection, recs: list[DocRecord], program_id: int) -> FakeIngestor:
    ing = FakeIngestor(conn)
    _apply_umbrella(ing, recs, {}, [program_id], Counter(), lambda _: None)  # type: ignore[arg-type]
    return ing


def test_umbrella_name_detected() -> None:
    for name in (
        "Все из перечня олимпиад школьников",
        "Все олимпиады школьников соответствующего уровня, включенные в Перечень олимпиад школьников",
    ):
        assert RE_UMBRELLA.search(name)
    for name in ("Всероссийская олимпиада школьников", "Олимпиады из перечня РСОШ"):
        assert not RE_UMBRELLA.search(name)


def test_umbrella_expands_to_rsosh_profile_pairs(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        ing = expand(conn, [umbrella_record("Информатика", [1, 2, 3], "цитата")], NEW_PROGRAM)
        assert ing.inserted
        olympiads = {d.olympiad_id for d, *_ in ing.inserted}
        assert len(olympiads) > 1  # по всем олимпиадам перечня с профилем «Информатика»
        assert {ing.olympiad_kinds[o] for o in olympiads} == {"rsosh"}
        for detail, _, layer, sheet in ing.inserted:
            assert (layer, sheet) == ("derived", DOC_SHEET)
            assert detail.olympiad_profile.lower().startswith("информатик")
            assert (detail.source_quote, detail.source_page) == ("цитата", 3)
            assert detail.source_title == "Приложение 5"
        pairs = [(d.olympiad_id, d.olympiad_profile) for d, *_ in ing.inserted]
        assert len(pairs) == len(set(pairs))


def test_umbrella_respects_levels(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        pid = NEW_PROGRAM
        every = expand(conn, [umbrella_record("Математика", [1, 2, 3])], pid).inserted
        third = expand(conn, [umbrella_record("Математика", [3])], pid).inserted
        assert 0 < len(third) < len(every)
        assert {d.level for d, *_ in third} <= {"III", "I, II, III"}  # III или уровень не определён


def test_umbrella_skips_existing_rows_and_repeats(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        pid, olympiad_id, profile = conn.execute(
            """SELECT b.program_id, bo.olympiad_id, p.name
               FROM benefits b JOIN benefit_olympiads bo ON bo.benefit_id = b.id
               JOIN olympiad_profiles p ON p.id = bo.profile_id
               JOIN olympiads o ON o.id = bo.olympiad_id
               WHERE b.layer = 'detailed' AND b.benefit_type = 'БВИ' AND o.kind = 'rsosh'
                 AND p.mentions >= 2 AND p.level <> '' ORDER BY b.id LIMIT 1"""
        ).fetchone()
        level = {"I": 1, "II": 2, "III": 3}[
            conn.execute(
                "SELECT level FROM olympiad_profiles WHERE olympiad_id = %s AND name = %s",
                (olympiad_id, profile),
            ).fetchone()[0]
        ]
        rec = umbrella_record(profile, [level])
        ing = expand(conn, [rec, rec], pid)  # запись дважды: повтор строк не создаётся
        pairs = [(d.olympiad_id, d.olympiad_profile) for d, *_ in ing.inserted]
        assert len(pairs) == len(set(pairs))
        assert (olympiad_id, profile) not in pairs  # такая пара у направления уже есть


def test_umbrella_without_known_profile_adds_nothing(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        ing = expand(conn, [umbrella_record("Несуществующий профиль", [1, 2, 3])], NEW_PROGRAM)
        assert ing.inserted == []


def grade_record(grades: list[int], role: str = "both") -> DocRecord:
    record = Record.model_validate(
        {
            "university": "МАИ",
            "campaign": 2026,
            "program_code": "01.03.01",
            "benefit_type": "bvi",
            "olympiad": "Высшая проба",
            "profile": "математика",
            "levels": [1],
            "grades": grades,
            "winner_role": role,
            "source": {"url": URL, "sha256": SHA, "page": 1, "quote": f"классы {grades}"},
        }
    )
    return DocRecord(record, "Приложение")


def test_records_differing_by_grades_are_both_kept(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        uid = conn.execute("SELECT id FROM universities ORDER BY id LIMIT 1").fetchone()[0]
        conn.execute(
            "INSERT INTO programs (university_id, code, faculty_or_direction)"
            " VALUES (%s, '01.03.01', 'Математика')",
            (uid,),
        )
        ing = FakeIngestor(conn)
        oid = conn.execute(
            "SELECT id FROM olympiads WHERE canonical_name ILIKE %s", ("%Высшая проба%",)
        ).fetchone()[0]
        ing.olympiad_id_for = lambda name: oid  # type: ignore[attr-defined]
        recs = [grade_record([11]), grade_record([10]), grade_record([10])]
        stats: Counter[str] = Counter()
        _apply_university(ing, uid, recs, {}, stats, lambda _: None)  # type: ignore[arg-type]
        assert stats["added"] == 2 and stats["duplicates"] == 1
        assert sorted(d.grade for d, *_ in ing.inserted) == ["10 класс", "11 класс"]
        conn.rollback()
