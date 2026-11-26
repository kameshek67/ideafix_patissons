"""olymp_workers.export_dataset: открытый датасет видимых льгот."""

import gzip
import json
from pathlib import Path

import psycopg
from olymp_db.session import psycopg_dsn
from olymp_workers.export_dataset import export_dataset


def test_export_dataset_from_small_database(empty_database_url: str, tmp_path: Path) -> None:
    output = tmp_path / "release" / "olymp-benefits.jsonl.gz"
    with psycopg.connect(psycopg_dsn(empty_database_url)) as conn:
        try:
            # база общая на прогон: работаем в своей транзакции и ничего не коммитим
            conn.execute("DELETE FROM universities")
            conn.execute("DELETE FROM olympiads")
            university_id = conn.execute(
                "INSERT INTO universities (name, short_name) VALUES ('МГУ', 'МГУ') RETURNING id"
            ).fetchone()[0]
            program_id = conn.execute(
                "INSERT INTO programs (university_id, faculty_or_direction, code) "
                "VALUES (%s, 'Прикладная математика', '01.03.02') RETURNING id",
                (university_id,),
            ).fetchone()[0]
            olympiad_id = conn.execute(
                "INSERT INTO olympiads (canonical_name, short_name, squash_key) "
                "VALUES ('Ломоносов', 'Ломоносов', 'ломоносов') RETURNING id"
            ).fetchone()[0]
            benefit_id = conn.execute(
                "INSERT INTO benefits (program_id, benefit_type, raw_conditions_text, layer, "
                "olympiad_profile, level, winner_role, grade, confirm_subject, min_ege, "
                "source_title, source_url, row_key) "
                "VALUES (%s, 'БВИ', 'условие', 'detailed', 'математика', 'I', 'победитель', '11', "
                "'математика', '75', 'Правила приёма', 'https://example.org/doc', 'key-1') "
                "RETURNING id",
                (program_id,),
            ).fetchone()[0]
            conn.execute(
                "INSERT INTO benefit_olympiads (benefit_id, olympiad_id, profile, level, "
                "winner_role) VALUES (%s, %s, 'математика', 'I', 'победитель')",
                (benefit_id, olympiad_id),
            )
            conn.execute(
                "INSERT INTO benefits (program_id, benefit_type, raw_conditions_text, layer, "
                "row_key) VALUES (%s, 'БВИ', 'черновик', 'raw', 'key-raw')",
                (program_id,),
            )
            count = export_dataset(conn, output, built_at="2026-11-26")
        finally:
            conn.rollback()

    assert count == 1
    with gzip.open(output, "rt", encoding="utf-8") as stream:
        rows = [json.loads(line) for line in stream]
    assert rows == [
        {
            "row_key": "key-1",
            "university": "МГУ",
            "program_code": "01.03.02",
            "program_name": "Прикладная математика",
            "benefit_type": "БВИ",
            "olympiad": "Ломоносов",
            "profile": "математика",
            "level": "I",
            "role": "победитель",
            "grade": "11",
            "ege_subjects": "математика",
            "ege_min": "75",
            "layer": "detailed",
            "source_title": "Правила приёма",
            "source_url": "https://example.org/doc",
            "campaign": 2026,
        }
    ]
    assert json.loads(output.with_name("meta.json").read_text(encoding="utf-8")) == {
        "built_at": "2026-11-26",
        "rows": 1,
        "format_version": "1.0",
        "license": "CC BY 4.0",
        "source": "База «Олимпа», собранная из data/Olimpiady_BVI_100ballov.xlsx",
        "notice": "Данные справочные: условия приёма сверяйте с официальными документами вузов.",
    }
