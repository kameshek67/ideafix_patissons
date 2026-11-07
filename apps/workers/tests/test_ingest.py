"""Сборка базы из настоящего XLSX: числа совпадают со сборкой прототипа (ветка main)."""

import psycopg
from olymp_db.session import psycopg_dsn

# итог сборки прототипа на SQLite по тому же файлу data/Olimpiady_BVI_100ballov.xlsx
EXPECTED = {
    "universities": "39",
    "programs": "659",
    "benefits": "49440",
    "benefits_bvi": "27777",
    "benefits_sto": "20859",
    "benefits_raw": "859",
    "benefits_rows": "48963",
    "benefits_derived": "23720",
    "benefits_notes": "477",
    "olympiads": "173",
    "profiles": "635",
    "links": "59098",
    "keywords": "117677",
    "fts": "on",
}


def test_totals_match_prototype(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
    assert {k: meta.get(k) for k in EXPECTED} == EXPECTED
    assert meta["source_file"] == "Olimpiady_BVI_100ballov.xlsx"


def test_no_dangling_links(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        dangling = conn.execute(
            """SELECT COUNT(*) FROM benefit_olympiads bo
               LEFT JOIN olympiad_profiles p ON p.id = bo.profile_id
               WHERE bo.profile_id IS NOT NULL AND p.id IS NULL"""
        ).fetchone()
    assert dangling == (0,)


def test_every_program_has_source(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        missing = conn.execute("SELECT COUNT(*) FROM programs WHERE source_url = ''").fetchone()
        pages = conn.execute("SELECT COUNT(*) FROM universities WHERE docs_url = ''").fetchone()
    assert missing == (0,)
    assert pages == (0,)


def test_search_index_covers_non_derived_rows(built_database_url: str) -> None:
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        indexed, expected = conn.execute(
            """SELECT (SELECT COUNT(*) FROM search_index),
                      (SELECT COUNT(*) FROM benefits WHERE layer <> 'derived')"""
        ).fetchone()
        hits = conn.execute(
            "SELECT COUNT(*) FROM search_index WHERE document @@ to_tsquery('simple', 'физтех:*')"
        ).fetchone()
    assert indexed == expected
    assert hits[0] > 0


def test_benefit_ids_follow_build_order(built_database_url: str) -> None:
    """id льгот выдаёт сборка: последовательность должна быть сдвинута за последний id."""
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        max_id = conn.execute("SELECT MAX(id) FROM benefits").fetchone()[0]
        next_id = conn.execute(
            "SELECT nextval(pg_get_serial_sequence('benefits', 'id'))"
        ).fetchone()[0]
    assert next_id == max_id + 1


def test_extra_points_loaded_with_sources(built_database_url: str) -> None:
    """Баллы за ИД (T-052): строки загружены, у каждой есть источник, вузы из справочника."""
    with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
        meta = dict(conn.execute("SELECT key, value FROM meta").fetchall())
        no_source = conn.execute(
            "SELECT COUNT(*) FROM individual_achievements"
            " WHERE source_url NOT LIKE 'https://%' OR source_quote = '' OR source_page IS NULL"
        ).fetchone()[0]
    assert (meta["extra_rules"], meta["extra_universities"], meta["extra_limits"]) == (
        "223",
        "7",
        "6",
    )
    assert no_source == 0


def test_extra_points_reload_is_idempotent_and_keeps_data_on_error(
    built_database_url: str, tmp_path
) -> None:
    """Перезагрузка баллов при выкате: тот же результат, а ошибка в CSV не стирает данные."""
    import shutil
    from pathlib import Path

    import pytest
    from olymp_workers.extra_points import ExtraPointsDataError, reload_extra_points

    data = Path(__file__).resolve().parents[3] / "data"

    def counts() -> tuple[int, int, str]:
        with psycopg.connect(psycopg_dsn(built_database_url)) as conn:
            rules = conn.execute("SELECT COUNT(*) FROM individual_achievements").fetchone()[0]
            limits = conn.execute("SELECT COUNT(*) FROM individual_achievement_limits").fetchone()[
                0
            ]
            version = conn.execute(
                "SELECT value FROM meta WHERE key = 'extra_points_version'"
            ).fetchone()[0]
        return rules, limits, version

    before = counts()
    assert reload_extra_points(built_database_url, data) == {"rules": 223, "limits": 6}
    assert counts() == before

    broken = tmp_path / "data"
    shutil.copytree(data, broken, ignore=shutil.ignore_patterns("*.xlsx"))
    text = (broken / "individual_achievements.csv").read_text(encoding="utf-8")
    (broken / "individual_achievements.csv").write_text(
        text.replace("Университет ИТМО", "Несуществующий вуз", 1), encoding="utf-8"
    )
    with pytest.raises(ExtraPointsDataError):
        reload_extra_points(built_database_url, broken)
    assert counts() == before
